"""Recursos físicos del centro de despacho y estrategias frente al interbloqueo.

Recursos (numeración global, usada por la estrategia de orden):
    0 .. V-1        vehículo en el patio del centro   (un Lock por vehículo)
    V .. V+A-1      andén de cargue                   (un Lock por andén)

Dos operaciones necesitan un vehículo y un andén a la vez, en orden OPUESTO:
    cargue      (despachador):  vehículo -> andén    prepara el vehículo y luego lo carga
    inspección  (taller):       andén -> vehículo    reserva un andén y luego trae el vehículo

--interbloqueo sin_orden   cada operación toma los recursos en su orden natural, con
                           esperas indefinidas: espera circular posible -> INTERBLOQUEO.
--interbloqueo orden       prevención: todas las operaciones toman los recursos en orden
                           creciente de número global (vehículos antes que andenes).
                           Rompe la condición de ESPERA CIRCULAR.
--interbloqueo timeout     prevención: el segundo recurso se pide con tiempo límite; si
                           vence, se suelta el primero y se reintenta tras una espera
                           aleatoria creciente. Rompe la condición de RETENCIÓN Y ESPERA.
--interbloqueo deteccion   detección y recuperación: se permite el interbloqueo; el
                           vigilante del principal encuentra el ciclo en el grafo de espera
                           y ordena a una víctima que suelte lo que tiene (EXPROPIACIÓN).

Registro compartido (sólo instrumentación): para cada recurso, qué hilo lo tiene; para
cada hilo, qué recurso espera. Con él se construye el grafo de espera (wait-for graph).
Orden de actualización: el dueño se registra DESPUÉS de adquirir y se borra ANTES de
soltar, así el registro nunca muestra un dueño que ya soltó el recurso.
"""

import random
import time

ESPERA_ABORTABLE = 0.05   # sondeo del indicador de aborto en el modo deteccion
BACKOFF_BASE = 0.02       # espera aleatoria base tras un fallo (modo timeout / deteccion)
BACKOFF_MAX = 0.5


class Abortado(Exception):
    """La operación se abandonó (víctima de la recuperación o parada del sistema)."""


