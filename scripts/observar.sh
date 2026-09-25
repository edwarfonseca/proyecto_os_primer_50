#!/usr/bin/env bash
# Captura el estado del sistema de despacho con herramientas del SO.
#
# Uso: scripts/observar.sh [PID_principal] [archivo_salida]
#   PID_principal : por defecto se busca el proceso llamado "centro_despacho".
#   archivo_salida: si se indica, la salida también se guarda en ese archivo.

set -euo pipefail

PID="${1:-$(pgrep -xo centro_despacho || true)}"
SALIDA="${2:-/dev/null}"

if [[ -z "$PID" ]] || [[ ! -d "/proc/$PID" ]]; then
    echo "No se encontró el proceso principal (centro_despacho). ¿Está en ejecución?" >&2
    exit 1
fi

HIJOS="$(pgrep -P "$PID" | paste -sd, -)"
TODOS="$PID${HIJOS:+,$HIJOS}"

titulo() { printf '\n===== %s =====\n' "$1"; }

{
    echo "Captura: $(date '+%Y-%m-%d %H:%M:%S') | kernel $(uname -r) | PID principal: $PID"

    titulo "1. Jerarquía de procesos e hilos (pstree -p -t: {..} = hilos)"
    pstree -p -t "$PID"

    titulo "2. Procesos: identidad, estado y recursos (ps -o)"
    ps -o pid,ppid,pgid,stat,nlwp,pcpu,pmem,rss,vsz,etime,comm,args -p "$TODOS"

    titulo "3. Hilos de cada proceso (ps -eLf filtrado; LWP = TID del kernel)"
    ps -eLf | awk -v pids=",$TODOS," 'NR==1 || index(pids, ","$2",")'

    titulo "4. Hilos con nombre, estado y CPU (ps -L)"
    ps -L -o pid,lwp,stat,pcpu,wchan:24,comm -p "$TODOS"

    titulo "5. /proc/<pid>/status (campos relevantes)"
    for p in ${TODOS//,/ }; do
        echo "-- PID $p"
        grep -E '^(Name|State|Pid|PPid|Threads|VmRSS|VmSize|voluntary_ctxt_switches|nonvoluntary_ctxt_switches):' \
            "/proc/$p/status" | sed 's/^/   /'
        # PSS reparte las páginas compartidas (copy-on-write tras fork) entre quienes
        # las comparten; a diferencia de RSS, la suma de PSS sí es la memoria real.
        grep -E '^(Rss|Pss|Shared_Clean|Private_Dirty):' "/proc/$p/smaps_rollup" 2>/dev/null \
            | sed 's/^/   /' || true
    done
} | tee "$SALIDA"
