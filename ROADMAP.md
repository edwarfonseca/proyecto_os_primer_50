# Ruta de desarrollo — Proyecto 6: Sistema de despacho y logística

> Plan de trabajo por fases. Cada fase termina con: código funcionando, evidencia real
> del SO capturada en `evidencias/`, y su sección completada en
> [`docs/BITACORA_TECNICA.md`](docs/BITACORA_TECNICA.md).

## Principios para obtener la nota máxima

1. **Todo fenómeno debe poder activarse y desactivarse con un parámetro** (`--modo inseguro|seguro`,
   `--interbloqueo sin_orden|orden|timeout`). Así se conserva en un solo código la *versión
   funcional* y la *versión con el problema* (condición general del enunciado) y el antes/después
   se compara con los mismos datos de entrada.
2. **Reproducibilidad**: semilla (`--semilla`) para los tiempos aleatorios y ventanas de
   carrera controladas. Una condición de carrera que "a veces sale" no es evidencia.
3. **Detección automática, no visual**: el propio sistema cuenta asignaciones dobles e
   interbloqueos y lo imprime en el resumen final. El profesor ve un número, no una opinión.
4. **Trazabilidad SO**: cada línea del log lleva `PID`, `PPID`, `TID` (el mismo LWP que muestra
   `ps -eLf`) y nombre de hilo. Así se cruza el log con `ps`, `pstree`, `top -H` y `/proc`.
5. **Cada captura de pantalla va con explicación** del fenómeno observado (el enunciado rechaza
   capturas sin explicación).
6. **Control de versiones con git y etiquetas por fase** (`fase-1`, `fase-2`, …) para demostrar
   la evolución y poder volver a la versión con el problema (ver flujo abajo).

## Flujo de trabajo con Git / GitHub

Repositorio: <https://github.com/edwarfonseca/proyecto_os_primer_50>

- Rama principal `main`: siempre contiene una versión que ejecuta.
- Cada fase se desarrolla en una rama `fase-N-<tema>` y se integra a `main` al cerrarla.
- Commits pequeños con prefijo de fase, p. ej. `fase3: agrega asignación check-then-act sin lock`.
- Al cerrar una fase se crea la etiqueta `fase-N` (anotada). Con
  `git checkout fase-3` se puede volver a la versión exacta de esa fase en la sustentación.
- Cada cierre de fase incluye en el mismo commit: código, evidencias en `evidencias/faseN/`
  y la sección actualizada de la bitácora.

## Arquitectura objetivo (resumen)

```
Proceso principal: centro_despacho (PID P)
├── hilo generador-k  (productores: llegada simultánea de solicitudes, sincronizada con Barrier)
├── hilo monitor      (estadísticas periódicas + watchdog de interbloqueo)
├── Proceso trabajador-1 (PPID = P)
│   ├── hilo despachador-1-1  ┐ consumidores de la cola compartida
│   ├── hilo despachador-1-2  │ asignan vehículo, calculan ruta (CPU),
│   └── hilo despachador-1-T  ┘ despachan y registran entrega
├── Proceso trabajador-2 ...
└── Proceso trabajador-W ...

Recursos compartidos entre procesos (memoria compartida, multiprocessing):
  - cola_solicitudes : ColaAcotada(K) (semáforos + pipe) → productor-consumidor acotado
  - vehiculos        : multiprocessing.Array('i', V)       → 0 = libre, n = id de solicitud
  - contadores       : multiprocessing.Value / Array       → recibidas, pendientes, finalizadas...
  - andenes          : multiprocessing.Lock por andén      → segundo tipo de recurso (interbloqueo)
  - locks            : Lock / Semaphore(V)                 → corrección de la carrera
```

Justificación clave (para la sustentación): con GIL activo (`sys._is_gil_enabled() == True`
en este Python 3.14), los **hilos** sirven para concurrencia de E/S y esperas (despacho,
entrega simulados con `sleep`), pero **no** paralelizan cálculo. La tarea intensiva en CPU
(cálculo de ruta) escala sólo con **procesos**. Esto se demostrará con `top -H` y mediciones.

## Fases

| Fase | Objetivo | Requisitos cubiertos | Entregable de la fase |
|---|---|---|---|
| 0 | Diseño, estructura del repo, diagramas | 9.1 | Diagramas + decisiones en bitácora |
| 1 | Proceso principal + procesos trabajadores + ciclo de vida | 1, 2, 14 (parcial) | `pstree -p` con jerarquía |
| 2 | Hilos consumidores + cola productor-consumidor + llegada simultánea + tiempos | 3, 5, 6, 9 | `ps -eLf` con hilos nombrados |
| 3 | Estado compartido de vehículos + **condición de carrera** reproducible | 4, 7 | Log con doble asignación detectada |
| 4 | **Corrección** con sincronización (Lock + Semaphore) | 8, 15 (parcial) | Tabla antes/después |
| 5 | **Interbloqueo** (vehículo + andén en orden inverso) y estrategia de prevención | 10, 11 | `/proc/<pid>/task/*/wchan` = futex, análisis Coffman |
| 6 | Tarea intensiva en **CPU** + crecimiento controlado de **memoria** | 13, 9.4 | `top -H`, `/proc/<pid>/status` (VmRSS) |
| 7 | Registro y estadísticas + scripts de observación del SO | 12, 14 | `scripts/observar.sh` y CSV de estadísticas |
| 8 | Batería de experimentos (N solicitudes × modo) y comparación | 15, 9.3 | CSV + gráficas + tabla comparativa |
| 9 | README, guion de demostración, preguntas de sustentación | Entregables 1–9 | Proyecto listo para entregar |

