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
```

## Observación con herramientas del SO
Con el sistema en ejecución, en otra terminal:
```bash
scripts/observar.sh                # pstree, ps, ps -eLf, /proc/<pid>/status, PSS
kill -USR1 $(pgrep -xo centro_despacho)   # volcado de la pila de todos los hilos
```

## Reproducir evidencias
```bash
scripts/evidencias_fase1.sh        # escenarios de procesos, señales, zombis y huérfanos
scripts/evidencias_fase2.sh        # ráfagas, hilos en el SO, escalamiento, capacidad de cola
python3 experimentos/h1_event_bloqueado.py [--corregido]
experimentos/h3_trabajador_caido.sh 10
experimentos/h4_barrera_abortada.sh despues 30
```

## Estructura
```
main.py                  punto de entrada
despacho/                código del sistema (centro, trabajador, registro, utilidades del SO)
scripts/                 observación y reproducción de evidencias
experimentos/            experimentos aislados de hallazgos
evidencias/faseN/        salidas reales de cada fase
docs/                    bitácora técnica
```
