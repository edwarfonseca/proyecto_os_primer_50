#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 6 (CPU y memoria) y guarda las evidencias en
# evidencias/fase6/.
#
#   E1: tarea intensiva en CPU: escalamiento con hilos frente a procesos (efecto del GIL).
#   E2: la misma tarea vista desde el SO: top -H y estados de los hilos.
#   E3: carga mixta (CPU + esperas): tiempo y memoria de repartir 16 hilos en 1..16 procesos.
#   E4: crecimiento de memoria: historial sin límite (fuga) frente a acotado (controlado).
#
# Uso: scripts/evidencias_fase6.sh [SECCIONES...]   (≈ 5 min completo)

set -uo pipefail
cd "$(dirname "$0")/.."
SECCIONES="${*:-e1 e2 e3 e4}"
DIR="${DIR:-evidencias/fase6}"
mkdir -p "$DIR" logs/fase6

# Sin cuellos de botella de otras fases: vehículos, andenes y taller fuera del camino.
AISLADO="-v 100 -a 100 -i 0 --ventana 0 -s 42"

est() { sed -n '/ESTADÍSTICAS:/,$p' "$1"; }
num() { est "$1" | grep -oE "$2=[0-9.]+" | head -1 | cut -d= -f2; }

e1() {
    echo "== E1: CPU: hilos frente a procesos =="
    rm -f "$DIR"/e1_*
    CARGA="-g 4 -n 24 -k 24 -p 9 --despacho 0-0 --entrega 0-0 --traza-kb 0"
    {
        echo "Carga: 24 rutas de 9 puntos (362 880 recorridos cada una, sólo CPU), $AISLADO"
        printf "\n%-9s %-6s %-10s %-9s %-12s %-12s %-14s %-16s %-14s\n" "PROCESOS" "HILOS" \
            "TIEMPO(s)" "SPEEDUP" "CPU TRAB(%)" "REAL/CPU" "CTX INVOLUNT." "CPU TOTAL RUTAS" "SUMA LONGITUDES"
        base=""
        for conf in "1 1" "1 2" "1 4" "1 8" "2 1" "4 1" "8 1" "2 2" "4 2"; do
            set -- $conf
            L="logs/fase6/e1_w$1_t$2.log"; rm -f "$L"
            python3 main.py -w "$1" -t "$2" $CARGA $AISLADO --log "$L" > /dev/null
            t=$(num "$L" "tiempo total"); [[ -z "$base" ]] && base=$t
            printf "%-9s %-6s %-10s %-9s %-12s %-12s %-14s %-16s %-14s\n" "$1" "$2" "$t" \
                "$(awk -v b="$base" -v t="$t" 'BEGIN{printf "%.2fx", b/t}')" \
                "$(num "$L" "CPU de los trabajadores")" "$(num "$L" "real/CPU")" \
                "$(num "$L" "involuntarios")" "$(num "$L" "CPU total en rutas")" \
                "$(num "$L" "suma de longitudes")"
        done
        echo
        echo "Núcleos lógicos del equipo: $(nproc). REAL/CPU = tiempo real de cada ruta / CPU consumida por su hilo."
    } | tee "$DIR/e1_cpu_hilos_procesos.txt"
}

e2() {
    echo "== E2: la tarea de CPU vista desde el SO =="
    rm -f "$DIR"/e2_*
    for conf in "1 4" "4 1"; do
        set -- $conf
        L="logs/fase6/e2_w$1_t$2.log"; rm -f "$L"
        setsid python3 main.py -w "$1" -t "$2" -g 2 -n 0 --tam-rafaga 4 --intervalo 0.2 -k 40 -p 9 \
            --despacho 0-0 --entrega 0-0 --traza-kb 0 $AISLADO --log "$L" > /dev/null &
        PID=$!
        sleep 3
        HIJOS=$(pgrep -d, -P "$PID")
        {
            echo "## $1 proceso(s) x $2 hilo(s) calculando rutas: top -H (2.a muestra de 1 s)"
            top -H -b -n 2 -d 1 -w 200 -p "$HIJOS" | awk '/^top -/ {n++} n == 2' | sed -n '7,20p'
            echo
            echo "## ps -L: estado de los hilos despachadores (R = ejecutándose o listo)"
            for k in 1 2 3; do
                ps -L -o stat=,comm= -p "$HIJOS" | awk '/despachador/ {printf "%s:%s  ", $2, $1} END {print ""}'
                sleep 0.3
            done
        } > "$DIR/e2_top_w$1_t$2.txt"
        kill -INT -- "-$PID"
        wait "$PID"
        cat "$DIR/e2_top_w$1_t$2.txt"
    done
}

