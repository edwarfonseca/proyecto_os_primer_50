#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 4 (corrección por sincronización) y guarda las
# evidencias en evidencias/fase4/.
#
#   E1: antes/después con la MISMA carga y semilla (inseguro+activa vs seguro+bloqueante).
#   E2: la versión corregida por dentro: cronología de un vehículo y los hilos en el SO.
#   E3: qué corrige cada mecanismo: las 4 combinaciones de modo y espera.
#   E4: costo de la espera activa en CPU bajo alta demanda (16 hilos, 2 vehículos).
#   E5: sección crítica fina frente a gruesa.
#   E6: la corrección vale para hilos, procesos y ambos, con y sin ventana.
#
# Uso: scripts/evidencias_fase4.sh [REPETICIONES] [SECCIONES...]   (≈ 15 min completo)
#   scripts/evidencias_fase4.sh            todas las secciones, 10 repeticiones
#   scripts/evidencias_fase4.sh 10 e2 e4   sólo E2 y E4

set -uo pipefail
cd "$(dirname "$0")/.."
REP="${1:-10}"
shift || true
SECCIONES="${*:-e1 e2 e3 e4 e5 e6}"
DIR="${DIR:-evidencias/fase4}"
mkdir -p "$DIR" logs/fase4

ANTES="--modo inseguro --espera activa"
DESPUES="--modo seguro --espera bloqueante"
BASE="-w 2 -t 3 -g 4 -n 24 -v 3 --ventana 0.01 -s 42"

