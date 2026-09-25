# Sistema de despacho y logística — Proyecto 6

Proyecto práctico de **Sistemas Operativos** (UPTC, primer 50 %). Simula el centro de despacho de
una empresa de transporte con **procesos, hilos, productor-consumidor, sincronización,
interbloqueos, CPU y memoria**, y lo observa con herramientas del SO Linux (`ps`, `pstree`, `top`,
`/proc`).

El sistema reproduce los tres síntomas del enunciado, los explica con conceptos del sistema
operativo, los corrige y mide la diferencia con la misma carga:

| Síntoma | Causa | Corrección | Antes → después |
|---|---|---|---|
| Dos solicitudes asignadas al mismo vehículo | Condición de carrera *check-then-act* en memoria compartida | Mutex + semáforo contador | 78 % de asignaciones en conflicto → 0 |
| Despachos que quedan esperando | Interbloqueo vehículo ↔ andén (órdenes opuestos) | Orden global de recursos | 6/6 ejecuciones bloqueadas → 0/18 |
| CPU elevada con muchas solicitudes | Espera activa (sondeo) y cálculo limitado por el GIL | Semáforo (espera bloqueante); procesos para la CPU | 25.6 s → 0.26 s de CPU |

## Requisitos
- **Linux** (usa `/proc`, `fork`, semáforos POSIX en `/dev/shm`).
- **Python 3.14** (desarrollado y probado con 3.14.7). Sólo biblioteca estándar: no hay nada que
  instalar. El código no usa sintaxis exclusiva de versiones recientes y debería funcionar desde
  3.10, pero sólo se probó en 3.14. Con versiones anteriores a 3.14 los hilos no muestran su
  nombre en `ps`/`top` (aparecen como `python3`).
- Herramientas de observación: `ps`, `pstree`, `top` (paquetes `procps-ng` y `psmisc`).

## Inicio rápido
```bash
scripts/verificar.sh                     # comprueba que todo funciona (≈ 40 s)
python3 main.py --vista resumen          # una ejecución: estado cada segundo + resumen final
scripts/demo.sh                          # demostración guiada de 7 pasos (≈ 8 min)
```

## Arquitectura
```
centro_despacho (proceso principal)
├── hilos: generador-1..g (productores, llegada simultánea con Barrier)
│          vigilante (grafo de espera: detecta interbloqueos)
│          monitor (estado en vivo: recibidas, pendientes, vehículos, finalizadas)
│          muestreador (CPU y memoria de cada proceso desde /proc)
├── trabajador-1..w (procesos)
│   └── hilos: despachador-w-1..t (consumidores: planifican la ruta, asignan vehículo,
│              cargan en un andén y entregan)
└── taller (proceso)
    └── hilos: inspector-1..i (inspeccionan vehículos en los andenes)

Compartido entre procesos (memoria compartida /dev/shm + semáforos POSIX):
  cola de solicitudes (ColaAcotada: semáforos vacíos/llenos + mutex), flota de vehículos
  (mutex + semáforo contador), locks de vehículos y andenes (orden global), contadores del
  monitor, cola de resultados, indicador de parada.
```
El diagrama detallado, con cada recurso y su mecanismo de sincronización, está en la
[bitácora, sección 9.2](docs/BITACORA_TECNICA.md).

## Ejecución
```bash
python3 main.py --help                                      # todos los parámetros
python3 main.py                                             # 2 trabajadores x 3 hilos, 20 solicitudes
python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5         # generación continua hasta Ctrl+C
python3 main.py -w 2 -t 3 -g 4 -n 24 --tam-rafaga 2 -k 5    # ráfagas simultáneas, cola de 5
```

### Versiones seleccionables (antes / después)
| Fenómeno | Versión con el problema | Versión corregida (defecto) |
|---|---|---|
| Condición de carrera en la asignación | `--modo inseguro --espera activa` | `--modo seguro --espera bloqueante` |
| Interbloqueo | `--interbloqueo sin_orden` | `--interbloqueo orden` (alternativas: `timeout`, `deteccion`) |
| Espera por vehículo | `--espera activa --reintento 0` | `--espera bloqueante` |
| Cola productor-consumidor ante un proceso caído | `--cola mp` | `--cola semaforos` |
| Memoria | `--traza-kb 256 --historial 0` | `--historial 50` |

El código de salida es **1** cuando el sistema detecta un resultado incorrecto (dobles
asignaciones, interbloqueo no resuelto, balance que no cuadra) y **0** cuando todo es correcto.

### Parámetros principales
| Grupo | Parámetros (defecto) |
|---|---|
| Procesos e hilos | `-w` trabajadores (2), `-t` hilos por trabajador (3), `-g` generadores (2), `--metodo-inicio` (fork) |
| Carga | `-n` solicitudes (20; 0 = continuo), `--tam-rafaga` (0 = todas juntas), `--intervalo` (1 s), `-k` capacidad de la cola (10), `--despacho` (0.1-0.3 s), `--entrega` (0.2-0.6 s), `-s` semilla (42) |
| Flota | `-v` vehículos (3), `--ventana` de validación (0.01 s), `--modo`, `--espera`, `--seccion` (fina), `--reintento` (0.005 s) |
| Interbloqueo | `-a` andenes (2), `-i` inspectores (1), `--interbloqueo` (orden), `--timeout-recurso` (0.1 s), `--alistar-anden` (0.05 s) |
| CPU y memoria | `-p` puntos de entrega por ruta (7; P! recorridos), `--traza-kb` (64), `--historial` (50; 0 = sin límite), `--muestreo` (0.5 s) |
| Registro | `--vista` (completa o resumen), `--intervalo-monitor` (1 s), `--alerta-sin-progreso` (5 s), `--log` |
| Ejecución | `-d` duración máxima (0 = sin límite), `--espera-fin` (3 s de gracia antes de SIGTERM) |

