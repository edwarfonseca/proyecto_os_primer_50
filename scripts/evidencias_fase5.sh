#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 5 (interbloqueo) y guarda las evidencias en
# evidencias/fase5/.
#
#   E1: interbloqueo real (sin_orden): grafo de espera, hilos bloqueados vistos desde el SO,
#       ausencia de progreso y volcado de pilas.
#   E2: reproducibilidad: frecuencia y tiempo hasta el interbloqueo.
#   E3: comparación de las cuatro estrategias con la misma carga.
#   E4: estrategia timeout: efecto del tiempo límite.
#   E5: estrategia orden en ejecución: esperas cortas por locks, pero sin ciclos.
#
# Uso: scripts/evidencias_fase5.sh [REPETICIONES] [SECCIONES...]   (≈ 12 min completo)
#   scripts/evidencias_fase5.sh 10 e1 e3   sólo E1 y E3

set -uo pipefail
cd "$(dirname "$0")/.."
REP="${1:-10}"
shift || true
SECCIONES="${*:-e1 e2 e3 e4 e5}"
DIR="${DIR:-evidencias/fase5}"
mkdir -p "$DIR" logs/fase5

# La carga de CPU y memoria (Fase 6) no existía en esta fase.
SIN_CARGA="-p 0 --traza-kb 0"
BASE="-w 2 -t 3 -g 4 -n 24 -v 3 -a 2 -i 1 -s 42 $SIN_CARGA"

est() { sed -n '/ESTADÍSTICAS:/,$p' "$1"; }
num() { est "$1" | grep -oE "$2=[0-9.]+" | head -1 | cut -d= -f2; }
media() { awk '{s+=$1} END {printf "%.2f", (NR ? s/NR : 0)}'; }
# Segundos desde el inicio del sistema hasta la primera detección de interbloqueo.
t_deteccion() {
    awk -F'|' 'NR == 1 {split($1, a, ":"); t0 = a[1]*3600 + a[2]*60 + a[3]}
               /INTERBLOQUEO DETECTADO/ {split($1, b, ":"); printf "%.2f", b[1]*3600 + b[2]*60 + b[3] - t0; exit}' "$1"
}

e1() {
    echo "== E1: interbloqueo real y su observación desde el SO =="
    rm -f "$DIR"/e1_*
    L="$DIR/e1_ejecucion.log"
    # --espera-fin 8 deja el sistema interbloqueado unos segundos para observarlo.
    setsid python3 main.py $BASE --interbloqueo sin_orden --espera-fin 8 --log "$L" \
        > /dev/null 2> "$DIR/e1_volcado_pilas.txt" &
    PID=$!
    for _ in $(seq 300); do grep -q "INTERBLOQUEO DETECTADO" "$L" 2>/dev/null && break; sleep 0.1; done
    sleep 1.5                                  # espera los volcados escalonados
    CICLO=$(grep -m1 "INTERBLOQUEO DETECTADO" "$L" | cut -d'|' -f7-)
    H1=$(echo "$CICLO" | grep -oE "(despachador|inspector)-[0-9-]+" | sed -n 1p)
    H2=$(echo "$CICLO" | grep -oE "(despachador|inspector)-[0-9-]+" | sed -n 2p)
    PIDS="$PID,$(pgrep -d, -P "$PID")"
    {
        echo "## Ciclo informado por el vigilante (grafo de espera):"
        echo "$CICLO"
        echo
        echo "## ps -L: estado y canal de espera de cada hilo (los del ciclo: $H1, $H2)"
        ps -L -o pid,lwp,stat,pcpu,wchan:22,comm -p "$PIDS"
        echo
        echo "## Hilos del ciclo en /proc: estado, CPU y cambios de contexto (dos lecturas a 2 s)"
        for n in "$H1" "$H2"; do
            for t in $(ps -L -o pid=,lwp=,comm= -p "$PIDS" | awk -v n="$n" '$3 == n {print $1"/"$2}'); do
                p=${t%/*}; l=${t#*/}
                f="/proc/$p/task/$l"
                a1=$(awk '/^voluntary_ctxt/ {print $2}' "$f/status"); c1=$(awk '{print $14+$15}' "$f/stat")
                sleep 2
                a2=$(awk '/^voluntary_ctxt/ {print $2}' "$f/status"); c2=$(awk '{print $14+$15}' "$f/stat")
                printf "   %-16s PID %-7s TID %-7s estado=%s wchan=%s | ctx voluntarios %s -> %s | ticks CPU %s -> %s\n" \
                    "$n" "$p" "$l" "$(awk '{print $3}' "$f/stat")" "$(cat "$f/wchan")" "$a1" "$a2" "$c1" "$c2"
            done
        done
        echo
        echo "## Progreso del sistema: resultados en el log durante 2 s"
        a=$(grep -c "ENTREGADA solicitud" "$L"); sleep 2; b=$(grep -c "ENTREGADA solicitud" "$L")
        echo "   entregas registradas: $a -> $b"
    } > "$DIR/e1_observacion.txt"
    wait "$PID"; echo "exit code: $?" >> "$L"
    {
        echo "## Eventos de los recursos del ciclo antes del interbloqueo"
        R=$(echo "$CICLO" | grep -oE "tiene [VA][0-9]+" | awk '{print $2}' | paste -sd'|' -)
        grep -E "INICIO centro|INSPECCIÓN pide|ASIGNADO|INTERBLOQUEO|DIAGNÓSTICO" "$L" \
            | grep -E "INICIO centro|$R|INTERBLOQUEO|DIAGNÓSTICO|$H1|$H2" | tail -12 | cut -c1-16,77-260
        echo; echo "## Cierre forzado y balance"
        grep -E "SIGTERM|SIGKILL|solicitudes:|RECURSOS|INTERBLOQUEOS|FIN centro|exit code" "$L" | cut -c1-16,77-260
    } > "$DIR/e1_cronologia.txt"
    cat "$DIR/e1_observacion.txt"
}

