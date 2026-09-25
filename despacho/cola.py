"""Búfer acotado productor-consumidor entre procesos, con semáforos (solución clásica).

    vacios  = BoundedSemaphore(K)   espacios libres  (el productor espera si llega a 0)
    llenos  = Semaphore(0)          elementos listos (el consumidor espera si llega a 0)
    mutex_lectura / mutex_escritura exclusión mutua entre consumidores / entre productores

    productor:  P(vacios); P(mutex_e); escribir; V(mutex_e); V(llenos)
    consumidor: P(llenos); P(mutex_l); leer;     V(mutex_l); V(vacios)

El búfer físico es un pipe del kernel. Los semáforos garantizan que nunca haya más de K
mensajes en él y que un consumidor sólo lea cuando ya hay un mensaje completo.

Diferencia clave con multiprocessing.Queue: aquí el consumidor espera en `llenos` SIN
retener ningún lock; el mutex de lectura se toma sólo durante la lectura de un mensaje
(microsegundos). multiprocessing.Queue.get() retiene su lock de lectores durante toda la
espera, así que si el proceso que lo tiene muere, ningún consumidor vuelve a leer
(hallazgo H3 en la bitácora).
"""

import pickle
import queue


class ColaAcotada:
    def __init__(self, ctx, capacidad: int):
        self.capacidad = capacidad
        self._lector, self._escritor = ctx.Pipe(duplex=False)
        self._vacios = ctx.BoundedSemaphore(capacidad)
        self._llenos = ctx.Semaphore(0)
        self._mutex_lectura = ctx.Lock()
        self._mutex_escritura = ctx.Lock()

    def put(self, obj, block: bool = True, timeout: float | None = None) -> None:
        if not self._vacios.acquire(block, timeout):
            raise queue.Full
        datos = pickle.dumps(obj)            # serializar fuera de la sección crítica
        with self._mutex_escritura:
            self._escritor.send_bytes(datos)
        self._llenos.release()

    def put_nowait(self, obj) -> None:
        self.put(obj, block=False)

    def get(self, block: bool = True, timeout: float | None = None):
        if not self._llenos.acquire(block, timeout):
            raise queue.Empty
        with self._mutex_lectura:
            datos = self._lector.recv_bytes()
        self._vacios.release()
        return pickle.loads(datos)

    def get_nowait(self):
        return self.get(block=False)

    def qsize(self) -> int:
        """Elementos en la cola: valor actual del semáforo `llenos` (sem_getvalue)."""
        return self._llenos.get_value()
