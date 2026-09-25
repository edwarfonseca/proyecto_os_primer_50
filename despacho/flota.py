"""Flota de vehículos compartida entre todos los procesos e hilos despachadores.

El estado vive en memoria compartida (multiprocessing.RawArray, un archivo de /dev/shm
mapeado por todos los procesos):  estado[v] = 0 si el vehículo v está libre, o el id
de la solicitud que lo tiene asignado.

Fase 3 — versión INSEGURA: la asignación es un "check-then-act" sin exclusión mutua:
    1. buscar un vehículo con estado 0          (check)
    2. validar el vehículo (ventana de tiempo)
    3. escribir el id de la solicitud           (act)
Dos despachadores que hacen el paso 1 antes de que alguno haga el paso 3 ven el mismo
vehículo libre y ambos se lo asignan: DOBLE ASIGNACIÓN.

Detección (no corrige nada, sólo observa): una "sonda" cuenta los ocupantes reales de
cada vehículo con su propio lock DESPUÉS del paso 3, fuera de la ventana de carrera.
Si al registrarse un ocupante ya había otro, hay doble asignación.
"""

import os
import random
import threading
import time

REINTENTO = 0.005   # segundos entre búsquedas cuando no hay vehículos libres


class Flota:
    def __init__(self, ctx, n: int, ventana: float):
        self.n = n
        self.ventana = ventana
        self.estado = ctx.RawArray("i", n)          # sin lock: acceso sin protección
        # --- instrumentación (sonda) -------------------------------------------------
        self._sonda = ctx.Lock()
        self._ocupantes = ctx.RawArray("i", n)       # ocupantes reales de cada vehículo
        self._titular = ctx.RawArray("i", n)         # última solicitud registrada
        self._titular_pid = ctx.RawArray("i", n)
        self._titular_tid = ctx.RawArray("i", n)
        self.dobles = ctx.RawValue("i", 0)           # dobles asignaciones detectadas

    # -- operación ------------------------------------------------------------------

    def asignar(self, id_sol: int, detener, log) -> tuple[int | None, int]:
        """Asigna un vehículo libre a la solicitud. Devuelve (vehículo, reintentos).

        Si no hay vehículos libres reintenta cada REINTENTO segundos (espera activa con
        retardo). Devuelve (None, reintentos) si se ordena la parada mientras espera.
        """
        reintentos = 0
        while True:
            v = self._buscar_y_marcar(id_sol)
            if v is not None:
                self._registrar_ocupante(v, id_sol, log)
                return v, reintentos
            if detener.value:
                return None, reintentos
            if reintentos == 0:
                log.info("SIN VEHÍCULOS: solicitud %d espera un vehículo libre", id_sol)
            reintentos += 1
            time.sleep(REINTENTO)

    def _buscar_y_marcar(self, id_sol: int) -> int | None:
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

    def liberar(self, v: int, id_sol: int) -> None:
        self.estado[v] = 0
        with self._sonda:
            self._ocupantes[v] -= 1
            if self._ocupantes[v] == 0:
                self._titular[v] = 0

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
