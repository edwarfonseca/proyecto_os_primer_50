#!/usr/bin/env bash
# Reproduce los escenarios de la Fase 1 y guarda las evidencias en evidencias/fase1/.
#
#   E1: ejecución normal + observación con herramientas del SO + Ctrl+C al grupo.
#   E2: un trabajador muere por SIGKILL: estado zombi y detección por el principal.
#   E3: trabajador detenido con SIGSTOP: escalamiento SIGTERM -> SIGKILL en el cierre.
#   E4: comparación del método de inicio forkserver (PPID distinto) frente a fork.
#   E5: el principal muere con SIGKILL: los trabajadores quedan huérfanos y lo detectan.
#
# Uso: scripts/evidencias_fase1.sh   (desde la raíz del proyecto)

set -uo pipefail
cd "$(dirname "$0")/.."
# La flota (Fase 3+) no existía en esta fase: se usan vehículos de sobra y sin ventana
# para que no sea un cuello de botella y los resultados sigan siendo comparables.
SIN_FLOTA="-v 100 --ventana 0 -a 100 -i 0"   # sin taller ni andenes limitados (Fase 5+)
DIR="${DIR:-evidencias/fase1}"
mkdir -p "$DIR"
rm -f "$DIR"/e[0-9]_*

# Lanza el sistema en su propio grupo de procesos (setsid) para poder enviar señales
# al grupo completo, como hace el terminal al pulsar Ctrl+C. Se usa generación
# continua (-n 0) para que el sistema siga activo mientras se observa.
lanzar() { setsid python3 main.py $SIN_FLOTA -n 0 "$@" > /dev/null & PID=$!; sleep 1.5; }

# Espera a que el principal termine (máx. 15 s). Si no termina, lo reporta como
# bloqueado y elimina el grupo completo para no dejar procesos colgados.
esperar() {
    local log="$1"
    for _ in $(seq 150); do
        kill -0 "$PID" 2>/dev/null || { wait "$PID"; echo "exit code del principal: $?" | tee -a "$log"; return; }
        sleep 0.1
    done
    echo "BLOQUEADO: el principal no terminó en 15 s; se elimina el grupo" | tee -a "$log"
    kill -KILL -- "-$PID"
}

echo "== E1: ejecución normal y observación =="
lanzar -w 3 -d 0 --log "$DIR/e1_ejecucion.log"
scripts/observar.sh "$PID" "$DIR/e1_observacion.txt" > /dev/null
{
    echo "## top -H -b -n 1 (vista por hilos)"
    top -H -b -n 1 -w 200 -p "$(pgrep -d, -s "$PID")" | head -n 15
} > "$DIR/e1_top.txt"
kill -INT -- "-$PID"          # SIGINT a TODO el grupo = Ctrl+C
esperar "$DIR/e1_ejecucion.log"

echo "== E2: trabajador terminado con SIGKILL =="
lanzar -w 3 -d 0 --log "$DIR/e2_ejecucion.log"
VICTIMA=$(pgrep -P "$PID" -x trabajador-2)
{
    echo "## Antes: hijos del principal (PID $PID)"
    ps -o pid,ppid,stat,comm --ppid "$PID"
    echo; echo "## kill -KILL $VICTIMA; ps inmediatamente después"
    kill -KILL "$VICTIMA"
    ps -o pid,ppid,stat,comm -p "$VICTIMA"
    sleep 0.5
    echo; echo "## 0.5 s después (el principal ya hizo waitpid)"
    ps -o pid,ppid,stat,comm --ppid "$PID"
} > "$DIR/e2_zombi.txt" 2>&1
kill -TERM "$PID"
esperar "$DIR/e2_ejecucion.log"

echo "== E3: trabajador detenido (SIGSTOP) durante el cierre =="
lanzar -w 2 -d 0 --espera-fin 1.5 --log "$DIR/e3_ejecucion.log"
DETENIDO=$(pgrep -P "$PID" -x trabajador-1)
kill -STOP "$DETENIDO"
{
    echo "## kill -STOP $DETENIDO"
    ps -o pid,ppid,stat,wchan:20,comm --ppid "$PID"
} > "$DIR/e3_detenido.txt"
kill -INT "$PID"
esperar "$DIR/e3_ejecucion.log"

echo "== E4: método de inicio forkserver =="
lanzar -w 2 -d 0 --metodo-inicio forkserver --log "$DIR/e4_ejecucion.log"
{
    echo "## pstree -p -t con --metodo-inicio forkserver"
    pstree -p -t "$PID"
    echo; echo "## ps: observe el PPID de los trabajadores"
    ps -o pid,ppid,stat,comm,args -p "$PID,$(pgrep -d, -P "$PID"),$(pgrep -d, -P "$(pgrep -d, -P "$PID")")"
} > "$DIR/e4_forkserver.txt" 2>&1
kill -INT -- "-$PID"
esperar "$DIR/e4_ejecucion.log"

echo "== E5: el principal muere con SIGKILL (trabajadores huérfanos) =="
lanzar -w 2 -d 0 --log "$DIR/e5_ejecucion.log"
{
    echo "## Antes: grupo de procesos $PID"
    ps -o pid,ppid,stat,comm -g "$PID"
    kill -KILL "$PID"
    echo; echo "## kill -KILL $PID (sólo el principal); ps inmediatamente después"
    ps -o pid,ppid,stat,comm -g "$PID"
    sleep 0.5
    echo; echo "## 0.5 s después (los trabajadores detectaron la orfandad y terminaron)"
    ps -o pid,ppid,stat,comm -g "$PID" || echo "(no queda ningún proceso del grupo)"
    echo; echo "## Proceso que los adoptó"
    ps -o pid,ppid,comm,args -p "$(grep -m1 -o 'adoptado por PID [0-9]*' "$DIR/e5_ejecucion.log" | grep -o '[0-9]*$')"
} > "$DIR/e5_huerfanos.txt"
wait "$PID" 2>/dev/null

echo "Evidencias en $DIR/"
