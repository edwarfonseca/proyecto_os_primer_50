"""Proceso trabajador: atiende solicitudes de transporte.

Fase 1: el trabajador se registra, avisa al principal que está listo y emite latidos
hasta que el principal activa el indicador de parada o el trabajador queda huérfano.
"""

import os
import signal
import time

from . import registro, so_utils

SONDEO = 0.1   # segundos entre revisiones del indicador de parada


def proceso_trabajador(id_trabajador, detener, listos, cfg) -> None:
    """Punto de entrada del proceso hijo.

    detener: byte en memoria compartida (RawValue); el principal escribe 1 para terminar.
    listos:  semáforo compartido; cada trabajador hace release() al quedar listo.
    """
    so_utils.nombrar_proceso(f"trabajador-{id_trabajador}")
    # Ctrl+C envía SIGINT a todo el grupo de procesos del terminal. Sólo el principal
    # debe reaccionar y coordinar el cierre; los trabajadores lo ignoran.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    so_utils.habilitar_volcado_hilos()
    log = registro.configurar(cfg.ruta_log)

    ppid_original = os.getppid()
    log.info("INICIO trabajador %d", id_trabajador)
    listos.release()

    latidos = 0
    proximo_latido = time.monotonic() + cfg.latido
    while not detener.value:
        if os.getppid() != ppid_original:
            # El principal murió sin ordenar el cierre: el kernel re-asignó este proceso
            # a un "subreaper" (o a PID 1). Sin esta comprobación quedaría vivo para siempre.
            log.warning("HUÉRFANO: el principal (PID %d) terminó; adoptado por PID %d. Se termina",
                        ppid_original, os.getppid())
            return
        time.sleep(SONDEO)
        if time.monotonic() >= proximo_latido:
            latidos += 1
            proximo_latido += cfg.latido
            log.info("LATIDO %d", latidos)

    log.info("FIN trabajador %d (latidos=%d)", id_trabajador, latidos)
