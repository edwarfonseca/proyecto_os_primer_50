#!/usr/bin/env bash
# Vista en vivo del sistema de despacho desde el SO (una "mini top" de sus procesos).
#
# Uso: scripts/monitor_so.sh [INTERVALO_s] [REPETICIONES] [PID_principal]
#   Por defecto: cada 1 s, hasta Ctrl+C, busca el proceso "centro_despacho".
#
# Para cada proceso: PID, PPID, estado, hilos, hilos por estado (R/S/D) y %CPU del
# intervalo (ticks de utime+stime en /proc/<pid>/stat entre dos lecturas).

set -uo pipefail
INTERVALO="${1:-1}"
REPETICIONES="${2:-0}"
PID="${3:-$(pgrep -xo centro_despacho || true)}"
[[ -z "$PID" || ! -d /proc/$PID ]] && { echo "centro_despacho no está en ejecución" >&2; exit 1; }
TICKS=$(getconf CLK_TCK)
declare -A antes

ticks() { awk '{print $14 + $15}' "/proc/$1/stat" 2>/dev/null || echo 0; }
for p in $PID $(pgrep -P "$PID"); do antes[$p]=$(ticks "$p"); done

n=0
while [[ -d /proc/$PID ]]; do
    sleep "$INTERVALO"
    printf "\n== %s | centro_despacho PID %s ==\n" "$(date +%T)" "$PID"
    printf "%-16s %-8s %-8s %-6s %-6s %-4s %-4s %-4s %-7s %-8s\n" \
        "PROCESO" "PID" "PPID" "ESTADO" "HILOS" "R" "S" "D" "CPU%" "RSS(MB)"
    for p in $PID $(pgrep -P "$PID"); do
        [[ -r /proc/$p/stat ]] || continue
        t=$(ticks "$p"); d=$(( t - ${antes[$p]:-$t} )); antes[$p]=$t
        estados=$(cat /proc/"$p"/task/*/stat 2>/dev/null | awk '{print $3}' | sort | uniq -c \
            | awk '{c[$2] = $1} END {printf "%d %d %d", c["R"], c["S"], c["D"]}')
        read -r r s dd <<< "$estados"
        printf "%-16s %-8s %-8s %-6s %-6s %-4s %-4s %-4s %-7s %-8s\n" "$(cat /proc/$p/comm)" "$p" \
            "$(awk '/^PPid/ {print $2}' /proc/$p/status)" "$(awk '{print $3}' /proc/$p/stat)" \
            "$(awk '/^Threads/ {print $2}' /proc/$p/status)" "$r" "$s" "$dd" \
            "$(awk -v d="$d" -v t="$TICKS" -v i="$INTERVALO" 'BEGIN {printf "%.0f", 100 * d / t / i}')" \
            "$(awk '/^VmRSS/ {printf "%.1f", $2 / 1024}' /proc/$p/status)"
    done
    n=$((n + 1))
    [[ "$REPETICIONES" -gt 0 && "$n" -ge "$REPETICIONES" ]] && break
done
