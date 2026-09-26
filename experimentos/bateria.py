"""Batería de experimentos de la Fase 8: ejecuta el sistema con muchas configuraciones y
reúne sus métricas en evidencias/fase8/resultados.csv.

Grupos:
    antes_despues  N solicitudes simultáneas en {10, 25, 50, 100, 200} con la versión con
                   la condición de carrera (inseguro + espera activa) y la corregida
                   (seguro + bloqueante).
    interbloqueo   las cuatro estrategias con 24 y 48 solicitudes.
    espera         espera activa frente a bloqueante bajo alta demanda (16 hilos, 2 vehículos).

    python3 experimentos/bateria.py [REPETICIONES] [GRUPOS...]
    python3 experimentos/bateria.py 3                       # todo (≈ 15 min)
    python3 experimentos/bateria.py 1 espera                # un grupo

Cada ejecución deja su log (y sus CSV de estado y recursos) en logs/fase8/.
"""

import csv
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from despacho.metricas import METRICAS, extraer  # noqa: E402  (tras ajustar sys.path)

SALIDA = RAIZ / "evidencias" / "fase8" / "resultados.csv"
LOGS = RAIZ / "logs" / "fase8"

ANTES = ["--modo", "inseguro", "--espera", "activa"]
DESPUES = ["--modo", "seguro", "--espera", "bloqueante"]
# Aísla el fenómeno de cada grupo: sin taller, andenes de sobra, sin carga de CPU/memoria.
AISLADO = ["-i", "0", "-a", "100", "-p", "0", "--traza-kb", "0"]



def configuraciones(grupos):
    if "antes_despues" in grupos:
        for n in (10, 25, 50, 100, 200):
            for version, flags in (("antes", ANTES), ("despues", DESPUES)):
                yield ("antes_despues", f"{version}", n,
                       ["-w", "2", "-t", "3", "-g", "4", "-n", str(n), "-v", "3", "-k", "20",
                        *flags, *AISLADO])
    if "interbloqueo" in grupos:
        for n in (24, 48):
            for estrategia in ("sin_orden", "orden", "timeout", "deteccion"):
                yield ("interbloqueo", estrategia, n,
                       ["-w", "2", "-t", "3", "-g", "4", "-n", str(n), "-v", "3", "-a", "2",
                        "-i", "1", "-p", "0", "--traza-kb", "0", "--interbloqueo", estrategia,
                        "--espera-fin", "1"])
    if "espera" in grupos:
        for nombre, flags in (("bloqueante", ["--espera", "bloqueante"]),
                              ("activa_5ms", ["--espera", "activa", "--reintento", "0.005"]),
                              ("activa_sin_pausa", ["--espera", "activa", "--reintento", "0"])):
            yield ("espera", nombre, 48,
                   ["-w", "4", "-t", "4", "-g", "4", "-n", "48", "-k", "48", "-v", "2",
                    "--ventana", "0", *flags, *AISLADO])


def main():
    repeticiones = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    grupos = set(sys.argv[2:]) or {"antes_despues", "interbloqueo", "espera"}
    LOGS.mkdir(parents=True, exist_ok=True)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not SALIDA.exists()
    campos = ["grupo", "variante", "solicitudes", "repeticion", "exit_code", "duracion_real_s",
              "log", *METRICAS, "interbloqueo_sin_resolver"]
    confs = list(configuraciones(grupos))
    total = len(confs) * repeticiones
    with open(SALIDA, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        if nuevo:
            w.writeheader()
        k = 0
        for rep in range(1, repeticiones + 1):
            for grupo, variante, n, args in confs:
                k += 1
                log = LOGS / f"{grupo}_{variante}_n{n}_r{rep}.log"
                for viejo in (log, log.with_suffix(".estado.csv"), log.with_suffix(".recursos.csv")):
                    viejo.unlink(missing_ok=True)
                t0 = time.monotonic()
                proc = subprocess.run([sys.executable, "main.py", *args, "--log", str(log)],
                                      cwd=RAIZ, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
                fila = {"grupo": grupo, "variante": variante, "solicitudes": n,
                        "repeticion": rep, "exit_code": proc.returncode,
                        "duracion_real_s": round(time.monotonic() - t0, 2),
                        "log": log.relative_to(RAIZ), **extraer(log.read_text(encoding="utf-8"))}
                w.writerow(fila)
                f.flush()
                print(f"[{k}/{total}] {grupo:14} {variante:17} n={n:<4} rep={rep} "
                      f"exit={proc.returncode} dobles={fila['dobles_sonda'] or '-':>3} "
                      f"interbloqueos={fila['interbloqueos'] or '-'} "
                      f"tiempo={fila['tiempo_total_s'] or '-'} s", flush=True)


if __name__ == "__main__":
    main()