e2() {
    echo "== E2: reproducibilidad del interbloqueo =="
    rm -f "$DIR"/e2_*
    {
        echo "Carga: $BASE --interbloqueo sin_orden ($REP ejecuciones)"
        printf "\n%-5s %-14s %-24s %-12s %-12s %-6s\n" "RUN" "INTERBLOQUEO" "SEGUNDOS HASTA DETECTAR" \
            "ENTREGADAS" "CARGUES" "EXIT"
        for i in $(seq "$REP"); do
            L="logs/fase5/e2_$i.log"; rm -f "$L"
            python3 main.py $BASE --interbloqueo sin_orden --espera-fin 1 --log "$L" > /dev/null 2>&1; ex=$?
            d=$(num "$L" "detectados")
            printf "%-5s %-14s %-24s %-12s %-12s %-6s\n" "$i" "$([[ $d -gt 0 ]] && echo sí || echo no)" \
                "$(t_deteccion "$L")" "$(num "$L" "entregadas")/24" "$(num "$L" "cargues")" "$ex"
        done
    } | tee "$DIR/e2_reproducibilidad.txt"
    echo "Ejecuciones con interbloqueo: $(awk '$2 == "sí"' "$DIR/e2_reproducibilidad.txt" | wc -l) de $REP" \
        | tee -a "$DIR/e2_reproducibilidad.txt"
}

