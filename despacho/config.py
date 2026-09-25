"""Parámetros de ejecución leídos desde la línea de comandos."""

import argparse
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    trabajadores: int
    hilos: int               # hilos despachadores por trabajador
    generadores: int         # hilos productores en el proceso principal
    solicitudes: int         # total a generar; 0 = continuo hasta Ctrl+C
    tam_rafaga: int          # solicitudes por generador en cada ráfaga; 0 = todas de una vez
    intervalo: float         # segundos entre ráfagas
    capacidad_cola: int
    vehiculos: int
    ventana: float           # segundos entre ver un vehículo libre y marcarlo asignado
    modo: str                # seguro | inseguro
    espera: str              # bloqueante | activa
    seccion: str             # fina | gruesa (sólo modo seguro)
    reintento: float         # segundos entre búsquedas con espera activa
    andenes: int
    inspectores: int         # hilos del proceso taller
    intervalo_inspeccion: tuple[float, float]
    alistar_anden: float     # segundos que la inspección retiene el andén antes de pedir el vehículo
    interbloqueo: str        # sin_orden | orden | timeout | deteccion
    timeout_recurso: float   # tiempo límite del segundo recurso (estrategia timeout)
    puntos: int              # puntos de entrega por solicitud (CPU: P! rutas)
    traza_kb: int            # KB de traza GPS que se guardan por entrega
    historial: int           # trazas conservadas por proceso; 0 = sin límite
    muestreo: float          # segundos entre muestras de CPU/memoria en /proc
    tipo_cola: str           # semaforos (ColaAcotada) | mp (multiprocessing.Queue)
    despacho: tuple[float, float]   # rango (s) del tiempo de preparación
    entrega: tuple[float, float]    # rango (s) del tiempo de ruta
    semilla: int
    duracion: float          # tiempo máximo en segundos; 0 = sin límite
    metodo_inicio: str       # fork | forkserver | spawn
    espera_fin: float        # tiempo de gracia antes de forzar la terminación
    ruta_log: Path


def _rango(texto: str) -> tuple[float, float]:
    """'0.1-0.3' -> (0.1, 0.3); '0.2' -> (0.2, 0.2)."""
    partes = texto.split("-")
    try:
        a, b = (float(partes[0]), float(partes[-1]))
    except ValueError:
        raise argparse.ArgumentTypeError(f"rango inválido: {texto!r} (use p. ej. 0.1-0.3)")
    if len(partes) > 2 or a < 0 or b < a:
        raise argparse.ArgumentTypeError(f"rango inválido: {texto!r} (use p. ej. 0.1-0.3)")
    return a, b


