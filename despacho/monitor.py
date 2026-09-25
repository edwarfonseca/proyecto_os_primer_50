"""Hilo monitor del principal: estado del sistema en vivo (requisito 12).

Cada `intervalo` segundos registra una línea ESTADO y una fila en <log>.estado.csv con:
    recibidas       solicitudes que llegaron (generadores)
    en_cola         solicitudes pendientes en la cola: valor del semáforo `llenos` menos los
                    centinelas de cierre que aún están en ella
    en_proceso      tomadas de la cola y aún no finalizadas
    esperando_veh   despachadores bloqueados esperando un vehículo libre
    asignados       vehículos con una solicitud asignada (y cuál)
    disponibles     vehículos libres
    finalizadas     entregadas + canceladas

Además vigila el progreso: si hay trabajo pendiente y ninguna solicitud finaliza durante
`alerta` segundos, avisa SIN PROGRESO (síntoma de interbloqueo, inanición o proceso caído).
"""

import csv
import threading
import time


class Monitor(threading.Thread):
    def __init__(self, centro, ruta_csv, intervalo: float, alerta: float, log):
        super().__init__(name="monitor", daemon=True)
        self.centro = centro
        self.ruta_csv = ruta_csv
        self.intervalo = intervalo
        self.alerta = alerta
        self.log = log
        self.fin = threading.Event()
        self.alertas = 0

    def foto(self) -> dict:
        c = self.centro
        k = c.contadores.foto()
        flota = c.flota.foto()
        asignados = sum(1 for x in flota if x)
        finalizadas = k["entregadas"] + k["canceladas"]
        return {
            "recibidas": sum(g.generadas for g in c.generadores),
            # El semáforo cuenta todo lo que hay en la cola, también los centinelas de cierre.
            "en_cola": c.cola.qsize() - (c.centinelas_enviados - k["centinelas"]),
            "en_proceso": k["tomadas"] - finalizadas,
            "esperando_veh": k["esperando_vehiculo"],
            "asignados": asignados,
            "disponibles": len(flota) - asignados,
            "entregadas": k["entregadas"],
            "canceladas": k["canceladas"],
            "finalizadas": finalizadas,
            "flota": flota,
        }

    def run(self):
        t0 = time.monotonic()
        previas, t_ultimo_avance, avisado = 0, t0, False
        campos = ["t_s", "recibidas", "en_cola", "en_proceso", "esperando_veh", "asignados",
                  "disponibles", "entregadas", "canceladas", "finalizadas", "rendimiento"]
        with open(self.ruta_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(campos)
            while not self.fin.wait(self.intervalo):
                ahora = time.monotonic()
                e = self.foto()
                rendimiento = (e["finalizadas"] - previas) / self.intervalo
                w.writerow([round(ahora - t0, 2)] + [e[c] for c in campos[1:-1]] +
                           [round(rendimiento, 2)])
                f.flush()
                self.log.info(
                    "ESTADO | recibidas=%d en_cola=%d en_proceso=%d (esperando vehículo=%d) | "
                    "vehículos: asignados=%d disponibles=%d [%s] | finalizadas=%d "
                    "(entregadas=%d canceladas=%d) | %.1f/s", e["recibidas"], e["en_cola"],
                    e["en_proceso"], e["esperando_veh"], e["asignados"], e["disponibles"],
                    " ".join(f"V{i + 1}:{s or '-'}" for i, s in enumerate(e["flota"])),
                    e["finalizadas"], e["entregadas"], e["canceladas"], rendimiento,
                    extra={"resumen": True})

                pendiente = e["en_cola"] + e["en_proceso"]
                if e["finalizadas"] != previas or not pendiente:
                    t_ultimo_avance, avisado = ahora, False
                elif not avisado and ahora - t_ultimo_avance >= self.alerta:
                    avisado = True
                    self.alertas += 1
                    self.log.warning("SIN PROGRESO: %d solicitudes pendientes (%d en cola, %d en "
                                     "proceso) y ninguna finalizada en %.0f s: posible "
                                     "interbloqueo, inanición o proceso caído", pendiente,
                                     e["en_cola"], e["en_proceso"], ahora - t_ultimo_avance)
                previas = e["finalizadas"]
