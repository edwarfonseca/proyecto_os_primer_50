#!/usr/bin/env bash
# Fase 8: batería de experimentos y comparación antes/después.
#
#   1. experimentos/bateria.py      ejecuta el sistema con todas las configuraciones y
#                                   guarda las métricas en evidencias/fase8/resultados.csv
#   2. experimentos/informe_fase8.py genera las gráficas SVG y las tablas (resumen.md)
#
# Uso: scripts/evidencias_fase8.sh [REPETICIONES]   (defecto: 3; ≈ 25 min)
#      scripts/evidencias_fase8.sh --solo-informe  (regenera gráficas y tablas sin ejecutar)

set -euo pipefail
cd "$(dirname "$0")/.."
DIR=evidencias/fase8
mkdir -p "$DIR"

if [[ "${1:-}" != "--solo-informe" ]]; then
    rm -f "$DIR/resultados.csv"
    python3 experimentos/bateria.py "${1:-3}" | tee "$DIR/bateria_salida.txt"
fi
python3 experimentos/informe_fase8.py
