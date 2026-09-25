"""Parámetros de ejecución leídos desde la línea de comandos."""

import argparse
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    trabajadores: int
    duracion: float          # segundos; 0 = hasta recibir SIGINT/SIGTERM
    metodo_inicio: str       # fork | forkserver | spawn
    latido: float            # intervalo del latido de cada trabajador
    espera_fin: float        # tiempo de gracia antes de forzar la terminación
    ruta_log: Path


def leer_argumentos(argv=None) -> Config:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Centro de despacho: proceso principal que administra procesos trabajadores.",
    )
    p.add_argument("-w", "--trabajadores", type=int, default=2,
                   help="número de procesos trabajadores (defecto: 2)")
    p.add_argument("-d", "--duracion", type=float, default=5.0,
                   help="segundos de ejecución; 0 = hasta Ctrl+C (defecto: 5)")
    p.add_argument("--metodo-inicio", choices=["fork", "forkserver", "spawn"], default="fork",
                   help="método de creación de procesos (defecto: fork, conserva PPID = principal)")
    p.add_argument("--latido", type=float, default=1.0,
                   help="segundos entre latidos de cada trabajador (defecto: 1)")
    p.add_argument("--espera-fin", type=float, default=3.0,
                   help="segundos de gracia antes de enviar SIGTERM a un trabajador (defecto: 3)")
    p.add_argument("--log", type=Path, default=None,
                   help="archivo de registro (defecto: logs/despacho_<fecha>.log)")
    a = p.parse_args(argv)

    if a.trabajadores < 1:
        p.error("--trabajadores debe ser >= 1")
    ruta_log = a.log or Path("logs") / f"despacho_{time.strftime('%Y%m%d_%H%M%S')}.log"

    return Config(
        trabajadores=a.trabajadores,
        duracion=a.duracion,
        metodo_inicio=a.metodo_inicio,
        latido=a.latido,
        espera_fin=a.espera_fin,
        ruta_log=ruta_log,
    )
