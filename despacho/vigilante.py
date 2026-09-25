"""Hilo vigilante del proceso principal: detecta interbloqueos con el grafo de espera.

Cada INTERVALO segundos toma una foto consistente del registro de recursos (quién tiene
cada recurso y qué espera cada hilo), construye el grafo de espera y busca ciclos. Un
ciclo es un interbloqueo: cada hilo del ciclo espera un recurso que tiene el siguiente.
Para descartar fotos tomadas en un instante de transición, el ciclo debe aparecer en dos
fotos consecutivas.

Qué hace al detectarlo:
  - estrategia deteccion: elige una víctima (un inspector si lo hay: aplazar una
    inspección cuesta menos que retrasar un despacho) y le ordena soltar lo que retiene.
  - resto de estrategias: nadie puede romper el ciclo. Registra el diagnóstico, pide a los
    procesos involucrados un volcado de pilas (SIGUSR1 -> faulthandler) y solicita al
    principal detener el sistema.
"""

import os
import signal
import threading
import time

INTERVALO = 0.5
REAVISO = 2.0      # segundos antes de volver a actuar sobre un ciclo que persiste


class Vigilante(threading.Thread):
    def __init__(self, recursos, pid_de_slot, log):
        super().__init__(name="vigilante", daemon=True)
        self.rc = recursos
        self.pid_de_slot = pid_de_slot
        self.log = log
        self.fin = threading.Event()
        self.detectados = 0
        self.aborto_solicitado = False      # lo lee el bucle del principal
        self._avisados: dict[frozenset, float] = {}

    def run(self):
        previos: set[frozenset] = set()
        while not self.fin.wait(INTERVALO):
            foto = self.rc.foto()
            if foto is None:
                continue                    # registro ocupado: se reintenta en la próxima
            ciclos = {frozenset(c): c for c in self.rc.ciclos(foto)}
            for clave, ciclo in ciclos.items():
                if clave in previos and self._toca_actuar(clave):
                    self.detectados += 1
                    self._actuar(foto, ciclo)
            previos = set(ciclos)

    def _toca_actuar(self, clave) -> bool:
        ultimo = self._avisados.get(clave)
        if ultimo is not None and (self.rc.estrategia != "deteccion" or
                                   time.monotonic() - ultimo < REAVISO):
            return False
        self._avisados[clave] = time.monotonic()
        return True

    def _actuar(self, foto, ciclo) -> None:
        rc = self.rc
        self.log.error("INTERBLOQUEO DETECTADO (ciclo en el grafo de espera): %s",
                       rc.describir(foto, ciclo))
        if rc.estrategia == "deteccion":
            victima = max(ciclo, key=lambda s: (s >= rc.n_despachadores, s))
            self.log.warning("RECUPERACIÓN ordenada: víctima %s; se le expropia lo que retiene",
                             rc.nombre_slot(victima))
            rc.ordenar_abandono(victima)
            return
        pids = sorted({self.pid_de_slot(s) for s in ciclo})
        self.log.error("DIAGNÓSTICO: volcado de pilas (SIGUSR1) de los procesos %s. Con la "
                       "estrategia '%s' nadie puede romper el ciclo: se detiene el sistema",
                       pids, rc.estrategia)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass
            # Los procesos comparten stderr: si vuelcan a la vez, sus escrituras se mezclan
            # carácter a carácter. Se escalonan las señales para que cada volcado sea legible.
            time.sleep(0.5)
        self.aborto_solicitado = True
