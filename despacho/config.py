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

    e = p.add_argument_group("ejecución")
    e.add_argument("-d", "--duracion", type=float, default=0.0,
                   help="tiempo máximo en segundos; 0 = sin límite (defecto: 0)")
    e.add_argument("--espera-fin", type=float, default=3.0,
                   help="segundos de gracia antes de enviar SIGTERM a un trabajador (defecto: 3)")
    e.add_argument("--log", type=Path, default=None,
                   help="archivo de registro (defecto: logs/despacho_<fecha>.log)")
    a = p.parse_args(argv)

    for nombre in ("trabajadores", "hilos", "generadores", "capacidad_cola", "vehiculos"):
        if getattr(a, nombre) < 1:
            p.error(f"--{nombre.replace('_', '-')} debe ser >= 1")
    if a.solicitudes < 0 or a.tam_rafaga < 0 or a.ventana < 0:
        p.error("--solicitudes, --tam-rafaga y --ventana no pueden ser negativos")
    ruta_log = a.log or Path("logs") / f"despacho_{time.strftime('%Y%m%d_%H%M%S')}.log"

    return Config(
        trabajadores=a.trabajadores, hilos=a.hilos, generadores=a.generadores,
        solicitudes=a.solicitudes, tam_rafaga=a.tam_rafaga, intervalo=a.intervalo,
        capacidad_cola=a.capacidad_cola, tipo_cola=a.tipo_cola,
        vehiculos=a.vehiculos, ventana=a.ventana, despacho=a.despacho, entrega=a.entrega,
        semilla=a.semilla, duracion=a.duracion, metodo_inicio=a.metodo_inicio,
        espera_fin=a.espera_fin, ruta_log=ruta_log,
    )
