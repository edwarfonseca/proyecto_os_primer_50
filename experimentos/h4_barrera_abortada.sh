#!/usr/bin/env bash
# Hallazgo H4: carrera entre Barrier.wait() y Barrier.abort() en los generadores.
#
# Repite una carga de 4 generadores x 3 ráfagas y cuenta las ejecuciones en las que se
# generaron menos solicitudes de las pedidas (un generador perdió su última ráfaga).
#
# Uso: experimentos/h4_barrera_abortada.sh ETIQUETA [REPETICIONES]
#   ETIQUETA: nombre del archivo de resumen (p. ej. antes / despues)
#
# Para reproducir la versión con el problema (etiqueta anterior a la corrección):
#   git checkout fase2-h4-antes -- despacho/generador.py
#   experimentos/h4_barrera_abortada.sh antes
#   git checkout HEAD -- despacho/generador.py

set -uo pipefail
cd "$(dirname "$0")/.."
# La flota (Fase 3+) no existía en esta fase: se usan vehículos de sobra y sin ventana
# para que no sea un cuello de botella y los resultados sigan siendo comparables.
SIN_FLOTA="-v 100 --ventana 0 -a 100 -i 0 -p 0 --traza-kb 0"   # sin taller ni andenes limitados (Fase 5+)
ETIQUETA="${1:?indique una etiqueta, p. ej. antes o despues}"
N="${2:-30}"
DIR=evidencias/fase2/h4
mkdir -p "$DIR" logs/h4
SALIDA="$DIR/resumen_$ETIQUETA.txt"

fallos=0
{
    echo "Carga: -w 2 -t 3 -g 4 -n 24 --tam-rafaga 2 (3 ráfagas por generador), $N repeticiones"
    echo "Commit: $(git rev-parse --short HEAD)$(git diff --quiet -- despacho/ || echo ' + cambios sin commit')"
    echo
} > "$SALIDA"
for i in $(seq "$N"); do
    L="logs/h4/${ETIQUETA}_$i.log"
    rm -f "$L"
    python3 main.py $SIN_FLOTA -w 2 -t 3 -g 4 -n 24 --tam-rafaga 2 --intervalo 0.05 -k 5 \
        --despacho 0.005-0.01 --entrega 0.005-0.01 --log "$L" > /dev/null
    g=$(grep -oE "generadas=[0-9]+ entregadas" "$L" | grep -oE "[0-9]+")
    if [[ "$g" != 24 ]]; then
        fallos=$((fallos + 1))
        echo "run $i: generadas=$g | $(grep 'FIN generador' "$L" | grep -v 'generadas=6' \
            | grep -oE 'generador [0-9]+: generadas=[0-9]+' | paste -sd';' -)" >> "$SALIDA"
    fi
done
echo "ejecuciones con solicitudes sin generar: $fallos de $N" | tee -a "$SALIDA"