class Recursos:
    def __init__(self, ctx, cfg):
        self.nv = cfg.vehiculos
        self.na = cfg.andenes
        self.estrategia = cfg.interbloqueo
        self.timeout = cfg.timeout_recurso
        self.hilos_por_trabajador = cfg.hilos
        self.n_despachadores = cfg.trabajadores * cfg.hilos
        self.n_slots = self.n_despachadores + cfg.inspectores
        self._locks = [ctx.Lock() for _ in range(self.nv + self.na)]
        # --- registro (instrumentación) ----------------------------------------------
        self._reg = ctx.Lock()
        self.dueno = ctx.RawArray("i", self.nv + self.na)   # slot+1 del dueño; 0 = libre
        self.espera = ctx.RawArray("i", self.n_slots)       # recurso+1 que espera; 0 = nada
        self.abortar = ctx.RawArray("b", self.n_slots)      # orden de soltar (víctima)
        # --- contadores (bajo _reg) --------------------------------------------------
        self.reintentos = ctx.RawValue("i", 0)      # fallos por tiempo límite (timeout)
        self.recuperaciones = ctx.RawValue("i", 0)  # víctimas que soltaron (deteccion)
        self.operaciones = ctx.RawArray("i", 2)     # [cargues, inspecciones] completados

    # -- nombres ----------------------------------------------------------------------

    def nombre_recurso(self, r: int) -> str:
        return f"V{r + 1}" if r < self.nv else f"A{r - self.nv + 1}"

    def nombre_slot(self, s: int) -> str:
        if s < self.n_despachadores:
            w, t = divmod(s, self.hilos_por_trabajador)
            return f"despachador-{w + 1}-{t + 1}"
        return f"inspector-{s - self.n_despachadores + 1}"

    def slot_despachador(self, id_trabajador: int, idx: int) -> int:
        return (id_trabajador - 1) * self.hilos_por_trabajador + (idx - 1)

    def slot_inspector(self, idx: int) -> int:
        return self.n_despachadores + idx - 1

    def anden(self, d: int) -> int:
        return self.nv + d

    # -- operación con dos recursos -------------------------------------------------------

    def con_dos(self, slot, primero, segundo, antes, durante, detener, log) -> int:
        """Ejecuta una operación que necesita dos recursos.

        Toma `primero`, trabaja `antes` segundos reteniéndolo, toma `segundo` y trabaja
        `durante` segundos con ambos. Con la estrategia `orden` los recursos se piden en
        orden creciente de número global, sin importar el orden natural de la operación.
        Devuelve los reintentos hechos. Lanza Abortado si se ordena la parada.
        """
        if self.estrategia == "orden":
            primero, segundo = sorted((primero, segundo))
        intentos = 0
        while True:
            if self._tomar(slot, primero, detener, log, con_limite=False):
                try:
                    time.sleep(antes)
                    if self._tomar(slot, segundo, detener, log, con_limite=True):
                        try:
                            time.sleep(durante)
                            return intentos
                        finally:
                            self._soltar(slot, segundo)
                finally:
                    self._soltar(slot, primero)
            # No se consiguió el segundo recurso y se soltó el primero: se rompe la
            # retención y espera. Espera aleatoria creciente antes de reintentar, para que
            # las mismas operaciones no vuelvan a chocar al mismo tiempo (livelock).
            intentos += 1
            if detener.value:
                raise Abortado()
            time.sleep(random.uniform(0, min(BACKOFF_MAX, BACKOFF_BASE * 2 ** intentos)))

    def _tomar(self, slot, r, detener, log, con_limite: bool) -> bool:
        lock = self._locks[r]
        with self._reg:
            self.espera[slot] = r + 1
        ok = False
        try:
            if self.estrategia in ("sin_orden", "orden"):
                ok = lock.acquire()                      # espera indefinida (en el kernel)
            elif self.estrategia == "timeout":
                ok = lock.acquire(timeout=self.timeout) if con_limite else lock.acquire()
            else:
                ok = self._tomar_abortable(slot, r, lock, detener, log)
        finally:
            with self._reg:
                self.espera[slot] = 0
                if ok:
                    self.dueno[r] = slot + 1
                    self.abortar[slot] = 0               # descarta una orden ya innecesaria
                elif self.estrategia == "timeout":
                    self.reintentos.value += 1
        if not ok and self.estrategia == "timeout":
            log.info("TIEMPO LÍMITE: %s no obtuvo %s en %.2f s; suelta lo que tiene y reintenta",
                     self.nombre_slot(slot), self.nombre_recurso(r), self.timeout)
        return ok

    def _tomar_abortable(self, slot, r, lock, detener, log) -> bool:
        """Espera el recurso revisando periódicamente si debe abandonar (víctima o parada)."""
        while not lock.acquire(timeout=ESPERA_ABORTABLE):
            if self.abortar[slot]:
                with self._reg:
                    self.abortar[slot] = 0
                    self.recuperaciones.value += 1
                log.warning("RECUPERACIÓN: %s es la víctima; deja de esperar %s y suelta lo "
                            "que tiene", self.nombre_slot(slot), self.nombre_recurso(r))
                return False
            if detener.value:
                raise Abortado()
        return True

    def _soltar(self, slot, r) -> None:
        with self._reg:
            if self.dueno[r] != slot + 1:
                return                                   # no lo tiene este hilo
            self.dueno[r] = 0
        self._locks[r].release()

    def registrar_operacion(self, tipo: int) -> None:
        with self._reg:
            self.operaciones[tipo] += 1

    def ordenar_abandono(self, slot: int) -> None:
        with self._reg:
            self.abortar[slot] = 1

    # -- grafo de espera --------------------------------------------------------------

    def foto(self, timeout: float = 1.0):
        """Copia consistente del registro: (dueño por recurso, espera por slot)."""
        if not self._reg.acquire(timeout=timeout):
            return None
        try:
            return list(self.dueno), list(self.espera)
        finally:
            self._reg.release()

    @staticmethod
    def ciclos(foto) -> list[list[int]]:
        """Ciclos del grafo de espera. Arista s -> t: el hilo s espera un recurso de t.

        Cada hilo espera a lo sumo un recurso (una arista saliente), así que basta seguir
        las aristas desde cada nodo hasta repetir un nodo (ciclo) o llegar a un hilo que
        no espera nada.
        """
        dueno, espera = foto
        siguiente = {}
        for s, r in enumerate(espera):
            if r and dueno[r - 1]:
                siguiente[s] = dueno[r - 1] - 1
        encontrados, vistos = [], set()
        for inicio in siguiente:
            camino, s = [], inicio
            while s in siguiente and s not in camino and s not in vistos:
                camino.append(s)
                s = siguiente[s]
            if s in camino:
                ciclo = camino[camino.index(s):]
                if frozenset(ciclo) not in {frozenset(c) for c in encontrados}:
                    encontrados.append(ciclo)
            vistos.update(camino)
        return encontrados

    def describir(self, foto, ciclo) -> str:
        dueno, espera = foto
        partes = []
        for s in ciclo:
            tiene = [self.nombre_recurso(r) for r, d in enumerate(dueno) if d == s + 1]
            partes.append(f"{self.nombre_slot(s)} [tiene {','.join(tiene) or '-'}, "
                          f"espera {self.nombre_recurso(espera[s] - 1)}]")
        return " -> ".join(partes + [self.nombre_slot(ciclo[0])])
