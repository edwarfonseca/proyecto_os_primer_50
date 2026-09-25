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
python3 main.py -w 3 -d 5          # 3 procesos trabajadores durante 5 s
python3 main.py -w 3 -d 0          # hasta Ctrl+C
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
python3 experimentos/h1_event_bloqueado.py [--corregido]
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