e3() {
    echo "== E3: comparación de estrategias =="
    rm -f "$DIR"/e3_*
    {
        echo "Carga: $BASE ($REP ejecuciones por estrategia)"
        printf "\n%-11s %-18s %-12s %-12s %-12s %-12s %-14s %-12s %-10s\n" "ESTRATEGIA" "SIN RESOLVER" \
            "ENTREGADAS" "TIEMPO(s)" "INSPECC." "DETECTADOS" "RECUPERACIONES" "REINTENTOS" "EXIT=0"
        for e in sin_orden orden timeout deteccion; do
            fallo=0; ok=0; ent=""; ti=""; ins=""; det=""; rec=""; rei=""
            for i in $(seq "$REP"); do
                L="logs/fase5/e3_${e}_$i.log"; rm -f "$L"
                python3 main.py $BASE --interbloqueo "$e" --espera-fin 1 --log "$L" > /dev/null 2>&1
                [[ $? -eq 0 ]] && ok=$((ok + 1))
                grep -q "INTERBLOQUEO sin recuperación" "$L" && fallo=$((fallo + 1))
                ent+="$(num "$L" "entregadas")\n"; ins+="$(num "$L" "inspecciones")\n"
                det+="$(num "$L" "detectados")\n"; rec+="$(num "$L" "víctimas\)")\n"
                rei+="$(num "$L" "tiempo límite")\n"
                grep -q "INTERBLOQUEO sin recuperación" "$L" || ti+="$(num "$L" "tiempo total")\n"
            done
            printf "%-11s %-18s %-12s %-12s %-12s %-12s %-14s %-12s %-10s\n" "$e" "$fallo/$REP" \
                "$(printf "$ent" | media)/24" "$(printf "$ti" | media)" "$(printf "$ins" | media)" \
                "$(printf "$det" | media)" "$(printf "$rec" | media)" "$(printf "$rei" | media)" "$ok/$REP"
        done
        echo
        echo "TIEMPO(s): promedio sólo de las ejecuciones que terminaron (sin interbloqueo sin resolver)."
    } | tee "$DIR/e3_estrategias.txt"
}

e4() {
    echo "== E4: estrategia timeout: efecto del tiempo límite =="
    rm -f "$DIR"/e4_*
    R4=$(( REP / 2 > 0 ? REP / 2 : 1 ))
    {
        echo "Carga: $BASE --interbloqueo timeout, --alistar-anden 0.2 (inspección más larga), $R4 ejecuciones"
        printf "\n%-16s %-14s %-12s %-12s %-10s\n" "TIMEOUT(s)" "REINTENTOS" "TIEMPO(s)" "INSPECC." "EXIT=0"
        for t in 0.01 0.1 0.5; do
            ok=0; rei=""; ti=""; ins=""
            for i in $(seq "$R4"); do
                L="logs/fase5/e4_${t}_$i.log"; rm -f "$L"
                python3 main.py $BASE --interbloqueo timeout --timeout-recurso "$t" --alistar-anden 0.2 \
                    --log "$L" > /dev/null 2>&1 && ok=$((ok + 1))
                rei+="$(num "$L" "tiempo límite")\n"; ti+="$(num "$L" "tiempo total")\n"
                ins+="$(num "$L" "inspecciones")\n"
            done
            printf "%-16s %-14s %-12s %-12s %-10s\n" "$t" "$(printf "$rei" | media)" \
                "$(printf "$ti" | media)" "$(printf "$ins" | media)" "$ok/$R4"
        done
    } | tee "$DIR/e4_timeout.txt"
}

e5() {
    echo "== E5: estrategia orden en ejecución =="
    rm -f "$DIR"/e5_*
    L="$DIR/e5_ejecucion.log"
    setsid python3 main.py $SIN_CARGA -w 2 -t 3 -g 2 -n 0 --tam-rafaga 3 --intervalo 0.5 -v 3 -a 1 -i 2 \
        --interbloqueo orden --log "$L" > /dev/null &
    PID=$!
    sleep 3
    {
        for k in 1 2 3; do
            echo "## Foto $k: hilos que esperan un lock (futex) o trabajan"
            ps -L -o pid,lwp,stat,wchan:22,comm -p "$PID,$(pgrep -d, -P "$PID")" \
                | awk 'NR == 1 || /despachador|inspector/'
            sleep 1
        done
    } > "$DIR/e5_observacion.txt"
    scripts/observar.sh "$PID" "$DIR/e5_observar.txt" > /dev/null
    kill -INT -- "-$PID"
    wait "$PID"
    grep -E "INTERBLOQUEO|RECURSOS|INTERBLOQUEOS|solicitudes:|FIN centro" "$L" | cut -c1-16,77-260 \
        >> "$DIR/e5_observacion.txt"
    tail -4 "$DIR/e5_observacion.txt"
}

for e in $SECCIONES; do
    "$e"
done
echo "Evidencias en $DIR/"