## Observación con herramientas del SO
Con el sistema en ejecución (`python3 main.py -n 0`), en otra terminal:
```bash
scripts/observar.sh                      # pstree, ps, ps -eLf, ps -L (wchan), /proc, memoria compartida
scripts/monitor_so.sh                    # vista en vivo: procesos, hilos por estado R/S/D, %CPU, RSS
pstree -p -t $(pgrep -xo centro_despacho)
top -H -p $(pgrep -d, -f "main.py")
kill -USR1 $(pgrep -x trabajador-1)      # pila de todos los hilos del proceso (en su stderr)
```

## Registros de cada ejecución
| Archivo | Contenido |
|---|---|
| `logs/<nombre>.log` | eventos con hora, PID, PPID, TID, proceso e hilo, y el resumen final |
| `logs/<nombre>.estado.csv` | cada segundo: recibidas, en cola, en proceso, vehículos asignados/disponibles, finalizadas |
| `logs/<nombre>.recursos.csv` | cada 0.5 s y por proceso: estado, hilos, RSS, PSS, memoria privada, CPU |

## Reproducir las evidencias
Cada archivo de `evidencias/` lo genera un script, con ejecuciones reales:
```bash
scripts/evidencias_fase1.sh        # procesos, señales, zombis, huérfanos, forkserver
scripts/evidencias_fase2.sh        # hilos, productor-consumidor, llegada simultánea, escalamiento
scripts/evidencias_fase3.sh        # condición de carrera (≈ 10 min)
scripts/evidencias_fase4.sh        # corrección: antes/después, mecanismos, espera activa (≈ 15 min)
scripts/evidencias_fase5.sh        # interbloqueo y estrategias (≈ 12 min)
scripts/evidencias_fase6.sh        # CPU (GIL, hilos vs procesos) y memoria (≈ 5 min)
scripts/evidencias_fase7.sh        # registro en vivo, alerta sin progreso, contadores
scripts/evidencias_fase8.sh        # batería de 63 ejecuciones + gráficas (≈ 25 min; --solo-informe)
```
Hallazgos del desarrollo (problemas reales, corregidos y medidos):
```bash
python3 experimentos/h1_event_bloqueado.py [--corregido]   # H1: Event bloqueado por un proceso muerto
experimentos/h3_trabajador_caido.sh 10                     # H3: inanición con multiprocessing.Queue
experimentos/h4_barrera_abortada.sh despues 30             # H4: carrera Barrier.wait / abort
python3 experimentos/h6_contador_compartido.py             # H6: Value(lock=True) pierde incrementos
```

## Documentación
| Documento | Contenido |
|---|---|
| [docs/BITACORA_TECNICA.md](docs/BITACORA_TECNICA.md) | Bitácora por fases: diseño, decisiones, evidencias y cómo explicarlas, hallazgos, conclusiones |
| [docs/GUION_DEMOSTRACION.md](docs/GUION_DEMOSTRACION.md) | Guion de la demostración (10 min) paso a paso |
| [docs/PREGUNTAS_SUSTENTACION.md](docs/PREGUNTAS_SUSTENTACION.md) | Preguntas probables con respuestas, por criterio de evaluación |
| [evidencias/fase8/resumen.md](evidencias/fase8/resumen.md) | Tablas y gráficas de la comparación antes/después |
| [ROADMAP.md](ROADMAP.md) | Ruta de desarrollo por fases |

Cada fase quedó etiquetada en git (`fase-0` … `fase-9`): `git checkout fase-3` muestra el
proyecto tal como estaba al terminar esa fase.

## Estructura
```
main.py                      punto de entrada
despacho/
  centro.py                  proceso principal: crea, supervisa y cierra; estadísticas
  trabajador.py              proceso trabajador e hilos despachadores
  taller.py                  proceso taller e hilos inspectores
  generador.py               hilos productores (llegada simultánea con Barrier)
  cola.py                    ColaAcotada: productor-consumidor con semáforos
  flota.py                   vehículos compartidos: versión insegura y corregida
  recursos.py                locks de vehículos/andenes y estrategias de interbloqueo
  vigilante.py               detección de ciclos en el grafo de espera
  monitor.py                 estado en vivo y alerta sin progreso
  muestreador.py             CPU y memoria de cada proceso desde /proc
  contadores.py              contadores compartidos entre procesos
  carga.py                   ruta óptima (CPU) e historial de trazas (memoria)
  config.py, modelo.py, registro.py, so_utils.py
scripts/                     observación, demostración, verificación y evidencias por fase
experimentos/                hallazgos H1-H6, batería de la fase 8 y gráficas SVG
evidencias/faseN/            salidas reales de cada fase (fase8/graficas: gráficas SVG)
docs/                        bitácora técnica, guion de demostración, preguntas de sustentación
```
