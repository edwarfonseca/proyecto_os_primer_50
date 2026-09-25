# Sistema de despacho y logística — Proyecto 6

Proyecto práctico de **Sistemas Operativos** (UPTC, primer 50 %): simulación de un centro de
despacho de una empresa de transporte que usa **procesos, hilos, productor-consumidor,
sincronización, interbloqueos, CPU y memoria**, observados con herramientas del SO Linux.

> Estado: en desarrollo por fases. Ver [ROADMAP.md](ROADMAP.md).

## Documentación
- [ROADMAP.md](ROADMAP.md): ruta de desarrollo por fases.
- [docs/BITACORA_TECNICA.md](docs/BITACORA_TECNICA.md): bitácora técnica (diseño, decisiones,
  ejecución, evidencias y guía de sustentación por fase).
- `evidencias/`: salidas reales de `ps`, `pstree`, `top`, `/proc` y de las pruebas.

## Requisitos
- Linux
- Python 3.12+ (desarrollado con 3.14)

## Ejecución
```bash
python3 main.py --help
python3 main.py                    # 2 trabajadores x 3 hilos, 20 solicitudes
python3 main.py -w 2 -t 3 -g 4 -n 24 --tam-rafaga 2 -k 5   # ráfagas simultáneas, cola de 5
python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5        # generación continua hasta Ctrl+C
python3 main.py -v 3                                       # flota de 3 vehículos, versión corregida
python3 main.py -v 3 --modo inseguro --espera activa       # versión con la condición de carrera
python3 main.py --interbloqueo sin_orden                   # versión que se interbloquea
python3 main.py --interbloqueo deteccion                   # detección y recuperación
python3 main.py -p 9 -w 4 -t 1                             # CPU alta (rutas de 9 puntos) en 4 procesos
python3 main.py --traza-kb 256 --historial 0 -n 200       # memoria sin límite (como una fuga)
python3 main.py -n 40 --vista resumen                      # consola: sólo el estado cada segundo
```

## Observación con herramientas del SO
Con el sistema en ejecución, en otra terminal:
```bash
scripts/observar.sh                # pstree, ps, ps -eLf, /proc/<pid>/status, PSS
scripts/monitor_so.sh              # vista en vivo: procesos, hilos por estado, CPU, RSS
kill -USR1 $(pgrep -xo centro_despacho)   # volcado de la pila de todos los hilos
```

## Reproducir evidencias
```bash
scripts/evidencias_fase1.sh        # escenarios de procesos, señales, zombis y huérfanos
scripts/evidencias_fase2.sh        # ráfagas, hilos en el SO, escalamiento, capacidad de cola
scripts/evidencias_fase3.sh        # condición de carrera en la asignación de vehículos
scripts/evidencias_fase4.sh        # corrección: antes/después, mecanismos, espera activa
scripts/evidencias_fase5.sh        # interbloqueo: observación, estrategias, tiempo límite
scripts/evidencias_fase6.sh        # CPU (GIL, hilos vs procesos) y crecimiento de memoria
scripts/evidencias_fase7.sh        # registro en vivo, alerta sin progreso, contadores (H6)
python3 experimentos/h1_event_bloqueado.py [--corregido]
experimentos/h3_trabajador_caido.sh 10
experimentos/h4_barrera_abortada.sh despues 30
```

## Registros de cada ejecución
| Archivo | Contenido |
|---|---|
| `logs/<nombre>.log` | eventos con hora, PID, PPID, TID, proceso e hilo |
| `logs/<nombre>.estado.csv` | cada segundo: recibidas, en cola, en proceso, vehículos asignados/disponibles, finalizadas |
| `logs/<nombre>.recursos.csv` | cada 0.5 s y por proceso: estado, hilos, RSS, PSS, memoria privada, CPU |

## Estructura
```
main.py                  punto de entrada
despacho/                código del sistema (centro, trabajador, registro, utilidades del SO)
scripts/                 observación y reproducción de evidencias
experimentos/            experimentos aislados de hallazgos
evidencias/faseN/        salidas reales de cada fase
docs/                    bitácora técnica
```
