#!/usr/bin/env bash
# Demostración guiada para la sustentación (≈ 8-10 min con explicaciones).
#
# Uso: scripts/demo.sh [PASOS...] [--sin-pausa]
#   scripts/demo.sh              los 7 pasos, con pausa (Enter) entre partes
#   scripts/demo.sh 2 3          sólo la condición de carrera y el interbloqueo
#   scripts/demo.sh --sin-pausa  sin pausas (ensayo)
#
#   1 procesos e hilos         2 condición de carrera: antes/después
#   3 interbloqueo             4 CPU: hilos frente a procesos (GIL)
#   5 espera activa            6 monitor: proceso detenido y recuperación
#   7 memoria

set -uo pipefail
cd "$(dirname "$0")/.."
PAUSA=1
PASOS=()
for a in "$@"; do
    case "$a" in --sin-pausa) PAUSA=0 ;; *) PASOS+=("$a") ;; esac
done
[[ ${#PASOS[@]} -eq 0 ]] && PASOS=(1 2 3 4 5 6 7)
L=logs/demo
mkdir -p "$L"
rm -f "$L"/*

B=$'\e[1m'; D=$'\e[2m'; N=$'\e[0m'
titulo() { printf "\n${B}══════ %s ══════${N}\n" "$1"; }
decir()  { for x in "$@"; do printf "  » %s\n" "$x"; done; }
cmd()    { printf "${B}\$ %s${N}\n" "$*"; }
pausa()  { [[ $PAUSA -eq 1 ]] && read -rp "  ${D}[Enter para continuar]${N} " _ || true; }
correr() { cmd "$*"; "$@"; }
# Muestra sólo las líneas del log que interesan (sin el prefijo PID/PPID/TID).
ver()    { grep -E "$2" "$1" | cut -c1-16,94-260; }
lanzar() {   # lanza el sistema en su propio grupo de procesos, en segundo plano
    cmd "python3 main.py $*  &"
    setsid python3 main.py "$@" > /dev/null 2>&1 &
    PID=$!
    sleep 2
}
detener() { cmd "kill -INT -- -$PID    # Ctrl+C a todo el grupo"; kill -INT -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null; }
AISLADO="-i 0 -a 100 -p 0 --traza-kb 0"

paso1() {
    titulo "1. Procesos e hilos (requisitos 1-3 y 14)"
    decir "Un proceso principal crea 2 procesos trabajadores y un taller; cada uno tiene hilos." \
          "Los nombres que se ven en el kernel son los del programa."
    lanzar -n 0 --tam-rafaga 3 --intervalo 0.5 --log "$L/p1.log"
    correr pstree -p -t "$PID"
    pausa
    correr ps -L -o pid,ppid,lwp,stat,wchan:20,comm -p "$PID,$(pgrep -d, -P "$PID")"
    decir "PPID de los trabajadores = PID del principal. LWP = TID del hilo en el kernel." \
          "futex_do_wait = bloqueado en un lock o semáforo; hrtimer_nanosleep = dormido por tiempo."
    pausa
    correr scripts/monitor_so.sh 1 2 "$PID"
    detener
    ver "$L/p1.log" "SEÑAL|VERIFICACIÓN|solicitudes:|FIN centro"
    pausa
}

paso2() {
    titulo "2. Condición de carrera en la asignación de vehículos (requisitos 7, 8 y 15)"
    decir "Misma carga (semilla 42): 24 solicitudes, 6 despachadores, 3 vehículos." \
          "ANTES: buscar vehículo libre y marcarlo sin exclusión mutua (check-then-act)."
    correr python3 main.py -n 24 -g 4 -v 3 --modo inseguro --espera activa $AISLADO --log "$L/p2a.log" > /dev/null
    echo "  exit code: $?"
    ver "$L/p2a.log" "DOBLE ASIGNACIÓN" | head -4
    ver "$L/p2a.log" "entregas con vehículo a la vez|DOBLES ASIGNACIONES|INCONSISTENTES|tiempo total|FIN centro"
    decir "Hasta 6 entregas en ruta con sólo 3 vehículos: el sistema 'rinde más' porque usa vehículos ocupados."
    pausa
    decir "DESPUÉS: mutex sobre la sección crítica + semáforo contador de vehículos libres."
    correr python3 main.py -n 24 -g 4 -v 3 --modo seguro --espera bloqueante $AISLADO --log "$L/p2b.log" > /dev/null
    echo "  exit code: $?"
    ver "$L/p2b.log" "entregas con vehículo a la vez|DOBLES ASIGNACIONES|INCONSISTENTES|espera por el mutex|tiempo total|FIN centro"
    decir "Cero dobles asignaciones. Tarda más porque ahora respeta los 3 vehículos (≈ 4.9 solicitudes/s es el máximo físico)."
    pausa
}

paso3() {
    titulo "3. Interbloqueo (requisitos 10 y 11)"
    decir "Cargue: vehículo -> andén. Inspección (proceso taller): andén -> vehículo. Orden opuesto."
    local ok=0
    for intento in 1 2 3; do
        lanzar -n 24 -g 4 -v 3 -a 2 -i 1 -p 0 --traza-kb 0 --interbloqueo sin_orden --espera-fin 3 \
            --log "$L/p3_$intento.log"
        for _ in $(seq 40); do
            grep -q "INTERBLOQUEO DETECTADO" "$L/p3_$intento.log" 2>/dev/null && { ok=1; break; }
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.25
        done
        [[ $ok -eq 1 ]] && break
        decir "Esta vez no se formó el ciclo (ocurre en ~8 de cada 10 ejecuciones); se repite."
        kill -INT -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null
    done
    if [[ $ok -eq 1 ]]; then
        ver "$L/p3_$intento.log" "INTERBLOQUEO DETECTADO"
        correr ps -L -o pid,lwp,stat,pcpu,wchan:20,comm -p "$(pgrep -d, -P "$PID")"
        decir "Los hilos del ciclo: estado S, 0 % de CPU, dormidos en futex_do_wait para siempre." \
              "El vigilante lo detectó con un ciclo en el grafo de espera y detiene el sistema."
        pausa
        wait "$PID" 2>/dev/null
        ver "$L/p3_$intento.log" "SIGTERM|solicitudes:|FIN centro"
    fi
    pausa
    decir "Estrategia 'orden': todos piden los recursos en el mismo orden global (rompe la espera circular)."
    correr python3 main.py -n 24 -g 4 -v 3 -a 2 -i 1 -p 0 --traza-kb 0 --interbloqueo orden --log "$L/p3_orden.log" > /dev/null
    ver "$L/p3_orden.log" "INTERBLOQUEOS:|RECURSOS:|FIN centro"
    decir "Estrategia 'deteccion': se deja ocurrir, se detecta el ciclo y la víctima suelta lo que tiene." \
          "(1 andén y 2 inspectores para que el ciclo aparezca con seguridad)"
    for intento in 1 2 3; do
        correr python3 main.py -n 12 -g 4 -v 3 -a 1 -i 2 -p 0 --traza-kb 0 --interbloqueo deteccion \
            --log "$L/p3_det_$intento.log" > /dev/null
        grep -q "RECUPERACIÓN ordenada" "$L/p3_det_$intento.log" && break
    done
    ver "$L/p3_det_$intento.log" "INTERBLOQUEO DETECTADO|RECUPERACIÓN ordenada" | head -2
    ver "$L/p3_det_$intento.log" "INTERBLOQUEOS:|FIN centro"
    pausa
}

paso4() {
    titulo "4. CPU: hilos frente a procesos (requisito 13, efecto del GIL)"
    decir "32 rutas de 9 puntos (362 880 recorridos cada una), sin esperas: sólo CPU."
    local C="-n 32 -g 4 -k 32 -p 9 --despacho 0-0 --entrega 0-0 -v 100 -a 100 -i 0 --traza-kb 0 --ventana 0"
    for conf in "1 4" "4 1"; do
        set -- $conf
        decir "$1 proceso(s) x $2 hilo(s):"
        lanzar -w "$1" -t "$2" $C --log "$L/p4_w$1.log"
        cmd "top -H -b -n 2 -d 0.5 -p <trabajadores>"
        top -H -b -n 2 -d 0.5 -w 160 -p "$(pgrep -d, -P "$PID")" | awk '/^top -/ {n++} n == 2' \
            | grep -E "PID|despachador" | head -6
        wait "$PID" 2>/dev/null
        ver "$L/p4_w$1.log" "tiempo total|RUTAS:"
        pausa
    done
    decir "Con hilos: un solo hilo en R (el que tiene el GIL), ~25 % cada uno; real/CPU alto = esperan el GIL." \
          "Con procesos: todos en R cerca del 100 %; cada proceso tiene su propio GIL."
    pausa
}

paso5() {
    titulo "5. Espera activa frente a espera bloqueante (síntoma: CPU elevada)"
    decir "16 despachadores compiten por 2 vehículos. Mismo trabajo, distinta forma de esperar."
    local C="-w 4 -t 4 -g 4 -n 24 -k 24 -v 2 --ventana 0 $AISLADO"
    correr python3 main.py $C --espera activa --reintento 0 --log "$L/p5a.log" > /dev/null
    ver "$L/p5a.log" "tiempo total|CPU:|cambios de contexto"
    correr python3 main.py $C --espera bloqueante --log "$L/p5b.log" > /dev/null
    ver "$L/p5b.log" "tiempo total|CPU:|cambios de contexto"
    decir "Mismo tiempo total; la espera activa quema CPU preguntando. El semáforo duerme al hilo en el kernel."
    pausa
}

paso6() {
    titulo "6. Monitor en vivo: proceso detenido y recuperación (requisito 12)"
    decir "El monitor registra cada segundo recibidas, en cola, en proceso, vehículos y finalizadas."
    cmd "python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5 --alerta-sin-progreso 3 --vista resumen &"
    setsid python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5 --alerta-sin-progreso 3 --vista resumen \
        --log "$L/p6.log" 2>/dev/null | grep --line-buffered -E "ESTADO|SIN PROGRESO" \
        | stdbuf -oL cut -c1-190 &
    sleep 3
    PID=$(pgrep -xn centro_despacho)
    W=$(pgrep -P "$PID" | xargs -I{} sh -c 'grep -q trabajador /proc/{}/comm && echo {}' | tr '\n' ' ')
    cmd "kill -STOP $W    # ambos trabajadores detenidos (estado T)"
    kill -STOP $W
    sleep 5
    cmd "kill -CONT $W"
    kill -CONT $W
    sleep 3
    kill -INT -- "-$PID" 2>/dev/null
    sleep 2
    decir "Rendimiento a 0, alerta SIN PROGRESO a los 3 s y recuperación sola con SIGCONT."
    pausa
}

paso7() {
    titulo "7. Crecimiento de memoria: sin límite frente a acotado"
    local C="-n 120 --tam-rafaga 10 --intervalo 0.2 -k 40 --despacho 0.01-0.02 --entrega 0.02-0.05 --traza-kb 256 -v 100 -a 100 -i 0 -p 0 --ventana 0"
    for h in 0 20; do
        correr python3 main.py $C --historial "$h" --log "$L/p7_$h.log" > /dev/null
        ver "$L/p7_$h.log" "MEMORIA trabajador 1"
    done
    decir "Sin límite: cada entrega deja 256 KB y el RSS crece sin parar (como una fuga)." \
          "Acotado: se descartan las trazas viejas y la memoria se estabiliza."
    pausa
}

for p in "${PASOS[@]}"; do
    "paso$p"
done
titulo "Fin de la demostración (logs en $L/)"