# Extrae métricas del bloque de ESTADÍSTICAS de un log.
est() { sed -n '/ESTADÍSTICAS:/,$p' "$1"; }
num() { est "$1" | grep -oE "$2=[0-9.]+" | head -1 | cut -d= -f2; }
sonda() { num "$1" "sonda en vivo"; }
incons() { num "$1" "actualizaciones perdidas\)"; }
enruta() { est "$1" | grep -oE "entregas con vehículo a la vez: máx=[0-9]+" | grep -oE "[0-9]+$"; }
cpu() { num "$1" "CPU de los trabajadores"; }
vcsw() { num "$1" "voluntarios"; }
# Cambios de contexto voluntarios de TODOS los hilos: /proc/<pid>/status sólo informa los
# del hilo líder; cada hilo tiene los suyos en /proc/<pid>/task/<tid>/status.
ctx_proceso() { cat /proc/"$1"/task/*/status 2>/dev/null | awk '/^voluntary_ctxt/ {s+=$2} END {print s}'; }
media() { awk '{s+=$1} END {printf "%.2f", (NR ? s/NR : 0)}'; }
espveh() { est "$1" | grep "espera por vehículo" | grep -oE "prom=[0-9.]+" | cut -d= -f2; }

e1() {
    rm -f "$DIR"/e1_*
    echo "== E1: antes / después con la misma carga =="
    {
        echo "Carga: $BASE ($REP ejecuciones por versión)"
        printf "\n%-9s %-4s %-7s %-8s %-9s %-10s %-12s %-10s %-8s %-10s %-5s\n" "VERSIÓN" "RUN" \
            "DOBLES" "INCONS." "EN RUTA" "TIEMPO(s)" "SOLICITUD/s" "ESP.VEH" "CPU(%)" "CTX.VOL" "EXIT"
        for version in antes despues; do
            [[ $version == antes ]] && modo=$ANTES || modo=$DESPUES
            for i in $(seq "$REP"); do
                L="logs/fase4/e1_${version}_$i.log"; rm -f "$L"
                python3 main.py $BASE $modo --log "$L" > /dev/null; ex=$?
                printf "%-9s %-4s %-7s %-8s %-9s %-10s %-12s %-10s %-8s %-10s %-5s\n" "$version" "$i" \
                    "$(sonda "$L")" "$(incons "$L")" "$(enruta "$L")/3" "$(num "$L" "tiempo total")" \
                    "$(num "$L" "rendimiento")" "$(espveh "$L")" "$(cpu "$L")" "$(vcsw "$L")" "$ex"
            done
        done
    } | tee "$DIR/e1_antes_despues.txt"
    {
        echo; echo "PROMEDIOS"
        for version in antes despues; do
            f="$DIR/e1_antes_despues.txt"
            col() { awk -v v="$version" -v c="$1" '$1 == v {print $c}' "$f" | sed 's|/3||' | media; }
            fallos=$(awk -v v="$version" '$1 == v && $3 > 0' "$f" | wc -l)
            echo "$version: ejecuciones con dobles=$fallos/$REP | dobles=$(col 3) | inconsistencias=$(col 4)" \
                 "| en ruta máx=$(col 5) | tiempo=$(col 6) s | rendimiento=$(col 7)/s" \
                 "| espera por vehículo=$(col 8) ms | CPU=$(col 9) % | ctx. voluntarios=$(col 10)"
        done
    } | tee -a "$DIR/e1_antes_despues.txt"
    cp "logs/fase4/e1_antes_1.log" "$DIR/e1_ejecucion_antes.log"
    cp "logs/fase4/e1_despues_1.log" "$DIR/e1_ejecucion_despues.log"
}

e2() {
    rm -f "$DIR"/e2_*
    echo "== E2: la versión corregida por dentro =="
    L="$DIR/e1_ejecucion_despues.log"
    V=$(grep -oE "ASIGNADO vehículo V[0-9]+" "$L" | awk '{print $NF}' | sort | uniq -c | sort -rn \
        | awk 'NR==1 {print $2}')
    {
        echo "## Cronología de $V en la versión corregida (una solicitud a la vez)"
        grep -E "(vehículo|en) $V( |$)|$V liberado" "$L" | sort | cut -c1-16,77-230
        echo; echo "## Esperas por vehículo (bloqueo en el semáforo)"
        grep "SIN VEHÍCULOS" "$L" | cut -c1-16,77-230 | head -8
    } > "$DIR/e2_cronologia_$V.txt"
    # Observación en vivo: 12 despachadores y 2 vehículos, con cada tipo de espera.
    for espera in bloqueante activa; do
        setsid python3 main.py -w 2 -t 6 -g 2 -n 0 --tam-rafaga 6 --intervalo 0.5 -v 2 -k 20 \
            --entrega 1-2 --espera "$espera" --log "logs/fase4/e2_$espera.log" > /dev/null &
        PID=$!
        sleep 3
        W1=$(pgrep -P "$PID" -x trabajador-1)
        {
            echo "## --espera $espera: hilos de trabajador-1 (ps -L)"
            ps -L -o lwp,stat,pcpu,wchan:22,comm -p "$W1"
            c1=$(ctx_proceso "$W1")
            t1=$(awk '{print $14+$15}' /proc/$W1/stat)
            sleep 2
            c2=$(ctx_proceso "$W1")
            t2=$(awk '{print $14+$15}' /proc/$W1/stat)
            echo
            echo "En 2 s: cambios de contexto voluntarios de trabajador-1 (todos sus hilos) = $((c2 - c1))" \
                 "| CPU consumida = $(( (t2 - t1) * 10 )) ms (ticks de /proc/<pid>/stat)"
        } > "$DIR/e2_hilos_$espera.txt"
        kill -INT -- "-$PID"
        wait "$PID"
    done
}

e3() {
    rm -f "$DIR"/e3_*
    echo "== E3: qué corrige cada mecanismo =="
    {
        echo "Carga: $BASE ($REP ejecuciones por combinación)"
        printf "\n%-10s %-12s %-18s %-10s %-10s %-10s %-10s %-10s\n" "MODO" "ESPERA" \
            "EJEC. CON FALLO" "DOBLES" "INCONS." "EN RUTA" "REINTENT." "TIEMPO(s)"
        for modo in inseguro seguro; do
            for espera in activa bloqueante; do
                con=0; d=""; inc=""; er=""; re=""; ti=""
                for i in $(seq "$REP"); do
                    L="logs/fase4/e3_${modo}_${espera}_$i.log"; rm -f "$L"
                    python3 main.py $BASE --modo "$modo" --espera "$espera" --log "$L" > /dev/null
                    s=$(sonda "$L"); [[ "$s" -gt 0 ]] && con=$((con + 1))
                    d+="$s\n"; inc+="$(incons "$L")\n"; er+="$(enruta "$L")\n"
                    re+="$(num "$L" "espera activa\)")\n"; ti+="$(num "$L" "tiempo total")\n"
                done
                printf "%-10s %-12s %-18s %-10s %-10s %-10s %-10s %-10s\n" "$modo" "$espera" \
                    "$con/$REP" "$(printf "$d" | media)" "$(printf "$inc" | media)" \
                    "$(printf "$er" | media)/3" "$(printf "$re" | media)" "$(printf "$ti" | media)"
            done
        done
    } | tee "$DIR/e3_mecanismos.txt"
}

e4() {
    rm -f "$DIR"/e4_*
    echo "== E4: costo de la espera activa =="
    CARGA="-w 4 -t 4 -g 4 -n 48 -v 2 --ventana 0 -k 48"
    {
        echo "Carga: $CARGA (16 despachadores compiten por 2 vehículos), modo seguro"
        printf "\n%-26s %-10s %-12s %-14s %-14s %-12s\n" "ESPERA" "TIEMPO(s)" "CPU TRAB(s)" \
            "CPU MEDIA(%)" "CTX.VOLUNT." "REINTENTOS"
        for conf in "bloqueante" "activa 0.005" "activa 0"; do
            set -- $conf
            L="logs/fase4/e4_$1_${2:-na}.log"; rm -f "$L"
            extra="--espera $1"; [[ -n "${2:-}" ]] && extra+=" --reintento $2"
            python3 main.py $CARGA $extra --log "$L" > /dev/null &
            P=$!
            if [[ "$conf" == "activa 0" ]]; then
                sleep 4
                top -H -b -n 1 -w 200 -p "$(pgrep -d, -P "$P")" | sed -n '7,30p' > "$DIR/e4_top_espera_activa.txt"
            elif [[ "$conf" == "bloqueante" ]]; then
                sleep 4
                top -H -b -n 1 -w 200 -p "$(pgrep -d, -P "$P")" | sed -n '7,30p' > "$DIR/e4_top_bloqueante.txt"
            fi
            wait "$P"
            printf "%-26s %-10s %-12s %-14s %-14s %-12s\n" "$conf" "$(num "$L" "tiempo total")" \
                "$(num "$L" "trabajadores")" "$(cpu "$L")" "$(vcsw "$L")" "$(num "$L" "espera activa\)")"
        done
    } | tee "$DIR/e4_espera_activa.txt"
}

e5() {
    rm -f "$DIR"/e5_*
    echo "== E5: sección crítica fina frente a gruesa =="
    {
        echo "Carga: -w 2 -t 3 -g 4 -n 24 -v 3 --ventana 0.05 (validación de 50 ms), modo seguro"
        printf "\n%-10s %-10s %-22s %-22s %-14s\n" "SECCIÓN" "TIEMPO(s)" "ESPERA MUTEX PROM(ms)" \
            "ESPERA MUTEX MÁX(ms)" "DOBLES"
        for sec in fina gruesa; do
            L="logs/fase4/e5_$sec.log"; rm -f "$L"
            python3 main.py -w 2 -t 3 -g 4 -n 24 -v 3 --ventana 0.05 --seccion "$sec" --log "$L" > /dev/null
            printf "%-10s %-10s %-22s %-22s %-14s\n" "$sec" "$(num "$L" "tiempo total")" \
                "$(est "$L" | grep "mutex" | grep -oE "prom=[0-9.]+" | cut -d= -f2)" \
                "$(est "$L" | grep "mutex" | grep -oE "máx=[0-9.]+" | cut -d= -f2)" "$(sonda "$L")"
        done
    } | tee "$DIR/e5_seccion_critica.txt"
}

e6() {
    rm -f "$DIR"/e6_*
    echo "== E6: la corrección con hilos, procesos y ambos =="
    R6=$(( REP / 2 > 0 ? REP / 2 : 1 ))
    {
        echo "Carga de la Fase 3 (E4): 48 solicitudes en ráfagas, 3 vehículos, $R6 ejecuciones, versión corregida"
        printf "\n%-10s %-7s %-12s %-22s %-10s\n" "PROCESOS" "HILOS" "VENTANA(s)" "EJECUCIONES CON FALLO" "DOBLES"
        for vent in 0 0.001; do
            for conf in "1 6" "6 1" "2 3"; do
                set -- $conf; con=0; tot=0
                for i in $(seq "$R6"); do
                    L="logs/fase4/e6_$1_$2_${vent}_$i.log"; rm -f "$L"
                    python3 main.py -w "$1" -t "$2" -g 6 -n 48 --tam-rafaga 2 --intervalo 0.3 -v 3 \
                        --ventana "$vent" --log "$L" > /dev/null
                    s=$(sonda "$L"); tot=$((tot + s)); [[ "$s" -gt 0 ]] && con=$((con + 1))
                done
                printf "%-10s %-7s %-12s %-22s %-10s\n" "$1" "$2" "$vent" "$con/$R6" "$tot"
            done
        done
    } | tee "$DIR/e6_hilos_procesos.txt"
}

for e in $SECCIONES; do
    "$e"
done
echo "Evidencias en $DIR/"
