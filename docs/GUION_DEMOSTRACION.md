# Guion de demostración — Proyecto 6: Sistema de despacho y logística

Duración objetivo: **10 minutos** (7 de demostración + 3 de introducción y cierre). El script
`scripts/demo.sh` ejecuta cada paso con los comandos exactos y se detiene (Enter) entre partes,
para explicar sin teclear comandos en vivo.

## Antes de la sustentación

- [ ] `scripts/verificar.sh` → debe terminar con **0 fallas** (≈ 40 s).
- [ ] `scripts/demo.sh --sin-pausa` una vez como ensayo (≈ 3 min sin pausas).
- [ ] Cerrar navegadores y programas pesados: E4 y E5 miden CPU.
- [ ] Terminal grande, fuente ≥ 14 pt, tema claro si se proyecta. Una segunda terminal abierta
      en la carpeta del proyecto por si piden un comando adicional.
- [ ] Tener abiertos `docs/BITACORA_TECNICA.md` (secciones 8.4 y 8.5) y las gráficas de
      `evidencias/fase8/graficas/` por si piden ver resultados completos.

## Introducción (1 min, sin comandos)

> "Construimos un centro de despacho que reproduce los tres síntomas del enunciado —dos
> solicitudes en el mismo vehículo, despachos que quedan esperando y CPU elevada—, los explica
> con conceptos del sistema operativo, los corrige y mide la diferencia."

Mostrar el diagrama de la arquitectura final (bitácora, sección 9.2): proceso principal con sus
hilos (generadores, vigilante, monitor, muestreador), 2 procesos trabajadores con hilos
despachadores, proceso taller con inspectores; recursos compartidos: cola acotada, flota,
andenes, contadores.

## Paso 1 — Procesos e hilos (1 min) · `scripts/demo.sh 1`

| En pantalla | Qué señalar | Qué decir |
|---|---|---|
| `pstree -p -t` | Tres hijos del principal; hilos entre `{}` | "Los procesos cuelgan del padre; los hilos, del proceso que los contiene. Los nombres son los de nuestro programa: Python 3.14 los copia al kernel." |
| `ps -L ... wchan` | `PPID` de los trabajadores = PID del principal; columna `LWP` | "LWP es el identificador del hilo en el kernel: es el mismo TID que aparece en nuestro log." |
| `ps -L` columna `WCHAN` | `futex_do_wait` y `hrtimer_nanosleep` | "Casi todo el sistema está esperando: en un lock o semáforo (futex) o durmiendo por tiempo (ruta simulada)." |
| `monitor_so.sh` | Hilos por estado R/S/D, %CPU | "Nuestra vista en vivo desde /proc." |
| Tras el Ctrl+C | `sin zombis ni huérfanos`, balance | "Ctrl+C llega a todo el grupo; sólo el principal coordina el cierre ordenado." |

## Paso 2 — Condición de carrera: antes/después (1.5 min) · `scripts/demo.sh 2`

- **Antes:** señalar las líneas `DOBLE ASIGNACIÓN ... [entre procesos]` y
  `entregas con vehículo a la vez: máx=6 con 3 vehículos`.
  > "Buscar un vehículo libre y marcarlo son dos pasos separados. Dos despachadores ven el mismo
  > vehículo libre antes de que alguno lo marque. El programa terminó 'bien', pero el resultado es
  > incorrecto: por eso devuelve código de salida 1."
- **Después:** `sonda en vivo=0`, `máx=3 con 3 vehículos`, `espera por el mutex ... 0.00`.
  > "Un mutex hace indivisible buscar y marcar; un semáforo cuenta los vehículos libres. El mutex
  > cuesta centésimas de milisegundo; el tiempo extra es respetar que sólo hay 3 vehículos: la
  > versión insegura rendía más porque usaba vehículos que no tenía."

## Paso 3 — Interbloqueo (2 min) · `scripts/demo.sh 3`

- Señalar el ciclo: `inspector-1 [tiene A2, espera V1] -> despachador-2-2 [tiene V1, espera A2]`.
  > "El cargue pide vehículo y luego andén; la inspección, andén y luego vehículo. Se cumplen las
  > cuatro condiciones de Coffman: exclusión mutua, retención y espera, no expropiación y espera
  > circular."