e3() {
    echo "== E3: carga mixta: repartir 16 hilos entre procesos =="
    rm -f "$DIR"/e3_*
    CARGA="-g 4 -n 48 -k 48 -p 8 --traza-kb 0"
    {
        echo "Carga: 48 solicitudes con ruta de 8 puntos (≈ 25 ms de CPU) + despacho 0.1-0.3 s + entrega 0.2-0.6 s"
        printf "\n%-9s %-6s %-7s %-10s %-12s %-10s %-14s %-14s\n" "PROCESOS" "HILOS" "TOTAL" \
            "TIEMPO(s)" "CPU TRAB(%)" "REAL/CPU" "PSS TOTAL(MB)" "RSS TOTAL(MB)"
        for conf in "4 1" "1 16" "2 8" "4 4" "8 2" "16 1"; do
            set -- $conf
            L="logs/fase6/e3_w$1_t$2.log"; rm -f "$L"
            python3 main.py -w "$1" -t "$2" $CARGA $AISLADO --muestreo 0.2 --log "$L" > /dev/null
            printf "%-9s %-6s %-7s %-10s %-12s %-10s %-14s %-14s\n" "$1" "$2" "$(($1 * $2))" \
                "$(num "$L" "tiempo total")" "$(num "$L" "CPU de los trabajadores")" \
                "$(num "$L" "real/CPU")" "$(est "$L" | grep -oE "PSS total \(suma de picos\)=[0-9.]+" | cut -d= -f2)" \
                "$(est "$L" | grep -oE "RSS total \(suma de picos\)=[0-9.]+" | cut -d= -f2)"
        done
    } | tee "$DIR/e3_mixta.txt"
}

e4() {
    echo "== E4: crecimiento de memoria =="
    rm -f "$DIR"/e4_*
    CARGA="-w 2 -t 3 -g 2 -n 200 --tam-rafaga 10 --intervalo 0.2 -k 50 -p 0 --despacho 0.01-0.02 --entrega 0.02-0.05 --traza-kb 256 --muestreo 0.25"
    for h in 0 20; do
        L="logs/fase6/e4_historial_$h.log"; rm -f "$L"
        python3 main.py $CARGA $AISLADO --historial "$h" --log "$L" > /dev/null
        cp "${L%.log}.recursos.csv" "$DIR/e4_historial_${h}.recursos.csv"
        grep -E "MEMORIA trabajador" "$L" | cut -c77-300 > "$DIR/e4_historial_${h}_resumen.txt"
        est "$L" | sed -n '/MEMORIA Y CPU/,/PSS total/p' | cut -c94-300 >> "$DIR/e4_historial_${h}_resumen.txt"
    done
    {
        echo "Carga: 200 entregas, traza GPS de 256 KB por entrega, 2 trabajadores x 3 hilos"
        echo "RSS de cada proceso (MB) en el tiempo; historial=0 -> sin límite; historial=20 -> 20 trazas por proceso"
        printf "\n%-7s %-24s %-24s %-24s\n" "t(s)" "trabajador-1 sin límite" "trabajador-1 acotado" "centro_despacho (acotado)"
        paste -d, \
            <(awk -F, '$3 == "trabajador-1" {print $1 "," $6}' "$DIR/e4_historial_0.recursos.csv") \
            <(awk -F, '$3 == "trabajador-1" {print $6}' "$DIR/e4_historial_20.recursos.csv") \
            <(awk -F, '$3 == "centro_despacho" {print $6}' "$DIR/e4_historial_20.recursos.csv") \
            | awk -F, 'NF >= 3 && $2 != "" {printf "%-7s %-24.1f %-24.1f %-24.1f\n", $1, $2/1024, $3/1024, $4/1024}'
        for h in 0 20; do echo; echo "## historial=$h"; cat "$DIR/e4_historial_${h}_resumen.txt"; done
    } | tee "$DIR/e4_memoria.txt"
}

for e in $SECCIONES; do
    "$e"
done
echo "Evidencias en $DIR/"
