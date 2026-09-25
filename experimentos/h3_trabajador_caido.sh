#!/usr/bin/env bash
# Hallazgo H3: muerte de un trabajador mientras sus hilos esperan en la cola compartida.
#
# Para cada tipo de cola (mp = multiprocessing.Queue, semaforos = ColaAcotada propia) se
# ejecuta el sistema REPETICIONES veces en generación continua, se mata trabajador-2 con
# SIGKILL con el sistema ocioso y se cuenta cuántas solicitudes se despachan después.
# Si no se despacha ninguna, los consumidores sobrevivientes quedaron sin poder leer.
#
# Uso: experimentos/h3_trabajador_caido.sh [REPETICIONES]   (defecto: 8)

set -uo pipefail
cd "$(dirname "$0")/.."
REPETICIONES="${1:-8}"
DIR=evidencias/fase2/h3
mkdir -p "$DIR"
rm -f "$DIR"/*
RESUMEN="$DIR/resumen.txt"

printf "%-10s %-4s %-24s %-60s\n" "COLA" "RUN" "DESPACHOS TRAS SIGKILL" "BALANCE" | tee "$RESUMEN"
for tipo in mp semaforos; do
    for i in $(seq "$REPETICIONES"); do
        L="$DIR/${tipo}_$i.log"
        setsid python3 main.py -w 3 -t 2 -n 0 --tam-rafaga 1 --intervalo 1.5 \
            --despacho 0.02-0.05 --entrega 0.05-0.1 --espera-fin 1.5 --cola "$tipo" \
            --log "$L" > /dev/null 2> "$L.stderr" &
        P=$!
        sleep 2.2                                   # sistema ocioso entre ráfagas
        kill -KILL "$(pgrep -P "$P" -x trabajador-2)"
        sleep 4                                     # dos ráfagas más

        T=$(grep -m1 CAÍDO "$L" | cut -c1-15)
        DESPUES=$(awk -v t="$T" '$1 > t && /DESPACHO/' "$L" | wc -l)
        if [[ "$DESPUES" -eq 0 && ! -f "$DIR/inanicion_$tipo.txt" ]]; then
            # Primera inanición observada: se documenta el estado de los hilos.
            {
                echo "## ps -L (cola=$tipo, run $i): estado y canal de espera de cada hilo"
                ps -L -o pid,lwp,stat,pcpu,wchan:22,comm -p "$P,$(pgrep -d, -P "$P")"
                echo; echo "## kill -USR1 a trabajador-1: pila de sus hilos (faulthandler)"
            } > "$DIR/inanicion_$tipo.txt"
            W1=$(pgrep -P "$P" -x trabajador-1)
            kill -USR1 "$W1"; sleep 0.3
            cat "$L.stderr" >> "$DIR/inanicion_$tipo.txt"
        fi

        kill -INT "$P"
        for _ in $(seq 100); do kill -0 "$P" 2>/dev/null || break; sleep 0.1; done
        kill -0 "$P" 2>/dev/null && { echo "principal colgado: se elimina"; kill -KILL -- "-$P"; }
        wait "$P" 2>/dev/null
        BAL=$(grep -oE 'generadas=[0-9]+ entregadas=[0-9]+ canceladas=[0-9]+ no atendidas=[0-9]+' "$L")
        printf "%-10s %-4s %-24s %-60s\n" "$tipo" "$i" "$DESPUES" "$BAL" | tee -a "$RESUMEN"
    done
done

echo | tee -a "$RESUMEN"
for tipo in mp semaforos; do
    n=$(awk -v t="$tipo" '$1 == t && $3 == 0' "$RESUMEN" | wc -l)
    echo "cola=$tipo: inanición (0 despachos tras el SIGKILL) en $n de $REPETICIONES ejecuciones" \
        | tee -a "$RESUMEN"
done