- En `ps -L`: los hilos en `futex_do_wait` con 0 % de CPU.
  > "No es lentitud: el kernel no los volverá a planificar nunca. Nuestro vigilante construye el
  > grafo de espera, encuentra el ciclo y detiene el sistema; hay que terminarlos con SIGTERM."
- `orden`: `detectados=0`, `correcto`. `deteccion`: `RECUPERACIÓN ordenada: víctima inspector-1`.
  > "La estrategia por defecto rompe la espera circular con un orden global. La de detección deja
  > que ocurra y expropia a una víctima: la inspección, que es la operación más barata de repetir."
- **Si no se forma el ciclo:** el script reintenta 3 veces (ocurre en ~8 de cada 10 ejecuciones).
  Si aun así no aparece, decir que es precisamente una **posibilidad** probabilística y mostrar
  `evidencias/fase5/e1_observacion.txt` (una ejecución real capturada).

## Paso 4 — CPU: hilos frente a procesos (1 min) · `scripts/demo.sh 4`

- 1 × 4: en `top -H` un solo hilo en `R`, los cuatro alrededor de 25 %; `real/CPU ≈ 3`.
- 4 × 1: los cuatro en `R` cerca del 80–100 %; `real/CPU ≈ 1`; tiempo total ≈ la mitad.
  > "Con hilos, el GIL deja ejecutar Python a uno solo a la vez: cada ruta espera tres veces su
  > tiempo de CPU. Con procesos, cada uno tiene su propio GIL. No llega a 4x porque este equipo
  > tiene 2 núcleos físicos con Hyper-Threading."
- La suma de longitudes es la misma: la concurrencia no altera el resultado.

## Paso 5 — Espera activa (45 s) · `scripts/demo.sh 5`

- Comparar la línea `CPU:` de las dos ejecuciones (≈ 9 s frente a ≈ 0.2 s) con el mismo tiempo total.
  > "Es el síntoma de CPU elevada del enunciado. Los hilos sin vehículo preguntaban en un bucle;
  > con el semáforo duermen en el kernel hasta que alguien libera un vehículo."

## Paso 6 — Monitor en vivo (45 s) · `scripts/demo.sh 6`

- Las líneas `ESTADO` cada segundo: recibidas, en cola, en proceso, vehículos (con su solicitud),
  finalizadas. Tras `kill -STOP`: todo congelado, **`SIN PROGRESO`** a los 3 s. Tras `kill -CONT`:
  el sistema se recupera solo.
  > "El requisito 12 en vivo. El monitor detecta que el sistema no avanza por cualquier causa; el
  > vigilante del paso 3 explica por qué cuando es un interbloqueo."

## Paso 7 — Memoria (30 s) · `scripts/demo.sh 7`

- Comparar `RSS` y `privada modificada` de las dos líneas `MEMORIA trabajador 1`.
  > "Sin límite, cada entrega deja 256 KB: es una fuga. Acotado, se descartan las trazas viejas y
  > la memoria se estabiliza. Medimos con PSS y memoria privada, no con VSZ, que incluye memoria
  > reservada que nunca se usa."

## Cierre (1 min)

Mostrar la tabla 8.4 de la bitácora o la gráfica G1 (`g1_dobles_asignaciones.svg`):

> "Cada síntoma tiene una causa del sistema operativo, una corrección y una medición antes y
> después con la misma carga: 78 % de asignaciones en conflicto → 0; interbloqueo en todas las
> ejecuciones → en ninguna; 99 veces menos CPU al esperar. Además documentamos seis problemas
> reales que aparecieron durante el desarrollo, cada uno corregido y medido."

## Si piden algo fuera del guion

| Pedido | Comando |
|---|---|
| Ver todos los parámetros | `python3 main.py --help` |
| Una ejecución normal | `python3 main.py --vista resumen` |
| Observar mientras corre | terminal 1: `python3 main.py -n 0`; terminal 2: `scripts/observar.sh` |
| La pila de cada hilo | `kill -USR1 $(pgrep -x trabajador-1)` (se imprime en la terminal 1) |
| Jerarquía con `forkserver` | `python3 main.py -n 0 --metodo-inicio forkserver` + `pstree -p $(pgrep -xo centro_despacho)` |
| El hallazgo H1 | `python3 experimentos/h1_event_bloqueado.py` y luego con `--corregido` |
| El hallazgo H6 | `python3 experimentos/h6_contador_compartido.py 50000` |
| Volver a una fase anterior | `git checkout fase-3` (y `git checkout main` para volver) |
