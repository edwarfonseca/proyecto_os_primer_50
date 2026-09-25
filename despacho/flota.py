"""Flota de vehículos compartida entre todos los procesos e hilos despachadores.

El estado vive en memoria compartida (multiprocessing.RawArray, un archivo de /dev/shm
mapeado por todos los procesos):  estado[v] = 0 si el vehículo v está libre, o el id
de la solicitud que lo tiene asignado.

Asignar un vehículo es una operación compuesta "check-then-act":
    1. buscar un vehículo con estado 0          (check)
    2. validar el vehículo (ventana de tiempo)
    3. escribir el id de la solicitud           (act)

--modo inseguro  (Fase 3): los pasos se ejecutan sin exclusión mutua. Dos despachadores
                 que hacen el paso 1 antes de que alguno haga el paso 3 ven el mismo
                 vehículo libre y ambos se lo asignan: DOBLE ASIGNACIÓN.
--modo seguro    (Fase 4): un mutex compartido (multiprocessing.Lock) convierte la
                 búsqueda y el marcado en una sección crítica indivisible.
                 --seccion fina:   se reserva el vehículo dentro del mutex y se valida
                                   fuera (el vehículo ya es exclusivo): sección mínima.
                 --seccion gruesa: la validación también queda dentro del mutex.

--espera activa      sin vehículos libres, el despachador reintenta cada --reintento s.
--espera bloqueante  un semáforo contador (BoundedSemaphore(V)) representa los vehículos
                     libres: P() antes de buscar, V() al liberar. Sin vehículos, el hilo
                     se bloquea en el kernel (futex) sin consumir CPU.

Detección (no corrige nada, sólo observa): una "sonda" cuenta los ocupantes reales de
cada vehículo con su propio lock DESPUÉS de marcar, fuera de la ventana de carrera. Si al
registrarse un ocupante ya había otro, hay doble asignación. Al liberar se comprueba que
el registro siga indicando la solicitud que libera (si no, hubo una actualización perdida).
"""

import os
import random
import threading
import time

ESPERA_SEMAFORO = 0.5   # timeout de P(disponibles): permite revisar la orden de parada


