"""Punto de entrada del sistema de despacho y logística.

Uso: python3 main.py --help
"""

import sys

from despacho.centro import CentroDespacho
from despacho.config import leer_argumentos

if __name__ == "__main__":
    sys.exit(CentroDespacho(leer_argumentos()).ejecutar())