### Fase 0 — Diseño y estructura
- [x] `git init`, `.gitignore`, estructura de carpetas, repositorio en GitHub.
- [x] Diagrama de arquitectura, jerarquía de procesos, identificación de hilos y recursos (Mermaid).
- [x] Identificación a priori de secciones críticas y posibles bloqueos.
- [x] Matriz de trazabilidad requisito → fase → evidencia.

### Fase 1 — Procesos ✅
- [x] `main.py` con CLI (`argparse`): `--trabajadores`, `--duracion`, `--metodo-inicio`, `--latido`, `--espera-fin`, `--log` (los demás parámetros se agregan en su fase).
- [x] Proceso principal crea W procesos trabajadores (`multiprocessing.Process`, método `fork` explícito: en Python 3.14 el defecto es `forkserver`).
- [x] Nombre del proceso visible en `ps` (escritura en `/proc/self/comm`).
- [x] Logger común: `timestamp | PID | PPID | TID | proceso | hilo | evento`.
- [x] Terminación ordenada: indicador de parada compartido + `SIGINT`/`SIGTERM`, escalamiento `SIGTERM → SIGKILL`, sin zombis, detección de huérfanos. (Los centinelas en la cola llegan en la Fase 2.)
- [x] Evidencia: E1–E5 con `pstree`, `ps`, `top -H`, `/proc` (`scripts/evidencias_fase1.sh`).
- [x] Hallazgos documentados: H1 (`multiprocessing.Event` bloqueado por la muerte de un participante) y H2 (huérfanos).

### Fase 2 — Hilos y productor-consumidor ✅
- [x] Hilos generadores (productores) en el proceso principal; `threading.Barrier` para llegada **simultánea** por ráfagas.
- [x] Cola acotada propia `ColaAcotada` (semáforos `vacios`/`llenos` + mutex sobre un pipe); `--cola mp` conserva `multiprocessing.Queue`.
- [x] T hilos despachadores por trabajador (consumidores) + cola de resultados hacia el principal.
- [x] Tiempos aleatorios reproducibles de despacho y entrega (`--semilla`).
- [x] Cierre por centinelas; cancelación contabilizada con Ctrl+C; balance verificado.
- [x] Estadísticas: espera, servicio, rendimiento, concurrencia, reparto, CPU (`getrusage`).
- [x] Evidencia: E1–E4 (`scripts/evidencias_fase2.sh`): ráfagas, `pstree -t`, `ps -L`, `top -H`, escalamiento, capacidad.
- [x] Hallazgos: H3 (inanición con `multiprocessing.Queue`, 4/10 → 0/10) y H4 (carrera `Barrier.wait`/`abort`, 13/30 → 0/30).

### Fase 3 — Condición de carrera (versión con el problema)
- [ ] Arreglo compartido de vehículos sin protección (`lock=False`).
- [ ] Asignación *check-then-act*: buscar libre → ventana → marcar ocupado (TOCTOU).
- [ ] Instrumentación: contador protegido de ocupantes por vehículo → detecta **doble asignación**.
- [ ] Prueba reproducible (misma semilla, varias repeticiones, % de ejecuciones con fallo).

### Fase 4 — Corrección
- [ ] `Lock` que hace atómica la búsqueda + marcado (sección crítica mínima).
- [ ] `Semaphore(V)` que cuenta vehículos libres: sin espera activa cuando no hay vehículos.
- [ ] Re-ejecución con la misma semilla: 0 dobles asignaciones; medición del costo (tiempo total, throughput).

### Fase 5 — Interbloqueo
- [ ] Recurso 2: andenes de carga. Operación *despacho*: vehículo → andén. Operación *retorno/mantenimiento*: andén → vehículo.
- [ ] Modo `sin_orden`: interbloqueo real; watchdog lo detecta (sin progreso durante X s) e imprime qué hilo tiene qué recurso.
- [ ] Evidencia: estado `S`, CPU 0 %, `wchan` = `futex_wait_queue`, `py-spy dump` (opcional).
- [ ] Análisis de las 4 condiciones de Coffman.
- [ ] Modo `orden`: orden global de adquisición (rompe espera circular). Modo `timeout`: `acquire(timeout)` + liberar y reintentar con *backoff* (rompe retención y espera). Comparación de ambos.

### Fase 6 — CPU y memoria
- [ ] Cálculo de ruta óptima (fuerza bruta sobre puntos de entrega) como tarea CPU-bound.
- [ ] Experimento GIL: 1 proceso × 8 hilos vs 4 procesos × 2 hilos → `top -H` y tiempos.
- [ ] Crecimiento controlado de memoria (historial/caché de rutas acotado) → `VmRSS` en `/proc`.

### Fase 7 — Registro y observación
- [ ] Hilo monitor: recibidas, pendientes, vehículos disponibles, asignados, finalizadas (cada segundo + CSV).
- [ ] `scripts/observar.sh <PID>`: captura ps, pstree, ps -eLf, top -H -b, /proc a `evidencias/`.

### Fase 8 — Experimentos
- [ ] `scripts/experimentos.sh`: N ∈ {10, 50, 100, 500}, modos inseguro/seguro, 5 repeticiones.
- [ ] Tablas y gráficas (tiempo, throughput, dobles asignaciones, CPU, RSS).

### Fase 9 — Cierre
- [ ] README con instalación y ejecución.
- [ ] Guion de demostración (5–10 min) y banco de preguntas de sustentación con respuestas.
- [ ] Revisión final contra la matriz de trazabilidad.
