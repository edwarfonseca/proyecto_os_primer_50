"""Hilo muestreador del principal: mide CPU y memoria de cada proceso leyendo /proc.

Cada `intervalo` segundos registra, para el principal y cada proceso hijo, el RSS, el PSS,
la memoria privada modificada, los hilos y el tiempo de CPU acumulado. Guarda la serie en
un CSV (<log>.recursos.csv) y conserva los valores inicial, pico y final de cada proceso.
"""

import csv
import threading
import time

from . import so_utils


class Muestreador(threading.Thread):
    def __init__(self, procesos, ruta_csv, intervalo: float):
        super().__init__(name="muestreador", daemon=True)
        self.procesos = procesos            # función -> [(pid, nombre)]
        self.ruta_csv = ruta_csv
        self.intervalo = intervalo
        self.fin = threading.Event()
        self.series: dict[str, list[dict]] = {}

    def run(self):
        t0 = time.monotonic()
        with open(self.ruta_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "pid", "proceso", "estado", "hilos", "rss_kb", "pss_kb",
                        "privada_kb", "cpu_s"])
            while True:
                t = round(time.monotonic() - t0, 2)
                for pid, nombre in self.procesos():
                    i = so_utils.info_proceso(pid)
                    if not i or i["estado"].startswith("Z"):
                        continue        # terminó: un zombi ya no tiene memoria (sin VmRSS)
                    m = so_utils.memoria_proceso(pid)
                    fila = {"t": t, "rss": i["rss_kb"], "pss": m.get("Pss", 0),
                            "privada": m.get("Private_Dirty", 0), "cpu": i["cpu_s"],
                            "hilos": i["hilos"]}
                    self.series.setdefault(nombre, []).append(fila)
                    w.writerow([t, pid, nombre, i["estado"][0], i["hilos"], i["rss_kb"],
                                fila["pss"], fila["privada"], f"{i['cpu_s']:.2f}"])
                f.flush()
                if self.fin.wait(self.intervalo):
                    break

    def resumen(self) -> dict[str, dict]:
        out = {}
        for nombre, serie in self.series.items():
            out[nombre] = {
                "rss_ini": serie[0]["rss"], "rss_pico": max(x["rss"] for x in serie),
                "rss_fin": serie[-1]["rss"], "pss_pico": max(x["pss"] for x in serie),
                "privada_pico": max(x["privada"] for x in serie),
                "cpu_s": serie[-1]["cpu"], "hilos_max": max(x["hilos"] for x in serie),
                "duracion": serie[-1]["t"] - serie[0]["t"],
            }
        return out
