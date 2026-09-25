"""Genera las tablas y las gráficas de la Fase 8 a partir de:

    evidencias/fase8/resultados.csv                 (batería: experimentos/bateria.py)
    logs/fase8/antes_despues_*_n100_r1.estado.csv   (serie del monitor; se copia a
                                                     evidencias/fase8/series/)
    evidencias/fase6/e1_cpu_hilos_procesos.txt      (escalamiento de CPU, Fase 6)
    evidencias/fase6/e4_historial_*.recursos.csv    (memoria, Fase 6)

Salida: evidencias/fase8/graficas/*.svg y evidencias/fase8/resumen.md (tablas gemelas de
cada gráfica, con media ± desviación estándar de las repeticiones).

    python3 experimentos/informe_fase8.py
"""

import csv
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

import graficas as g

RAIZ = Path(__file__).resolve().parent.parent
F8 = RAIZ / "evidencias" / "fase8"
F6 = RAIZ / "evidencias" / "fase6"
DIR_G = F8 / "graficas"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def media(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def ms(vals, dec=1):
    """'media ± desviación' de una lista (desviación estándar muestral)."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    m = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return f"{m:.{dec}f} ± {sd:.{dec}f}"


def leer_resultados():
    with open(F8 / "resultados.csv", newline="") as f:
        return list(csv.DictReader(f))


def agrupar(filas, grupo):
    d = defaultdict(list)
    for r in filas:
        if r["grupo"] == grupo:
            d[(r["variante"], int(r["solicitudes"]))].append(r)
    return d


def col(filas, campo):
    return [num(r[campo]) for r in filas]


def seccion_antes_despues(filas, md):
    d = agrupar(filas, "antes_despues")
    ns = sorted({n for _, n in d})
    nombres = {"antes": "Antes (inseguro)", "despues": "Después (corregido)"}
    rep = len(d[("antes", ns[0])])

    md += [f"## 1. Antes / después con distinta cantidad de solicitudes simultáneas",
           "", f"2 trabajadores × 3 hilos, 3 vehículos, todas las solicitudes llegan en una "
           f"ráfaga. {rep} repeticiones por celda (media ± desviación).", "",
           "| Solicitudes | Versión | Dobles asignaciones | % asignaciones en conflicto | "
           "Registros inconsistentes | Entregas simultáneas máx. (3 vehículos) | Tiempo total (s) "
           "| Rendimiento (sol/s) | Espera por vehículo (ms) | Exit 0 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for n in ns:
        for v in ("antes", "despues"):
            fs = d[(v, n)]
            pct = [100 * x / n for x in col(fs, "dobles_sonda") if x is not None]
            ok = sum(1 for r in fs if r["exit_code"] == "0")
            md.append(f"| {n} | {nombres[v]} | {ms(col(fs, 'dobles_sonda'))} | {ms(pct)} % | "
                      f"{ms(col(fs, 'inconsistencias'))} | {ms(col(fs, 'en_ruta_max'))} | "
                      f"{ms(col(fs, 'tiempo_total_s'), 2)} | {ms(col(fs, 'rendimiento'), 2)} | "
                      f"{ms(col(fs, 'espera_vehiculo_ms'), 0)} | {ok}/{len(fs)} |")
    md.append("")

    etq = [str(n) for n in ns]
    g.lineas(DIR_G / "g1_dobles_asignaciones.svg",
             "Dobles asignaciones de vehículo por ejecución",
             f"Media de {rep} ejecuciones · 3 vehículos, 6 despachadores · la versión corregida "
             "no tuvo ninguna", ns,
             [(nombres[v], [media(col(d[(v, n)], "dobles_sonda")) for n in ns])
              for v in ("antes", "despues")],
             "solicitudes simultáneas", "dobles asignaciones", x_etiquetas=etq, numerico=True,
             decimales=1)
    g.lineas(DIR_G / "g2_tiempo_total.svg", "Tiempo total para atender todas las solicitudes",
             "La versión corregida tarda más porque respeta los 3 vehículos; la insegura usa "
             "vehículos ocupados", ns,
             [(nombres[v], [media(col(d[(v, n)], "tiempo_total_s")) for n in ns])
              for v in ("antes", "despues")],
             "solicitudes simultáneas", "segundos", x_etiquetas=etq, numerico=True,
             decimales=1)
    md += ["![Dobles asignaciones](graficas/g1_dobles_asignaciones.svg)", "",
           "![Tiempo total](graficas/g2_tiempo_total.svg)", ""]

    # Serie del monitor para N = 100 (repetición 1 de cada versión).
    series, xs = [], None
    for v in ("antes", "despues"):
        # La serie se copia a evidencias/fase8/series/ (logs/ no se versiona) y se lee de ahí.
        nombre = f"antes_despues_{v}_n100_r1.estado.csv"
        origen, ruta = RAIZ / "logs" / "fase8" / nombre, F8 / "series" / nombre
        if origen.exists():
            ruta.parent.mkdir(exist_ok=True)
            shutil.copyfile(origen, ruta)
        if not ruta.exists():
            continue
        with open(ruta, newline="") as f:
            filas_e = list(csv.DictReader(f))
        t = [float(r["t_s"]) for r in filas_e]
        fin = [float(r["finalizadas"]) for r in filas_e]
        series.append((nombres[v], dict(zip(t, fin))))
        xs = sorted(set(xs or []) | set(t))
    if series:
        g.lineas(DIR_G / "g3_finalizadas_en_el_tiempo.svg",
                 "Solicitudes finalizadas a lo largo de la ejecución (100 solicitudes)",
                 "Registro del monitor, una muestra por segundo", xs,
                 [(nom, [s.get(x) for x in xs]) for nom, s in series],
                 "tiempo (s)", "finalizadas (acumulado)", numerico=True, marcadores=False)
        md += ["![Finalizadas en el tiempo](graficas/g3_finalizadas_en_el_tiempo.svg)", ""]
    return md


def seccion_interbloqueo(filas, md):
    d = agrupar(filas, "interbloqueo")
    estrategias = ["sin_orden", "orden", "timeout", "deteccion"]
    ns = sorted({n for _, n in d})
    md += ["## 2. Estrategias frente al interbloqueo", "",
           "Cargue (vehículo → andén) frente a inspección (andén → vehículo), 3 vehículos, "
           "2 andenes, 1 inspector.", "",
           "| Estrategia | Solicitudes | Ejecuciones | Interbloqueos sin resolver | Detectados | "
           "Recuperaciones | Reintentos por tiempo límite | Entregadas | Tiempo total (s) |",
           "|---|---|---|---|---|---|---|---|---|"]
    pct_sin, tiempos = [], []
    for e in estrategias:
        todas = []
        for n in ns:
            fs = d[(e, n)]
            todas += fs
            sin = sum(int(r["interbloqueo_sin_resolver"]) for r in fs)
            terminadas = [r for r in fs if r["interbloqueo_sin_resolver"] == "0"]
            md.append(f"| {e} | {n} | {len(fs)} | {sin}/{len(fs)} | {ms(col(fs, 'interbloqueos'))} "
                      f"| {ms(col(fs, 'recuperaciones'))} | {ms(col(fs, 'reintentos_timeout'))} | "
                      f"{ms(col(fs, 'entregadas'))} / {n} | "
                      f"{ms(col(terminadas, 'tiempo_total_s'), 2) if terminadas else '—'} |")
        pct_sin.append(100 * sum(int(r["interbloqueo_sin_resolver"]) for r in todas) / len(todas))
        n_max = max(ns)
        term = [r for r in d[(e, n_max)] if r["interbloqueo_sin_resolver"] == "0"]
        tiempos.append(media(col(term, "tiempo_total_s")) or 0.0)
    md.append("")
    total = sum(len(d[(estrategias[0], n)]) for n in ns)
    g.barras(DIR_G / "g4_interbloqueos_por_estrategia.svg",
             "Ejecuciones que terminaron en interbloqueo sin resolver",
             f"{total} ejecuciones por estrategia (24 y 48 solicitudes)", estrategias, pct_sin,
             "% de las ejecuciones", decimales=0, sufijo=" %")
    # sin_orden no se grafica: no termina (se interbloquea), y una barra en 0 sugeriría
    # que es la más rápida. La tabla lo muestra como "—".
    g.barras(DIR_G / "g5_tiempo_por_estrategia.svg",
             f"Tiempo total por estrategia ({max(ns)} solicitudes)",
             "Media de las ejecuciones · sin_orden no aparece: no termina, se interbloquea",
             estrategias[1:], tiempos[1:], "segundos", decimales=2, sufijo=" s")
    md += ["![Interbloqueos por estrategia](graficas/g4_interbloqueos_por_estrategia.svg)", "",
           "![Tiempo por estrategia](graficas/g5_tiempo_por_estrategia.svg)", ""]
    return md


def seccion_espera(filas, md):
    d = agrupar(filas, "espera")
    nombres = {"bloqueante": "bloqueante (semáforo)", "activa_5ms": "activa, reintento 5 ms",
               "activa_sin_pausa": "activa, sin pausa"}
    orden = [k for k in nombres if (k, 48) in d]
    md += ["## 3. Espera bloqueante frente a espera activa", "",
           "16 despachadores (4 × 4) compiten por 2 vehículos, 48 solicitudes, modo seguro.", "",
           "| Espera | Tiempo total (s) | CPU de los trabajadores (s) | CPU media (%) | "
           "Cambios de contexto voluntarios | Reintentos de sondeo |", "|---|---|---|---|---|---|"]
    for k in orden:
        fs = d[(k, 48)]
        md.append(f"| {nombres[k]} | {ms(col(fs, 'tiempo_total_s'), 2)} | "
                  f"{ms(col(fs, 'cpu_trabajadores_s'), 2)} | {ms(col(fs, 'cpu_trabajadores_pct'))} | "
                  f"{ms(col(fs, 'ctx_voluntarios'), 0)} | {ms(col(fs, 'reintentos_sondeo'), 0)} |")
    md.append("")
    g.barras(DIR_G / "g6_cpu_segun_espera.svg", "CPU consumida para el mismo trabajo",
             "16 despachadores y 2 vehículos · el tiempo total es el mismo en los tres casos",
             [nombres[k] for k in orden],
             [media(col(d[(k, 48)], "cpu_trabajadores_s")) for k in orden],
             "segundos de CPU de los trabajadores", decimales=2, sufijo=" s")
    md += ["![CPU según la espera](graficas/g6_cpu_segun_espera.svg)", ""]
    return md


def seccion_cpu_memoria(md):
    ruta = F6 / "e1_cpu_hilos_procesos.txt"
    if ruta.exists():
        filas = {}
        for linea in ruta.read_text().splitlines():
            p = linea.split()
            if len(p) > 4 and p[0].isdigit() and p[1].isdigit():
                filas[(int(p[0]), int(p[1]))] = float(p[3].rstrip("x"))
        u = [1, 2, 4, 8]
        g.lineas(DIR_G / "g7_aceleracion_cpu.svg",
                 "Aceleración de una tarea de CPU: hilos frente a procesos",
                 "24 rutas de 9 puntos · 2 núcleos físicos con Hyper-Threading (4 CPU lógicas) · "
                 "fuente: Fase 6, E1", u,
                 [("hilos en 1 proceso", [filas.get((1, k)) for k in u]),
                  ("procesos de 1 hilo", [filas.get((k, 1)) for k in u])],
                 "hilos o procesos", "aceleración (veces)", x_etiquetas=[str(k) for k in u],
                 decimales=2)
        md += ["## 4. CPU: hilos frente a procesos (datos de la Fase 6, E1)", "",
               "| Unidades | Aceleración con hilos (1 proceso) | Aceleración con procesos (1 hilo) |",
               "|---|---|---|"]
        md += [f"| {k} | {filas.get((1, k), '—')}x | {filas.get((k, 1), '—')}x |" for k in u]
        md += ["", "![Aceleración](graficas/g7_aceleracion_cpu.svg)", ""]

    series, xs = [], set()
    for h, nombre in ((0, "historial sin límite"), (20, "historial acotado a 20")):
        ruta = F6 / f"e4_historial_{h}.recursos.csv"
        if ruta.exists():
            with open(ruta, newline="") as f:
                pts = {float(r["t_s"]): int(r["rss_kb"]) / 1024 for r in csv.DictReader(f)
                       if r["proceso"] == "trabajador-1"}
            series.append((nombre, pts))
            xs |= set(pts)
    if series:
        xs = sorted(xs)
        g.lineas(DIR_G / "g8_memoria_rss.svg", "Memoria residente (RSS) de trabajador-1",
                 "Traza GPS de 256 KB por entrega · muestreo de /proc cada 0.25 s · fuente: "
                 "Fase 6, E4", xs, [(nom, [p.get(x) for x in xs]) for nom, p in series],
                 "tiempo (s)", "RSS (MB)", numerico=True, marcadores=True, decimales=1)
        md += ["## 5. Crecimiento de memoria (datos de la Fase 6, E4)", "",
               "| t (s) | " + " | ".join(n for n, _ in series) + " |",
               "|---|" + "---|" * len(series)]
        md += [f"| {x} | " + " | ".join(f"{p[x]:.1f}" if x in p else "—" for _, p in series) + " |"
               for x in xs]
        md += ["", "![Memoria](graficas/g8_memoria_rss.svg)", ""]
    return md


def main():
    DIR_G.mkdir(parents=True, exist_ok=True)
    filas = leer_resultados()
    md = ["# Fase 8 — Resultados de la batería de experimentos", "",
          f"Generado por `experimentos/informe_fase8.py` a partir de `resultados.csv` "
          f"({len(filas)} ejecuciones). Cada gráfica tiene su tabla gemela.", ""]
    md = seccion_antes_despues(filas, md)
    md = seccion_interbloqueo(filas, md)
    md = seccion_espera(filas, md)
    md = seccion_cpu_memoria(md)
    (F8 / "resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(list(DIR_G.glob('*.svg')))} gráficas en {DIR_G.relative_to(RAIZ)} | "
          f"tablas en {(F8 / 'resumen.md').relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
