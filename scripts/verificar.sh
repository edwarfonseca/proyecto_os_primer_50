#!/usr/bin/env bash
# Verificación rápida del proyecto (≈ 1-2 min): úsela antes de una demostración.
# Comprueba que el código compila y que cada versión se comporta como se documentó.
#
# Uso: scripts/verificar.sh

set -uo pipefail
cd "$(dirname "$0")/.."
L=logs/verificacion
mkdir -p "$L"
rm -f "$L"/*
ok=0; falla=0

check() {   # check id "descripción" código_esperado comando...
    local id="$1" desc="$2" esperado="$3"; shift 3
    local log="$L/$id.log"
    "$@" --log "$log" > /dev/null 2>&1
    local ex=$?
    if [[ "$esperado" == "*" || "$ex" == "$esperado" ]]; then
        printf "  [OK]    %-58s exit=%s\n" "$desc" "$ex"; ok=$((ok + 1))
    else
        printf "  [FALLA] %-58s exit=%s (se esperaba %s) -> %s\n" "$desc" "$ex" "$esperado" "$log"
        falla=$((falla + 1))
    fi
}

echo "Entorno: $(python3 --version), $(nproc) CPU lógicas, kernel $(uname -r)"
echo
echo "1. Sintaxis"
if python3 -m py_compile main.py despacho/*.py experimentos/*.py && bash -n scripts/*.sh experimentos/*.sh; then
    echo "  [OK]    código Python y scripts de shell"; ok=$((ok + 1))
else
    echo "  [FALLA] errores de sintaxis"; falla=$((falla + 1))
fi

echo "2. Comportamiento de cada versión"
R="-n 12 -s 42"
check defecto "versión por defecto (corregida)"               0 python3 main.py $R
check inseguro "versión con la condición de carrera (exit 1)"   1 python3 main.py $R --modo inseguro --espera activa -i 0 -a 100
check orden "interbloqueo: estrategia orden"                0 python3 main.py $R --interbloqueo orden
check timeout "interbloqueo: estrategia timeout"              0 python3 main.py $R --interbloqueo timeout
check deteccion "interbloqueo: estrategia deteccion"            0 python3 main.py $R --interbloqueo deteccion
check sin_orden "interbloqueo: sin_orden (0 ó 1: puede ocurrir)" "*" python3 main.py $R --interbloqueo sin_orden --espera-fin 1
check cola_mp "cola multiprocessing.Queue (--cola mp)"        0 python3 main.py $R --cola mp
check forkserver "método de inicio forkserver"                   0 python3 main.py $R --metodo-inicio forkserver
check cpu_memoria "CPU y memoria (rutas de 8 puntos, trazas 128 KB)" 0 python3 main.py $R -p 8 --traza-kb 128 --historial 5

echo "3. Detectores"
if grep -q "DOBLE ASIGNACIÓN" "$L/inseguro.log" 2>/dev/null; then
    echo "  [OK]    la versión insegura registra dobles asignaciones"; ok=$((ok + 1))
else
    echo "  [FALLA] la versión insegura no registró dobles asignaciones"; falla=$((falla + 1))
fi
if grep -q "coinciden" "$L/defecto.log" 2>/dev/null; then
    echo "  [OK]    los contadores del monitor coinciden con los resultados"; ok=$((ok + 1))
else
    echo "  [FALLA] el registro no coincide"; falla=$((falla + 1))
fi

echo "4. Herramientas de observación"
setsid python3 main.py -n 0 --tam-rafaga 2 --intervalo 0.5 --log "$L/observacion.log" > /dev/null 2>&1 &
PID=$!
sleep 2
if scripts/observar.sh "$PID" > /dev/null 2>&1 && scripts/monitor_so.sh 0.5 1 "$PID" > /dev/null 2>&1; then
    echo "  [OK]    observar.sh y monitor_so.sh"; ok=$((ok + 1))
else
    echo "  [FALLA] observar.sh o monitor_so.sh"; falla=$((falla + 1))
fi
kill -INT -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null
if python3 experimentos/h1_event_bloqueado.py --corregido > /dev/null 2>&1; then
    echo "  [OK]    experimento H1 (versión corregida)"; ok=$((ok + 1))
else
    echo "  [FALLA] experimento H1"; falla=$((falla + 1))
fi

echo
echo "Resultado: $ok correctas, $falla fallas (logs en $L/)"
[[ $falla -eq 0 ]]