def leer_argumentos(argv=None) -> Config:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Centro de despacho: procesos trabajadores con hilos que atienden "
                    "solicitudes de transporte desde una cola productor-consumidor.",
    )
    g = p.add_argument_group("procesos e hilos")
    g.add_argument("-w", "--trabajadores", type=int, default=2,
                   help="procesos trabajadores (defecto: 2)")
    g.add_argument("-t", "--hilos", type=int, default=3,
                   help="hilos despachadores por trabajador (defecto: 3)")
    g.add_argument("-g", "--generadores", type=int, default=2,
                   help="hilos productores de solicitudes (defecto: 2)")
    g.add_argument("--metodo-inicio", choices=["fork", "forkserver", "spawn"], default="fork",
                   help="método de creación de procesos (defecto: fork, conserva PPID = principal)")

    c = p.add_argument_group("carga")
    c.add_argument("-n", "--solicitudes", type=int, default=20,
                   help="total de solicitudes; 0 = generación continua hasta Ctrl+C (defecto: 20)")
    c.add_argument("--tam-rafaga", type=int, default=0,
                   help="solicitudes por generador en cada ráfaga simultánea; "
                        "0 = todas en una ráfaga (defecto: 0)")
    c.add_argument("--intervalo", type=float, default=1.0,
                   help="segundos entre ráfagas (defecto: 1)")
    c.add_argument("-k", "--capacidad-cola", type=int, default=10,
                   help="capacidad máxima de la cola de solicitudes (defecto: 10)")
    c.add_argument("--cola", choices=["semaforos", "mp"], default="semaforos", dest="tipo_cola",
                   help="implementación de la cola: semaforos = búfer acotado propio; "
                        "mp = multiprocessing.Queue (reproduce el hallazgo H3) (defecto: semaforos)")
    c.add_argument("--despacho", type=_rango, default=(0.1, 0.3), metavar="MIN-MAX",
                   help="tiempo de preparación en segundos (defecto: 0.1-0.3)")
    c.add_argument("--entrega", type=_rango, default=(0.2, 0.6), metavar="MIN-MAX",
                   help="tiempo de ruta hasta la entrega en segundos (defecto: 0.2-0.6)")
    c.add_argument("-s", "--semilla", type=int, default=42,
                   help="semilla aleatoria: misma semilla = misma carga (defecto: 42)")

    f = p.add_argument_group("flota")
    f.add_argument("-v", "--vehiculos", type=int, default=3,
                   help="vehículos de la flota compartida (defecto: 3)")
    f.add_argument("--ventana", type=float, default=0.01,
                   help="segundos de validación entre ver un vehículo libre y marcarlo "
                        "asignado; ensancha la ventana de carrera (defecto: 0.01)")
    f.add_argument("--modo", choices=["seguro", "inseguro"], default="seguro",
                   help="seguro = búsqueda y marcado bajo exclusión mutua; inseguro = sin "
                        "protección, reproduce la condición de carrera (defecto: seguro)")
    f.add_argument("--espera", choices=["bloqueante", "activa"], default="bloqueante",
                   help="sin vehículos libres: bloqueante = semáforo contador; activa = "
                        "reintentar cada --reintento s (defecto: bloqueante)")
    f.add_argument("--seccion", choices=["fina", "gruesa"], default="fina",
                   help="modo seguro: fina = validar fuera del mutex con el vehículo ya "
                        "reservado; gruesa = validar dentro del mutex (defecto: fina)")
    f.add_argument("--reintento", type=float, default=0.005,
                   help="segundos entre búsquedas con --espera activa; 0 = sin pausa "
                        "(defecto: 0.005)")

    r = p.add_argument_group("andenes, taller e interbloqueo")
    r.add_argument("-a", "--andenes", type=int, default=2,
                   help="andenes de cargue (defecto: 2)")
    r.add_argument("-i", "--inspectores", type=int, default=1,
                   help="hilos inspectores del proceso taller; 0 = sin taller (defecto: 1)")
    r.add_argument("--intervalo-inspeccion", type=_rango, default=(0.1, 0.4), metavar="MIN-MAX",
                   help="segundos entre inspecciones de cada inspector (defecto: 0.1-0.4)")
    r.add_argument("--alistar-anden", type=float, default=0.05,
                   help="segundos que la inspección retiene el andén antes de pedir el "
                        "vehículo (defecto: 0.05)")
    r.add_argument("--interbloqueo", choices=["sin_orden", "orden", "timeout", "deteccion"],
                   default="orden",
                   help="sin_orden = cada operación en su orden natural (puede interbloquearse); "
                        "orden = orden global de recursos; timeout = tiempo límite y reintento; "
                        "deteccion = detectar el ciclo y expropiar a una víctima (defecto: orden)")
    r.add_argument("--timeout-recurso", type=float, default=0.1,
                   help="tiempo límite para el segundo recurso con --interbloqueo timeout "
                        "(defecto: 0.1)")

    m = p.add_argument_group("CPU y memoria")
    m.add_argument("-p", "--puntos", type=int, default=7,
                   help="puntos de entrega por solicitud; la ruta óptima evalúa P! recorridos "
                        "(7 ≈ 3 ms, 8 ≈ 25 ms, 9 ≈ 220 ms de CPU); 0 = sin planificación (defecto: 7)")
    m.add_argument("--traza-kb", type=int, default=64,
                   help="KB de traza GPS guardados por entrega; 0 = sin historial (defecto: 64)")
    m.add_argument("--historial", type=int, default=50,
                   help="trazas conservadas por proceso trabajador; 0 = sin límite, la memoria "
                        "crece con cada entrega (defecto: 50)")
    m.add_argument("--muestreo", type=float, default=0.5,
                   help="segundos entre muestras de CPU y memoria leídas de /proc (defecto: 0.5)")

    e = p.add_argument_group("ejecución")
    e.add_argument("-d", "--duracion", type=float, default=0.0,
                   help="tiempo máximo en segundos; 0 = sin límite (defecto: 0)")
    e.add_argument("--espera-fin", type=float, default=3.0,
                   help="segundos de gracia antes de enviar SIGTERM a un trabajador (defecto: 3)")
    e.add_argument("--log", type=Path, default=None,
                   help="archivo de registro (defecto: logs/despacho_<fecha>.log)")
    a = p.parse_args(argv)

    for nombre in ("trabajadores", "hilos", "generadores", "capacidad_cola", "vehiculos",
                   "andenes"):
        if getattr(a, nombre) < 1:
            p.error(f"--{nombre.replace('_', '-')} debe ser >= 1")
    if a.puntos > 10:
        p.error("--puntos > 10 no es razonable (10! = 3.6 millones de rutas por solicitud)")
    if min(a.solicitudes, a.tam_rafaga, a.ventana, a.reintento, a.inspectores,
           a.alistar_anden, a.puntos, a.traza_kb, a.historial) < 0 or a.timeout_recurso <= 0 \
            or a.muestreo <= 0:
        p.error("valores negativos no permitidos (--timeout-recurso y --muestreo deben ser > 0)")
    ruta_log = a.log or Path("logs") / f"despacho_{time.strftime('%Y%m%d_%H%M%S')}.log"

    return Config(
        trabajadores=a.trabajadores, hilos=a.hilos, generadores=a.generadores,
        solicitudes=a.solicitudes, tam_rafaga=a.tam_rafaga, intervalo=a.intervalo,
        capacidad_cola=a.capacidad_cola, tipo_cola=a.tipo_cola,
        vehiculos=a.vehiculos, ventana=a.ventana, modo=a.modo, espera=a.espera,
        seccion=a.seccion, reintento=a.reintento, andenes=a.andenes,
        inspectores=a.inspectores, intervalo_inspeccion=a.intervalo_inspeccion,
        alistar_anden=a.alistar_anden, interbloqueo=a.interbloqueo,
        timeout_recurso=a.timeout_recurso, puntos=a.puntos, traza_kb=a.traza_kb,
        historial=a.historial, muestreo=a.muestreo, despacho=a.despacho, entrega=a.entrega,
        semilla=a.semilla, duracion=a.duracion, metodo_inicio=a.metodo_inicio,
        espera_fin=a.espera_fin, ruta_log=ruta_log,
    )
