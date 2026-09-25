"""Proceso taller: sus hilos inspectores revisan vehículos en los andenes de cargue.

Una inspección reserva primero un andén (lo alista) y luego necesita el vehículo en ese
andén: orden andén -> vehículo, el OPUESTO al del cargue que hacen los despachadores
(vehículo -> andén). Esa diferencia de orden es la que hace posible el interbloqueo.
"""

import os
import random
import signal
import threading
import time

from . import registro, so_utils
from .recursos import Abortado

SONDEO = 0.1


def proceso_taller(detener, listos, recursos, cfg) -> None:
    so_utils.nombrar_proceso("taller")
    signal.signal(signal.SIGINT, signal.SIG_IGN)     # el principal coordina el cierre
    so_utils.habilitar_volcado_hilos()
    log = registro.configurar(cfg.ruta_log)

    ppid_original = os.getppid()
    parar = threading.Event()
    hilos = [Inspector(i, recursos, detener, parar, cfg, log)
             for i in range(1, cfg.inspectores + 1)]
    for h in hilos:
        h.start()
    log.info("INICIO taller con %d hilos inspectores", len(hilos))
    listos.release()

    while any(h.is_alive() for h in hilos):
        if not parar.is_set() and os.getppid() != ppid_original:
            log.warning("HUÉRFANO: el principal (PID %d) terminó; adoptado por PID %d. "
                        "Se detienen los inspectores", ppid_original, os.getppid())
            parar.set()
        time.sleep(SONDEO)
    for h in hilos:
        h.join()
    log.info("FIN taller | inspecciones: %s",
             ", ".join(f"{h.name}={h.inspecciones}" for h in hilos))


class Inspector(threading.Thread):
    def __init__(self, idx, recursos, detener, parar, cfg, log):
        super().__init__(name=f"inspector-{idx}")
        self.slot = recursos.slot_inspector(idx)
        self.recursos = recursos
        self.detener = detener
        self.parar = parar
        self.cfg = cfg
        self.log = log
        self.rng = random.Random(cfg.semilla * 7919 + idx)
        self.inspecciones = 0

    def run(self):
        rc = self.recursos
        while not (self.detener.value or self.parar.is_set()):
            self._dormir(self.rng.uniform(*self.cfg.intervalo_inspeccion))
            if self.detener.value or self.parar.is_set():
                break
            v = self.rng.randrange(rc.nv)
            d = self.rng.randrange(rc.na)
            self.log.info("INSPECCIÓN pide %s y luego %s", rc.nombre_recurso(rc.anden(d)),
                          rc.nombre_recurso(v))
            try:
                # Orden natural de la inspección: andén -> vehículo.
                reintentos = rc.con_dos(self.slot, rc.anden(d), v,
                                        antes=self.cfg.alistar_anden,
                                        durante=self.rng.uniform(0.05, 0.15),
                                        detener=self.detener, log=self.log)
            except Abortado:
                break
            self.inspecciones += 1
            rc.registrar_operacion(1)
            self.log.info("INSPECCIÓN terminada: %s en %s%s", rc.nombre_recurso(v),
                          rc.nombre_recurso(rc.anden(d)),
                          f" ({reintentos} reintentos)" if reintentos else "")

    def _dormir(self, segundos):
        limite = time.monotonic() + segundos
        while not (self.detener.value or self.parar.is_set()) and time.monotonic() < limite:
            time.sleep(min(SONDEO, max(0.0, limite - time.monotonic())))