class Flota:
    def __init__(self, ctx, cfg, contadores=None):
        self.contadores = contadores
        self.n = cfg.vehiculos
        self.ventana = cfg.ventana
        self.modo = cfg.modo
        self.espera = cfg.espera
        self.seccion = cfg.seccion
        self.reintento = cfg.reintento
        self.estado = ctx.RawArray("i", self.n)     # sin lock propio: el acceso lo decide el modo
        # --- sincronización (modo seguro / espera bloqueante) --------------------------
        self._mutex = ctx.Lock()                     # exclusión mutua de la sección crítica
        self._disponibles = ctx.BoundedSemaphore(self.n)   # vehículos libres
        # --- instrumentación (sonda) -------------------------------------------------
        self._sonda = ctx.Lock()
        self._ocupantes = ctx.RawArray("i", self.n)  # ocupantes reales de cada vehículo
        self._titular = ctx.RawArray("i", self.n)    # última solicitud registrada
        self._titular_pid = ctx.RawArray("i", self.n)
        self._titular_tid = ctx.RawArray("i", self.n)
        self.dobles = ctx.RawValue("i", 0)           # dobles asignaciones detectadas
        self.inconsistencias = ctx.RawValue("i", 0)  # liberaciones con registro ajeno

    # -- asignación -----------------------------------------------------------------

    def asignar(self, id_sol: int, detener, log):
        """Asigna un vehículo a la solicitud.

        Devuelve (vehículo, reintentos, espera_mutex_s); vehículo es None si se ordena la
        parada mientras espera.
        """
        if self.espera == "bloqueante":
            if not self._disponibles.acquire(False):
                log.info("SIN VEHÍCULOS: solicitud %d bloqueada en el semáforo de vehículos "
                         "libres", id_sol)
                self._esperando(+1)
                try:
                    while not self._disponibles.acquire(timeout=ESPERA_SEMAFORO):
                        if detener.value:
                            return None, 0, 0.0
                finally:
                    self._esperando(-1)
        return self._buscar_con_reintentos(id_sol, detener, log)

    def _esperando(self, n: int) -> None:
        if self.contadores:
            self.contadores.sumar("esperando_vehiculo", n)

    def _buscar_con_reintentos(self, id_sol, detener, log):
        # `reintentos` es local: cada hilo tiene la suya. Un atributo del objeto Flota lo
        # compartirían todos los hilos del proceso y sería una condición de carrera.
        reintentos, espera_mutex = 0, 0.0
        try:
            while True:
                v, espera = self._buscar_y_marcar(id_sol)
                espera_mutex += espera
                if v is not None:
                    self._registrar_ocupante(v, id_sol, log)
                    return v, reintentos, espera_mutex
                if detener.value:
                    if self.espera == "bloqueante":
                        self._disponibles.release()
                    return None, reintentos, espera_mutex
                if reintentos == 0:
                    log.info("SIN VEHÍCULOS: solicitud %d reintenta cada %.3f s (espera activa)",
                             id_sol, self.reintento)
                    self._esperando(+1)
                reintentos += 1
                time.sleep(self.reintento)
        finally:
            if reintentos:
                self._esperando(-1)

    def _buscar_y_marcar(self, id_sol: int) -> tuple[int | None, float]:
        """Devuelve (vehículo marcado o None, segundos esperando el mutex)."""
        if self.modo == "inseguro":
            return self._buscar_y_marcar_sin_exclusion(id_sol), 0.0

        t0 = time.monotonic()
        with self._mutex:                            # --- inicio de la sección crítica
            espera = time.monotonic() - t0
            v = self._primer_libre()                 # (1) check
            if v is not None:
                if self.seccion == "gruesa" and self.ventana:
                    time.sleep(self.ventana)         # (2) validación dentro del mutex
                self.estado[v] = id_sol              # (3) act
        #                                            # --- fin de la sección crítica
        if v is not None and self.seccion == "fina" and self.ventana:
            time.sleep(self.ventana)                 # (2) validación: el vehículo ya es suyo
        return v, espera

    def _buscar_y_marcar_sin_exclusion(self, id_sol: int) -> int | None:
        # Cada búsqueda empieza en un vehículo al azar (simula elegir el más cercano), así
        # no todos los despachadores compiten siempre por el primero de la lista.
        inicio = random.randrange(self.n)
        for i in range(self.n):
            v = (inicio + i) % self.n
            if self.estado[v] == 0:                  # (1) check: el vehículo parece libre
                if self.ventana:
                    time.sleep(self.ventana)         # (2) validación del vehículo
                self.estado[v] = id_sol              # (3) act: se marca como asignado
                return v
        return None

    def _primer_libre(self) -> int | None:
        inicio = random.randrange(self.n)
        for i in range(self.n):
            v = (inicio + i) % self.n
            if self.estado[v] == 0:
                return v
        return None

    # -- liberación -----------------------------------------------------------------

    def liberar(self, v: int, id_sol: int, log) -> None:
        # La sonda se actualiza ANTES de que el vehículo quede libre para otro; al revés,
        # un nuevo ocupante podría registrarse antes que este descuento (falso positivo).
        with self._sonda:
            self._ocupantes[v] -= 1
            if self._ocupantes[v] == 0:
                self._titular[v] = 0

        if self.modo == "seguro":
            with self._mutex:
                registrado = self.estado[v]
                self.estado[v] = 0
        else:
            registrado = self.estado[v]
            self.estado[v] = 0

        if registrado != id_sol:
            # Otra solicitud sobrescribió el registro (actualización perdida) o ya lo había
            # liberado otra (liberación prematura).
            with self._sonda:
                self.inconsistencias.value += 1
            log.warning("REGISTRO INCONSISTENTE: al liberar V%d el registro indicaba %s, "
                        "no la solicitud %d", v + 1,
                        f"la solicitud {registrado}" if registrado else "'libre'", id_sol)
        if self.espera == "bloqueante":
            self._disponibles.release()              # V(disponibles)

    def foto(self) -> list[int]:
        """Copia del estado de la flota (id de solicitud por vehículo; 0 = libre).

        En modo seguro se lee bajo el mutex: una foto consistente. En modo inseguro se lee
        sin protección, igual que la asignación.
        """
        if self.modo == "seguro":
            with self._mutex:
                return list(self.estado)
        return list(self.estado)

    def libres(self) -> int:
        """Vehículos con estado 0 (lectura sin lock: es una foto aproximada)."""
        return sum(1 for x in self.estado if x == 0)

    # -- instrumentación ------------------------------------------------------------

    def _registrar_ocupante(self, v: int, id_sol: int, log) -> None:
        with self._sonda:
            self._ocupantes[v] += 1
            previo = (self._titular[v], self._titular_pid[v], self._titular_tid[v])
            self._titular[v] = id_sol
            self._titular_pid[v] = os.getpid()
            self._titular_tid[v] = threading.get_native_id()
            conflicto = self._ocupantes[v] > 1
            if conflicto:
                self.dobles.value += 1
        if conflicto:
            ambito = "mismo proceso" if previo[1] == os.getpid() else "entre procesos"
            log.warning("DOBLE ASIGNACIÓN: vehículo V%d asignado a la solicitud %d mientras lo "
                        "usa la solicitud %d (PID %d, TID %d) [%s]", v + 1, id_sol, previo[0],
                        previo[1], previo[2], ambito)
        else:
            log.info("ASIGNADO vehículo V%d a la solicitud %d | libres ~%d/%d",
                     v + 1, id_sol, self.libres(), self.n)
