"""Registro de eventos con la identidad del proceso y del hilo en el SO.

Cada línea incluye PID, PPID y TID. El TID es el identificador nativo del hilo en el
kernel (el mismo LWP que muestran `ps -eLf` y `top -H`), lo que permite cruzar el log
con las herramientas del sistema operativo.
"""

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

NOMBRE = "despacho"
FORMATO = ("%(asctime)s | PID %(process)6d | PPID %(ppid)6d | TID %(tid)6d | "
           "%(processName)-15s | %(threadName)-16s | %(message)s")


class _FiltroSO(logging.Filter):
    """Agrega PPID y TID nativo; se ejecuta en el hilo que emite el evento."""

    def filter(self, record):
        record.ppid = os.getppid()
        record.tid = threading.get_native_id()
        return True


class _FiltroConsola(logging.Filter):
    """Vista 'resumen': en consola sólo pasan avisos y líneas marcadas como resumen."""

    completa = True

    def filter(self, record):
        return (_FiltroConsola.completa or record.levelno >= logging.WARNING
                or getattr(record, "resumen", False))


def consola_completa() -> None:
    """Vuelve a mostrar todo en consola (para el resumen final)."""
    _FiltroConsola.completa = True


class _Formato(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # Microsegundos: necesarios para ordenar eventos concurrentes muy cercanos.
        return datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")


def configurar(ruta_log: Path, vista: str = "completa") -> logging.Logger:
    """Configura el registro una sola vez por proceso.

    Con el método `fork` el hijo hereda los manejadores ya configurados; con
    `forkserver`/`spawn` el hijo arranca limpio y los crea aquí.
    """
    log = logging.getLogger(NOMBRE)
    if log.handlers:
        return log
    _FiltroConsola.completa = vista == "completa"

    ruta_log.parent.mkdir(parents=True, exist_ok=True)
    formato = _Formato(FORMATO)
    # El archivo se abre en modo 'a' (O_APPEND): cada escritura va al final aunque
    # varios procesos compartan el archivo, así las líneas no se sobrescriben.
    consola = logging.StreamHandler(sys.stdout)
    consola.addFilter(_FiltroConsola())
    archivo = logging.FileHandler(ruta_log, mode="a", encoding="utf-8")
    for manejador in (consola, archivo):
        manejador.setFormatter(formato)
        manejador.addFilter(_FiltroSO())
        log.addHandler(manejador)
    if vista == "resumen":
        # En la vista resumen la consola muestra sólo hora y mensaje; el archivo conserva
        # siempre la identidad completa (PID, PPID, TID, proceso, hilo).
        consola.setFormatter(_Formato("%(asctime)s | %(message)s"))
    log.setLevel(logging.INFO)
    log.propagate = False
    return log
