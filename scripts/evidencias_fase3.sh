#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 3 (condición de carrera en la asignación de
# vehículos) y guarda las evidencias en evidencias/fase3/.
#
#   E1: demostración: dobles asignaciones, cronología de un vehículo, auditoría.
#   E2: reproducibilidad: 10 ejecuciones con la misma configuración y semilla.
#   E3: ancho de la ventana de carrera (0 a 10 ms) frente a la frecuencia del fallo.
#   E4: hilos frente a procesos: la carrera con y sin ventana artificial (efecto del GIL).
#   E5: la flota vista desde el SO: memoria compartida en /proc/<pid>/maps.
#
# Uso: scripts/evidencias_fase3.sh [REPETICIONES]   (defecto: 10; ≈ 8 min)

set -uo pipefail
cd "$(dirname "$0")/.."
REP="${1:-10}"
DIR="${DIR:-evidencias/fase3}"
mkdir -p "$DIR" logs/fase3
rm -f "$DIR"/e[0-9]_*

# Desde la Fase 4 el modo por defecto es el seguro: aquí se fuerza la versión con el problema.
INSEGURO="--modo inseguro --espera activa -a 100 -i 0"   # sin taller ni andenes limitados (Fase 5+)

sonda() { grep -oE "sonda en vivo=[0-9]+" "$1" | cut -d= -f2; }
auditoria() { grep -oE "vehículo ocupado=[0-9]+" "$1" | cut -d= -f2; }

echo "== E1: demostración de la condición de carrera =="
python3 main.py $INSEGURO -w 2 -t 3 -g 4 -n 24 -v 3 --log "$DIR/e1_ejecucion.log" > /dev/null
echo "exit code: $? (1 = el sistema detectó resultados incorrectos)" | tee -a "$DIR/e1_ejecucion.log"
{
    echo "## Detecciones en vivo (sonda)"
    grep "DOBLE ASIGNACIÓN" "$DIR/e1_ejecucion.log" | cut -c1-16,77-300
    echo; echo "## Bloque de estadísticas"
    sed -n '/ESTADÍSTICAS:/,$p' "$DIR/e1_ejecucion.log" | cut -c94-400
} > "$DIR/e1_dobles.txt"
# Cronología del vehículo con más conflictos: todos sus eventos en orden de tiempo.
V=$(grep -oE "DOBLE ASIGNACIÓN: vehículo V[0-9]+" "$DIR/e1_ejecucion.log" | awk '{print $NF}' \
    | sort | uniq -c | sort -rn | awk 'NR==1 {print $2}')
if [[ -n "$V" ]]; then
    {
        echo "## Cronología de $V (ordenada por marca de tiempo)"
        echo "## Lectura: entre ASIGNADO/DOBLE y ENTREGADA la solicitud usa $V; si otra"
        echo "## solicitud entra antes de que la anterior termine, $V está en dos rutas a la vez."
        grep -E "(vehículo|en) $V( |$)|$V liberado" "$DIR/e1_ejecucion.log" | sort \
            | cut -c1-16,77-230
    } > "$DIR/e1_cronologia_$V.txt"
fi

echo "== E2: reproducibilidad ($REP ejecuciones, semilla 42) =="
{
    echo "Configuración: -w 2 -t 3 -g 4 -n 24 -v 3 --ventana 0.01 --semilla 42"
    printf "\n%-6s %-12s %-14s %-12s\n" "RUN" "SONDA" "AUDITORÍA" "EXIT"
    con=0
    for i in $(seq "$REP"); do
        L="logs/fase3/e2_$i.log"; rm -f "$L"
        python3 main.py $INSEGURO -w 2 -t 3 -g 4 -n 24 -v 3 --log "$L" > /dev/null; ex=$?
        s=$(sonda "$L"); [[ "$s" -gt 0 ]] && con=$((con + 1))
        printf "%-6s %-12s %-14s %-12s\n" "$i" "$s" "$(auditoria "$L")" "$ex"
    done
    echo; echo "Ejecuciones con doble asignación: $con de $REP"
} | tee "$DIR/e2_reproducibilidad.txt"

echo "== E3: ancho de la ventana de carrera =="
{
    echo "Configuración: -w 2 -t 3 -g 4 -n 24 -v 3, $REP ejecuciones por ventana"
    printf "\n%-12s %-22s %-18s %-10s\n" "VENTANA(s)" "EJECUCIONES CON FALLO" "DOBLES PROMEDIO" "MÁXIMO"
    for vent in 0 0.0005 0.001 0.005 0.01; do
        con=0; tot=0; max=0
        for i in $(seq "$REP"); do
            L="logs/fase3/e3_${vent}_$i.log"; rm -f "$L"
            python3 main.py $INSEGURO -w 2 -t 3 -g 4 -n 24 -v 3 --ventana "$vent" --log "$L" > /dev/null
            s=$(sonda "$L"); tot=$((tot + s)); [[ "$s" -gt 0 ]] && con=$((con + 1))
            [[ "$s" -gt "$max" ]] && max=$s
        done
        printf "%-12s %-22s %-18s %-10s\n" "$vent" "$con/$REP" \
            "$(awk -v t="$tot" -v n="$REP" 'BEGIN{printf "%.1f", t/n}')" "$max"
    done
} | tee "$DIR/e3_ventana.txt"

echo "== E4: hilos frente a procesos =="
{
    echo "Carga: 48 solicitudes en ráfagas (6 generadores x 2), 3 vehículos, $REP ejecuciones"
    printf "\n%-10s %-7s %-12s %-22s %-18s\n" "PROCESOS" "HILOS" "VENTANA(s)" "EJECUCIONES CON FALLO" "DOBLES PROMEDIO"
    for vent in 0 0.001; do
        for conf in "1 6" "6 1" "2 3"; do
            set -- $conf; con=0; tot=0
            for i in $(seq "$REP"); do
                L="logs/fase3/e4_$1_$2_${vent}_$i.log"; rm -f "$L"
                python3 main.py $INSEGURO -w "$1" -t "$2" -g 6 -n 48 --tam-rafaga 2 --intervalo 0.3 -v 3 \
                    --ventana "$vent" --log "$L" > /dev/null
                s=$(sonda "$L"); tot=$((tot + s)); [[ "$s" -gt 0 ]] && con=$((con + 1))
            done
            printf "%-10s %-7s %-12s %-22s %-18s\n" "$1" "$2" "$vent" "$con/$REP" \
                "$(awk -v t="$tot" -v n="$REP" 'BEGIN{printf "%.1f", t/n}')"
        done
    done
} | tee "$DIR/e4_hilos_procesos.txt"

echo "== E5: memoria compartida vista desde el SO =="
setsid python3 main.py $INSEGURO -n 0 --tam-rafaga 2 --intervalo 0.5 --log "$DIR/e5_ejecucion.log" > /dev/null &
PID=$!
sleep 2
scripts/observar.sh "$PID" "$DIR/e5_observacion.txt" > /dev/null
kill -INT -- "-$PID"
wait "$PID"

echo "Evidencias en $DIR/"
