#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 2 y guarda las evidencias en evidencias/fase2/.
#
#   E1: llegada simultánea en ráfagas (Barrier) y productor-consumidor con cola acotada.
#   E2: observación de procesos e hilos con herramientas del SO + Ctrl+C con cola llena.
#   E3: escalamiento: misma carga (misma semilla) con distinto número de procesos e hilos.
#   E4: capacidad de la cola: bloqueos del productor frente a espera en cola.
#
# El hallazgo H3 tiene su propio experimento: experimentos/h3_trabajador_caido.sh
#
# Uso: scripts/evidencias_fase2.sh   (desde la raíz del proyecto)

set -uo pipefail
cd "$(dirname "$0")/.."
# La flota (Fase 3+) no existía en esta fase: se usan vehículos de sobra y sin ventana
# para que no sea un cuello de botella y los resultados sigan siendo comparables.
SIN_FLOTA="-v 100 --ventana 0 -a 100 -i 0 -p 0 --traza-kb 0"   # sin taller ni andenes limitados (Fase 5+)
DIR="${DIR:-evidencias/fase2}"
mkdir -p "$DIR"
rm -f "$DIR"/e[0-9]_*

# Extrae un valor numérico del bloque de ESTADÍSTICAS de un log.
valor() { sed -n '/ESTADÍSTICAS:/,$p' "$1" | grep -oE "$2=[0-9.]+" | head -1 | cut -d= -f2; }

echo "== E1: ráfagas simultáneas y cola acotada =="
python3 main.py $SIN_FLOTA -w 2 -t 3 -g 4 -n 24 --tam-rafaga 2 --intervalo 0.8 -k 5 \
    --log "$DIR/e1_ejecucion.log" > /dev/null
echo "exit code: $?" | tee -a "$DIR/e1_ejecucion.log"
{
    echo "## Llegadas por ráfaga: 4 generadores x 2 solicitudes, liberados por una Barrier"
    grep -E "RÁFAGA|RECIBIDA|PRODUCTOR" "$DIR/e1_ejecucion.log" | cut -c1-16,77-200
} > "$DIR/e1_rafagas.txt"

echo "== E2: observación con herramientas del SO =="
setsid python3 main.py $SIN_FLOTA -w 2 -t 3 -g 2 -n 0 --tam-rafaga 3 --intervalo 0.5 -k 5 \
    --entrega 0.5-1.5 --log "$DIR/e2_ejecucion.log" > /dev/null &
PID=$!
sleep 3
scripts/observar.sh "$PID" "$DIR/e2_observacion.txt" > /dev/null
{
    echo "## top -H -b -n 1: una fila por hilo"
    top -H -b -n 1 -w 200 -p "$(pgrep -d, -s "$PID")" | sed -n '7,40p'
    echo; echo "## /proc/<pid>/task: hilos del principal y de trabajador-1"
    for p in "$PID" "$(pgrep -P "$PID" -x trabajador-1)"; do
        echo "-- PID $p ($(cat /proc/$p/comm)): Threads=$(grep Threads /proc/$p/status | cut -f2)"
        for t in /proc/$p/task/*; do
            printf "   TID %-8s %-16s %s\n" "${t##*/}" "$(cat $t/comm)" "$(cut -d' ' -f3 $t/stat)"
        done
    done
} > "$DIR/e2_hilos.txt"
kill -INT -- "-$PID"                  # Ctrl+C al grupo
wait "$PID"; echo "exit code: $?" | tee -a "$DIR/e2_ejecucion.log"

echo "== E3: escalamiento con la misma carga =="
{
    echo "Carga fija: 36 solicitudes, 4 generadores, cola 36 (sin bloqueos), semilla 42,"
    echo "despacho 0.1-0.3 s, entrega 0.2-0.6 s."
    printf "\n%-12s %-6s %-6s %-12s %-14s %-14s %-12s %-10s\n" "PROCESOS" "HILOS" "TOTAL" \
        "TIEMPO(s)" "SOLICITUDES/s" "CONCURR.EFECT" "CONC.MÁX" "CPU(%)"
    for conf in "1 1" "1 2" "1 4" "1 8" "2 4" "4 2" "4 4"; do
        set -- $conf
        L="$DIR/e3_w$1_t$2.log"
        python3 main.py $SIN_FLOTA -w "$1" -t "$2" -g 4 -n 36 -k 36 --log "$L" > /dev/null
        printf "%-12s %-6s %-6s %-12s %-14s %-14s %-12s %-10s\n" "$1" "$2" "$(($1 * $2))" \
            "$(valor "$L" "tiempo total")" "$(valor "$L" "rendimiento")" \
            "$(grep -oE 'trabajo/tiempo\)=[0-9.]+' "$L" | cut -d= -f2)" \
            "$(valor "$L" "concurrencia máxima observada")" \
            "$(grep -oE 'CPU de los trabajadores=[0-9.]+' "$L" | cut -d= -f2)"
    done
} | tee "$DIR/e3_escalamiento.txt"

echo "== E4: capacidad de la cola =="
{
    echo "Carga fija: 30 solicitudes en una ráfaga, 3 generadores, 1 trabajador x 3 hilos, semilla 42."
    printf "\n%-10s %-12s %-18s %-20s %-20s %-10s\n" "CAPACIDAD" "BLOQUEOS" \
        "T.BLOQUEADOS(s)" "ESPERA PROM(ms)" "ESPERA MÁX(ms)" "TIEMPO(s)"
    for k in 1 3 10 30; do
        L="$DIR/e4_k$k.log"
        python3 main.py $SIN_FLOTA -w 1 -t 3 -g 3 -n 30 -k "$k" --log "$L" > /dev/null
        printf "%-10s %-12s %-18s %-20s %-20s %-10s\n" "$k" "$(valor "$L" "bloqueos por cola llena")" \
            "$(valor "$L" "tiempo bloqueados")" "$(valor "$L" "prom")" "$(valor "$L" "máx")" \
            "$(valor "$L" "tiempo total")"
    done
} | tee "$DIR/e4_capacidad.txt"

echo "Evidencias en $DIR/"
