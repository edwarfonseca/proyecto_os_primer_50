#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 7 (registro y observación) y guarda las evidencias
# en evidencias/fase7/.
#
#   E1: registro en vivo del monitor (vista resumen) y ley de conservación de solicitudes.
#   E2: la misma ejecución vista desde el SO con scripts/monitor_so.sh.
#   E3: detección de falta de progreso: procesos detenidos (SIGSTOP/SIGCONT) e inanición (H3).
#   E4: contadores compartidos: Value(lock=True) no es atómico (hallazgo H6).
#   E5: archivos de registro que deja cada ejecución.
#
# Uso: scripts/evidencias_fase7.sh [SECCIONES...]   (≈ 3 min completo)

set -uo pipefail
cd "$(dirname "$0")/.."
SECCIONES="${*:-e1 e2 e3 e4 e5}"
DIR="${DIR:-evidencias/fase7}"
mkdir -p "$DIR" logs/fase7

e1() {
    echo "== E1: registro en vivo =="
    rm -f "$DIR"/e1_*
    L="$DIR/e1_ejecucion.log"
    python3 main.py -n 40 --vista resumen --log "$L" > "$DIR/e1_consola.txt"
    echo "exit code: $?" >> "$DIR/e1_consola.txt"
    cp "${L%.log}.estado.csv" "$DIR/e1_estado.csv"
    {
        echo "Ley de conservación en cada muestra: recibidas = en_cola + en_proceso + finalizadas"
        printf "\n%-6s %-10s %-8s %-11s %-12s %-10s %-10s %-12s %s\n" "t(s)" "RECIBIDAS" "EN COLA" \
            "EN PROCESO" "FINALIZADAS" "ASIGNADOS" "DISPONIB." "SUMA" "¿CUADRA?"
        awk -F, 'NR > 1 {s = $3 + $4 + $10;
            printf "%-6s %-10s %-8s %-11s %-12s %-10s %-10s %-12s %s\n", $1, $2, $3, $4, $10, $6, $7, s,
            (s == $2 ? "sí" : "no (en tránsito)")}' "$DIR/e1_estado.csv"
    } | tee "$DIR/e1_conservacion.txt"
}

e2() {
    echo "== E2: vista del SO en paralelo con el monitor =="
    rm -f "$DIR"/e2_*
    L="$DIR/e2_ejecucion.log"
    setsid python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5 -p 8 --vista resumen --log "$L" \
        > /dev/null &
    PID=$!
    sleep 2
    scripts/monitor_so.sh 1 4 "$PID" > "$DIR/e2_monitor_so.txt"
    kill -INT -- "-$PID"
    wait "$PID"
    {
        echo "## scripts/monitor_so.sh (SO: procesos, hilos por estado, CPU, RSS)"
        cat "$DIR/e2_monitor_so.txt"
        echo; echo "## Líneas ESTADO del monitor en los mismos instantes (negocio)"
        grep "ESTADO" "$L" | sed -n '2,6p' | cut -c1-16,77-400
    } > "$DIR/e2_so_vs_monitor.txt"
    cat "$DIR/e2_so_vs_monitor.txt"
}

e3() {
    echo "== E3: detección de falta de progreso =="
    rm -f "$DIR"/e3*
    # (a) Procesos que no responden: SIGSTOP a un trabajador, luego a ambos, luego SIGCONT.
    L="$DIR/e3a_detenidos.log"
    setsid python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5 --alerta-sin-progreso 3 \
        --vista resumen --log "$L" > /dev/null &
    PID=$!
    sleep 3
    W1=$(pgrep -P "$PID" -x trabajador-1); W2=$(pgrep -P "$PID" -x trabajador-2)
    {
        echo "$(date +%T.%N | cut -c1-12) kill -STOP trabajador-1 ($W1)"; kill -STOP "$W1"; sleep 4
        echo "$(date +%T.%N | cut -c1-12) kill -STOP trabajador-2 ($W2)"; kill -STOP "$W2"; sleep 2
        echo "## ps con ambos detenidos"; ps -o pid,stat,wchan:18,comm -p "$W1,$W2"; sleep 4
        echo "$(date +%T.%N | cut -c1-12) kill -CONT a ambos"; kill -CONT "$W1" "$W2"; sleep 4
    } > "$DIR/e3a_acciones.txt"
    kill -INT -- "-$PID"
    wait "$PID"
    {
        cat "$DIR/e3a_acciones.txt"
        echo; echo "## Monitor"
        grep -E "ESTADO|SIN PROGRESO|INTERBLOQUEO" "$L" | cut -c1-16,77-400
        echo; grep -E "MONITOR:|INTERBLOQUEOS:" "$L" | cut -c1-16,77-400
    } > "$DIR/e3a_resumen.txt"
    grep -E "kill|SIN PROGRESO:" "$DIR/e3a_resumen.txt" | cut -c1-200

    # (b) Inanición del hallazgo H3 (cola mp + trabajador muerto): se reintenta hasta observarla.
    SIN="-v 100 --ventana 0 -a 100 -i 0 -p 0 --traza-kb 0"
    for i in $(seq 8); do
        L="logs/fase7/e3b_$i.log"; rm -f "$L"
        setsid python3 main.py -w 3 -t 2 -n 0 --tam-rafaga 1 --intervalo 1 --despacho 0.02-0.05 \
            --entrega 0.05-0.1 --cola mp --alerta-sin-progreso 3 --espera-fin 1.5 $SIN \
            --vista resumen --log "$L" > /dev/null 2>&1 &
        PID=$!
        sleep 2.2
        kill -KILL "$(pgrep -P "$PID" -x trabajador-2)"
        sleep 6
        kill -INT "$PID"; wait "$PID" 2>/dev/null
        if grep -q "SIN PROGRESO:" "$L"; then
            {
                echo "Intento $i: inanición observada (en intentos anteriores el lock no lo tenía trabajador-2)"
                grep -E "CAÍDO|ESTADO|SIN PROGRESO|INTERBLOQUEOS:|MONITOR:|solicitudes:" "$L" | cut -c1-16,77-400
            } > "$DIR/e3b_inanicion_h3.txt"
            break
        fi
    done
    grep -E "Intento|SIN PROGRESO:|INTERBLOQUEOS" "$DIR/e3b_inanicion_h3.txt" | cut -c1-200
}

e4() {
    echo "== E4: contadores compartidos (H6) =="
    rm -f "$DIR"/e4_*
    python3 experimentos/h6_contador_compartido.py | tee "$DIR/e4_contadores_h6.txt"
}

e5() {
    echo "== E5: archivos de registro de una ejecución =="
    rm -f "$DIR"/e5_*
    L="$DIR/e1_ejecucion.log"
    {
        for f in "$L" "${L%.log}.estado.csv" "${L%.log}.recursos.csv"; do
            echo "## $f ($(wc -l < "$f") líneas)"
            head -4 "$f" | cut -c1-200
            echo
        done
    } | tee "$DIR/e5_archivos.txt"
}

for e in $SECCIONES; do
    "$e"
done
echo "Evidencias en $DIR/"
