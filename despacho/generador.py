"""Hilos productores: simulan la llegada de solicitudes de transporte.

Cada generador es un hilo del proceso principal. En cada ráfaga todos los generadores
se esperan en una threading.Barrier y se liberan juntos, de modo que sus solicitudes
llegan a la cola en el mismo instante (llegada simultánea).
"""

import itertools
import math
import queue
import random
import threading
import time

from .modelo import Solicitud

CLIENTES = ["Alkosto", "Éxito", "Homecenter", "Falabella", "Jumbo", "Olímpica", "D1", "Ara"]
ZONAS = ["Tunja", "Duitama", "Sogamoso", "Paipa", "Chiquinquirá", "Villa de Leyva",
         "Moniquirá", "Garagoa"]
SONDEO = 0.2


class Generador(threading.Thread):
    def __init__(self, idg, ids, rafagas, cfg, cola, detener, barrera, log):
        super().__init__(name=f"generador-{idg}")
        self.idg = idg
        self.ids = ids                  # range de ids propio (None = continuo)
        self.rafagas = rafagas          # None = continuo
        self.cfg = cfg
        self.cola = cola
        self.detener = detener
        self.barrera = barrera
        self.log = log
        # Semilla propia por generador: la carga no depende del orden de los hilos.
        self.rng = random.Random(cfg.semilla * 1000 + idg)
        # Estadísticas propias del hilo (sólo las escribe este hilo; el principal las lee
        # después de join(), así que no requieren sincronización).
        self.generadas = 0
        self.bloqueos = 0
        self.t_bloqueado = 0.0

    def run(self):
        tam = self.cfg.tam_rafaga or (len(self.ids) if self.ids is not None else 1)
        pendientes = iter(self.ids) if self.ids is not None else itertools.count(self.idg * 10**6)
        rafagas = range(1, self.rafagas + 1) if self.rafagas is not None else itertools.count(1)

        interrumpido = False
        for r in rafagas:
            if self.detener.value:
                interrumpido = True
                break
            lote = [self._crear(i, r) for i in itertools.islice(pendientes, tam)]
            try:
                # Todos los generadores esperan aquí; el último en llegar libera a todos.
                if self.barrera.wait() == 0:
                    self.log.info("RÁFAGA %d: %d generadores liberados simultáneamente",
                                  r, self.barrera.parties)
            except threading.BrokenBarrierError:
                self.log.info("RÁFAGA %d abortada por una parada", r)
                interrumpido = True
                break
            if not all(self._encolar(s) for s in lote):
                interrumpido = True
                break
            if self.rafagas is None or r < self.rafagas:
                self._dormir(self.cfg.intervalo)

        if interrumpido:
            # Sólo en una parada puede quedar otro generador esperando en la barrera.
            # No se hace abort() al terminar normalmente: un generador ya liberado de la
            # última barrera pero que aún no volvió a ejecutarse vería la barrera rota y
            # perdería su ráfaga (hallazgo H4).
            self.barrera.abort()
        self.log.info("FIN generador %d: generadas=%d, bloqueos por cola llena=%d (%.3f s)",
                      self.idg, self.generadas, self.bloqueos, self.t_bloqueado)

    def _crear(self, id_sol, rafaga) -> Solicitud:
        origen, destino = self.rng.sample(ZONAS, 2)
        return Solicitud(
            id=id_sol, cliente=self.rng.choice(CLIENTES), origen=origen, destino=destino,
            generador=self.idg, rafaga=rafaga,
            t_despacho=round(self.rng.uniform(*self.cfg.despacho), 3),
            t_entrega=round(self.rng.uniform(*self.cfg.entrega), 3),
            # Los puntos se sortean al final para no alterar los demás campos de la carga
            # (con --puntos 0 la secuencia aleatoria es la misma de las fases anteriores).
            puntos=tuple((round(self.rng.uniform(0, 100), 1), round(self.rng.uniform(0, 100), 1))
                         for _ in range(self.cfg.puntos)),
        )

    def _encolar(self, s: Solicitud) -> bool:
        """Productor: coloca la solicitud en la cola acotada; se bloquea si está llena."""
        s.t_llegada = time.monotonic()
        try:
            self.cola.put_nowait(s)
        except queue.Full:
            # Cola llena: el semáforo de espacios libres está en 0. El productor debe
            # esperar a que un consumidor retire un elemento (backpressure).
            self.bloqueos += 1
            self.log.info("PRODUCTOR BLOQUEADO: cola llena (%d/%d), solicitud %d espera",
                          self.cfg.capacidad_cola, self.cfg.capacidad_cola, s.id)
            inicio = time.monotonic()
            while True:
                if self.detener.value:
                    return False
                try:
                    self.cola.put(s, timeout=SONDEO)
                    break
                except queue.Full:
                    continue
            espera = time.monotonic() - inicio
            self.t_bloqueado += espera
            self.log.info("PRODUCTOR DESBLOQUEADO tras %.0f ms", espera * 1000)
        self.generadas += 1
        self.log.info("RECIBIDA solicitud %d (ráfaga %d) %s: %s -> %s | en cola ~%d",
                      s.id, s.rafaga, s.cliente, s.origen, s.destino, self.cola.qsize())
        return True

    def _dormir(self, segundos):
        limite = time.monotonic() + segundos
        while not self.detener.value and time.monotonic() < limite:
            time.sleep(min(SONDEO, max(0.0, limite - time.monotonic())))


def crear_generadores(cfg, cola, detener, log) -> list[Generador]:
    """Reparte las solicitudes entre los generadores con ids contiguos y deterministas."""
    k = cfg.generadores
    barrera = threading.Barrier(k)
    if cfg.solicitudes == 0:
        return [Generador(i + 1, None, None, cfg, cola, detener, barrera, log) for i in range(k)]

    base, resto = divmod(cfg.solicitudes, k)
    cuotas = [base + (1 if i < resto else 0) for i in range(k)]
    tam = cfg.tam_rafaga or max(cuotas)
    # Todos hacen el mismo número de ráfagas (aunque alguno tenga lotes vacíos al final)
    # para que ninguno quede esperando solo en la barrera.
    rafagas = max(1, math.ceil(max(cuotas) / tam))
    generadores, inicio = [], 1
    for i, cuota in enumerate(cuotas):
        ids = range(inicio, inicio + cuota)
        generadores.append(Generador(i + 1, ids, rafagas, cfg, cola, detener, barrera, log))
        inicio += cuota
    return generadores
