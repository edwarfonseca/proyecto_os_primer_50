"""Extracción de las métricas del bloque ESTADÍSTICAS de un log.

La usan la batería de experimentos (experimentos/bateria.py) y el frontend (web/servidor.py).
"""

import re

# Métricas de la batería: nombre -> expresión regular sobre el bloque ESTADÍSTICAS.
# Sus nombres son las columnas de evidencias/fase8/resultados.csv: no se deben cambiar.
METRICAS = {
    "generadas": r"generadas=(\d+)",
    "entregadas": r"solicitudes: generadas=\d+ entregadas=(\d+)",
    "canceladas": r"canceladas=(\d+) no atendidas",
    "no_atendidas": r"no atendidas=(\d+)",
    "tiempo_total_s": r"tiempo total=([\d.]+)",
    "rendimiento": r"rendimiento=([\d.]+)",
    "espera_cola_ms": r"espera en cola \(ms\): mín=\d+ prom=(\d+)",
    "espera_vehiculo_ms": r"espera por vehículo \(ms\): prom=(\d+)",
    "reintentos_sondeo": r"reintentos de búsqueda \(espera activa\)=(\d+)",
    "dobles_sonda": r"sonda en vivo=(\d+)",
    "dobles_auditoria": r"vehículo ocupado=(\d+)",
    "inconsistencias": r"actualizaciones perdidas\)=(\d+)",
    "en_ruta_max": r"entregas con vehículo a la vez: máx=(\d+)",
    "cpu_trabajadores_s": r"trabajadores=([\d.]+) s \|",
    "cpu_trabajadores_pct": r"CPU de los trabajadores=([\d.]+)",
    "ctx_voluntarios": r"voluntarios=(\d+), involuntarios",
    "ctx_involuntarios": r"involuntarios=(\d+)",
    "interbloqueos": r"INTERBLOQUEOS: detectados=(\d+)",
    "recuperaciones": r"recuperaciones \(víctimas\)=(\d+)",
    "reintentos_timeout": r"reintentos por tiempo límite=(\d+)",
}

# Métricas adicionales que muestra el frontend.
METRICAS_EXTRA = {
    "vehiculos": r"FLOTA: (\d+) vehículos",
    "real_cpu_rutas": r"real/CPU=([\d.]+)",
    "cpu_rutas_s": r"CPU total en rutas=([\d.]+)",
    "pss_total_mb": r"PSS total \(suma de picos\)=([\d.]+)",
    "rss_total_mb": r"RSS total \(suma de picos\)=([\d.]+)",
    "alertas_sin_progreso": r"MONITOR: (\d+) alertas",
}


def extraer(texto: str, extra: bool = False) -> dict:
    """Métricas de un log completo; valor "" si la métrica no aparece."""
    bloque = texto[texto.find("ESTADÍSTICAS:"):] if "ESTADÍSTICAS:" in texto else ""
    patrones = {**METRICAS, **(METRICAS_EXTRA if extra else {})}
    fila = {}
    for nombre, patron in patrones.items():
        m = re.search(patron, bloque)
        fila[nombre] = m.group(1) if m else ""
    fila["interbloqueo_sin_resolver"] = int("INTERBLOQUEO sin recuperación" in texto)
    return fila
