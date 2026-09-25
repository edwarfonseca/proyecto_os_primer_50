"""Proceso trabajador: sus hilos despachadores atienden solicitudes de transporte.

Cada trabajador lanza T hilos despachadores (consumidores) que compiten por la cola de
solicitudes compartida con los hilos de los demás trabajadores. El hilo principal del
trabajador sólo los crea, vigila la orfandad y espera a que terminen.
"""

import os
import queue
import signal
import threading
import time

from . import registro, so_utils
from .modelo import CANCELADA, ENTREGADA, Resultado

SONDEO = 0.1        # segundos entre revisiones del hilo principal del trabajador
ESPERA_COLA = 0.5   # timeout de get(): permite revisar las órdenes de parada


def proceso_trabajador(id_trabajador, detener, listos, cola, resultados, flota, cfg) -> None:
    """Punto de entrada del proceso hijo.

    detener:    byte en memoria compartida (RawValue); el principal escribe 1 para abortar.
    listos:     semáforo compartido; cada trabajador hace release() al quedar listo.
    cola:       cola de solicitudes (productor-consumidor) compartida por todos.
    resultados: cola por la que se informa al principal cada solicitud terminada.
    flota:      estado compartido de los vehículos (memoria compartida).
    """
    so_utils.nombrar_proceso(f"trabajador-{id_trabajador}")
    # Ctrl+C envía SIGINT a todo el grupo de procesos del terminal. Sólo el principal
    # debe reaccionar y coordinar el cierre; los trabajadores lo ignoran.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    so_utils.habilitar_volcado_hilos()
    log = registro.configurar(cfg.ruta_log)

    ppid_original = os.getppid()
    parar = threading.Event()       # orden local (mismo proceso) para los despachadores
    hilos = [
        Despachador(id_trabajador, t, cola, resultados, flota, detener, parar, log)
        for t in range(1, cfg.hilos + 1)
    ]
    for h in hilos:
        h.start()
    log.info("INICIO trabajador %d con %d hilos despachadores", id_trabajador, len(hilos))
    listos.release()

    while any(h.is_alive() for h in hilos):
        if not parar.is_set() and os.getppid() != ppid_original:
            # El principal murió sin ordenar el cierre: el kernel re-asignó este proceso
            # a un "subreaper" (o a PID 1). Sin esta comprobación quedaría vivo para siempre.
            log.warning("HUÉRFANO: el principal (PID %d) terminó; adoptado por PID %d. "
                        "Se detienen los despachadores", ppid_original, os.getppid())
            parar.set()
        time.sleep(SONDEO)

    for h in hilos:
        h.join()
    log.info("FIN trabajador %d | atendidas por hilo: %s", id_trabajador,
             ", ".join(f"{h.name}={h.entregadas}" for h in hilos))


class Despachador(threading.Thread):
    """Consumidor: toma una solicitud, le asigna un vehículo, la despacha y la entrega."""

    def __init__(self, id_trabajador, idx, cola, resultados, flota, detener, parar, log):
        super().__init__(name=f"despachador-{id_trabajador}-{idx}")
        self.id_trabajador = id_trabajador
        self.cola = cola
        self.resultados = resultados
        self.flota = flota
        self.detener = detener
        self.parar = parar
        self.log = log
        self.entregadas = 0
        self.canceladas = 0

    def run(self):
        tid = threading.get_native_id()
        ocioso = False
        while True:
            try:
                s = self.cola.get(timeout=ESPERA_COLA)
            except queue.Empty:
                # Cola vacía (o el lock de lectores ocupado por otro consumidor).
                if self.parar.is_set() or self.detener.value:
                    break
                if not ocioso:
                    self.log.info("CONSUMIDOR ESPERANDO: cola vacía")
                    ocioso = True
                continue
            ocioso = False

            if s is None:                   # centinela: no habrá más solicitudes
                self.log.info("CENTINELA recibido: el hilo termina")
                break

            t_inicio = time.monotonic()
            v, reintentos = (None, 0) if self.detener.value else \
                self.flota.asignar(s.id, self.detener, self.log)
            if v is None:
                # Parada solicitada antes de conseguir vehículo: la solicitud se retira sin
                # atenderla y se informa como cancelada para que el balance final cuadre.
                self.canceladas += 1
                self.resultados.put(Resultado(s.id, CANCELADA, self.id_trabajador, self.name,
                                              tid, s.t_llegada, t_inicio, time.monotonic(),
                                              reintentos=reintentos))
                continue
            t_asignado = time.monotonic()

            self.log.info("DESPACHO solicitud %d en V%d (%s: %s -> %s) | esperó en cola %.0f ms"
                          ", por vehículo %.0f ms", s.id, v + 1, s.cliente, s.origen, s.destino,
                          (t_inicio - s.t_llegada) * 1000, (t_asignado - t_inicio) * 1000)
            time.sleep(s.t_despacho)        # preparación y cargue en el centro de despacho
            self.log.info("EN RUTA solicitud %d en V%d", s.id, v + 1)
            time.sleep(s.t_entrega)         # trayecto hasta la entrega
            t_liberado = time.monotonic()
            self.flota.liberar(v, s.id)
            t_fin = time.monotonic()
            self.entregadas += 1
            self.log.info("ENTREGADA solicitud %d | V%d liberado | servicio %.0f ms", s.id,
                          v + 1, (t_fin - t_inicio) * 1000)
            self.resultados.put(Resultado(s.id, ENTREGADA, self.id_trabajador, self.name,
                                          tid, s.t_llegada, t_inicio, t_fin, v, t_asignado,
                                          t_liberado, reintentos))
