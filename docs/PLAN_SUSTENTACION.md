      # Plan de sustentación en consola — 3 presentadores

Complementa a [`GUION_DEMOSTRACION.md`](GUION_DEMOSTRACION.md) (que explica *qué* mostrar en cada
paso) con el **reparto entre Edwar, Marlon y Juan**, los comandos exactos que teclea cada uno, la
relación de cada paso con los **comandos de Linux** y con los **requisitos del enunciado**.

Duración objetivo: **15 min** (≈ 5 min por persona). Al final hay una versión comprimida de 10 min.
La demostración completa sin pausas tarda **1 min 30 s**; el resto del tiempo es explicación.

---

## 1. Reparto

| Bloque | Responsable | Contenido | Comando único | Min |
|---|---|---|---|---|
| **A. Qué construimos y cómo se observa** | **Edwar** | Introducción + arquitectura · Paso 1 (procesos, hilos, señales) · Paso 6 (monitor, `SIGSTOP`/`SIGCONT`) | `scripts/demo.sh 1 6` | 5 |
| **B. Qué fallaba y cómo lo corregimos** | **Marlon** | Paso 2 (condición de carrera, antes/después) · Paso 3 (interbloqueo y 3 estrategias) | `scripts/demo.sh 2 3` | 5 |
| **C. Qué cuesta y cómo lo medimos** | **Juan** | Paso 4 (CPU: hilos vs. procesos y GIL) · Paso 5 (espera activa) · Paso 7 (memoria) + cierre | `scripts/demo.sh 4 5 7` | 5 |

**Regla de las dos manos:** quien expone conduce la **terminal 1** (el guion); **el siguiente en el
turno** conduce la **terminal 2** (comandos del SO en vivo: `pstree`, `ps -L`, `top -H`, `/proc`).
Así los tres están activos todo el tiempo y el relevo es natural: el que estaba en la terminal 2
pasa a la 1.

| Bloque | Terminal 1 (guion) | Terminal 2 (SO en vivo) |
|---|---|---|
| A | Edwar | Marlon |
| B | Marlon | Juan |
| C | Juan | Edwar |

**Criterios de evaluación que defiende cada uno** (si el profesor pregunta, responde el dueño del
tema; los demás sólo complementan):

| Criterio | % | Responde |
|---|---|---|
| Diseño de la solución | 10 | Edwar |
| Implementación | 20 | Edwar (arquitectura y módulos) |
| Concurrencia y sincronización | 20 | Marlon |
| Manejo de interbloqueos | 15 | Marlon |
| Procesos, hilos y recursos del SO | 10 | Edwar |
| Gestión de CPU y memoria | 10 | Juan |
| Evidencias y documentación | 10 | Juan |
| Sustentación | 5 | los tres |

Las respuestas preparadas están en [`PREGUNTAS_SUSTENTACION.md`](PREGUNTAS_SUSTENTACION.md),
dividido exactamente por esos títulos: **cada uno estudia sus secciones**.

---

## 2. Preparación

### El día anterior
- [ ] `scripts/verificar.sh` → debe terminar en **0 fallas** (≈ 50 s).
- [ ] `scripts/demo.sh --sin-pausa` completo (≈ 1 min 30 s): confirma que todo corre en el equipo.
- [ ] Cada uno ensaya **su** bloque con pausas: `scripts/demo.sh 1 6`, `scripts/demo.sh 2 3`,
      `scripts/demo.sh 4 5 7`. Dos pasadas: una leyendo, otra sin leer.
- [ ] Un ensayo general seguido con relevos y cronómetro.

### 15 minutos antes
- [ ] **Cerrar navegador, Spotify, VS Code y todo lo pesado**: los pasos 4 y 5 miden CPU y un
      proceso ajeno arruina los números.
- [ ] Terminal grande, fuente ≥ 14 pt, tema claro si se proyecta, ventana ancha (≥ 120 columnas:
      `ps -L` y `top -H` se cortan si es más angosta).
- [ ] Dos terminales abiertas en `~/Desktop/OS/proyecto_os` (una al lado de la otra, o dos pestañas).
- [ ] Prueba rápida: `python3 main.py -n 8 --vista resumen` → debe decir
      `FIN centro de despacho (correcto)`.
- [ ] Abrir de respaldo: `docs/BITACORA_TECNICA.md` (secciones 8.4 y 8.5) y la carpeta
      `evidencias/fase8/graficas/`.
- [ ] Limpiar la pantalla: `clear`.

> **Ojo:** cada llamada a `scripts/demo.sh` **borra `logs/demo/`** antes de empezar. Si quieren
> volver a un log de un bloque anterior, usen los de `evidencias/`, que no se tocan.

---

## 3. Bloque A — Edwar: procesos, hilos y observación

### A.0 Introducción (1 min, sin comandos)

> "El proyecto 6 pide un sistema de despacho de una empresa de transporte que presenta tres
> síntomas: dos solicitudes asignadas al mismo vehículo, despachos que quedan esperando para
> siempre y consumo de CPU elevado. Construimos el sistema en Python con procesos e hilos reales,
> **reprodujimos los tres síntomas**, los explicamos con conceptos del sistema operativo, los
> corregimos y medimos la diferencia con la misma carga y la misma semilla."

Mostrar el diagrama de arquitectura (README o bitácora 9.2) y decir la estructura en una frase:

> "Un proceso principal —el centro de despacho— crea dos procesos trabajadores y un proceso taller.
> Dentro de cada uno hay hilos: generadores que producen solicitudes, despachadores que las
> consumen, inspectores en el taller, y en el principal un vigilante de interbloqueos, un monitor y
> un muestreador. En total 4 procesos y 18 hilos. Todo lo comparten por memoria compartida en
> `/dev/shm` con semáforos POSIX."

### A.1 Paso 1 — Procesos e hilos (2 min)

```bash
scripts/demo.sh 1 6      # terminal 1; Enter avanza entre partes
```

| Pantalla | Qué señalar | Qué decir |
|---|---|---|
| `pstree -p -t <PID>` | 3 hijos colgando del principal; los hilos entre `{}` con su nombre | "Los procesos cuelgan del padre; los hilos son tareas dentro de un proceso y comparten su memoria. Los nombres son los nuestros: Python 3.14 copia el nombre del hilo al kernel, por eso `ps` los ve." |
| `ps -L -o pid,ppid,lwp,stat,wchan:20,comm` | `PPID` de los tres hijos = PID del principal; columna `LWP`; columna `WCHAN` | "`LWP` es el TID, el identificador del hilo en el kernel: es el mismo número que imprime nuestro log. `WCHAN` dice *dónde* duerme cada hilo: `futex_do_wait` es un lock o semáforo, `hrtimer_nanosleep` es un sleep." |
| `scripts/monitor_so.sh` | columnas HILOS, R/S/D, CPU%, RSS | "Es nuestra mini-`top`, leída de `/proc/<pid>/stat` y `/proc/<pid>/task/*/stat`. Casi todos los hilos están en `S`: el sistema es concurrente pero pasa el tiempo esperando, no quemando CPU." |
| Tras `kill -INT -- -<PGID>` | `sin zombis ni huérfanos`, `generadas=36 entregadas=24 canceladas=12 no atendidas=0` | "Ctrl+C va a todo el **grupo de procesos**, pero sólo el principal coordina el cierre: cancela la generación, espera a los hijos con `waitpid` y verifica en `/proc` que no quede ninguno. Sin zombis ni huérfanos." |

**Terminal 2 (Marlon), mientras el sistema del paso 1 está vivo** — elegir uno:
```bash
scripts/observar.sh                                  # pstree + ps + ps -eLf + /proc + /dev/shm
pstree -p -t $(pgrep -xo centro_despacho)
ps -eLf | head -1; ps -eLf | grep -E "despachador|generador"
```

**Requisitos que quedan demostrados:** 1 (proceso principal), 2 (trabajadores), 3 (múltiples
hilos), 5 (cola: líneas `PRODUCTOR BLOQUEADO` / `DESBLOQUEADO` cuando la cola de 10 se llena),
6 (llegada simultánea: `RÁFAGA n: 2 generadores liberados simultáneamente`), 14 (observación con
herramientas del SO) y el transversal 9.4.

### A.2 Paso 6 — Monitor en vivo y proceso detenido (1.5 min)

El mismo `scripts/demo.sh 1 6` continúa solo. Aparece una línea `ESTADO` por segundo.

| Momento | Qué señalar | Qué decir |
|---|---|---|
| Líneas `ESTADO` | `recibidas / en_cola / en_proceso / vehículos asignados con su solicitud / finalizadas` | "Éste es el requisito 12 en vivo: el registro que pide el enunciado. Además se guarda en `<log>.estado.csv`. La suma siempre cuadra: recibidas = en cola + en proceso + finalizadas." |
| `kill -STOP <2 trabajadores>` | los números se congelan | "`SIGSTOP` no se puede ignorar: el kernel saca los procesos de la cola de ejecución y quedan en estado `T`. Es como simular que el proceso se cayó o se colgó." |
| `SIN PROGRESO: 16 solicitudes pendientes … en 3 s` | la alerta | "El monitor no sabe *por qué* no avanza: detecta el síntoma —hay trabajo pendiente y nada finaliza—. El vigilante del bloque siguiente es el que sabe diagnosticar el interbloqueo." |
| `kill -CONT` | los contadores vuelven a subir | "`SIGCONT` lo revive y el sistema se recupera solo: no perdió ninguna solicitud." |

**Terminal 2 (Marlon), mientras están detenidos:**
```bash
ps -o pid,stat,comm -p $(pgrep -x trabajador-1),$(pgrep -x trabajador-2)   # STAT = T
kill -USR1 $(pgrep -x trabajador-1)    # vuelca la pila de todos sus hilos (faulthandler)
```

**Requisitos:** 12 (registro completo), 14. **Conceptos:** señales, estados de proceso, `waitpid`.

---

## 4. Bloque B — Marlon: concurrencia, sincronización e interbloqueos

```bash
scripts/demo.sh 2 3      # terminal 1
```

### B.1 Paso 2 — Condición de carrera (2 min)

Misma carga en las dos ejecuciones: 24 solicitudes, 6 despachadores, 3 vehículos, semilla 42.
Lo único que cambia es `--modo inseguro/seguro`.

**Antes (`--modo inseguro --espera activa`):**

| Qué señalar | Qué decir |
|---|---|
| `DOBLE ASIGNACIÓN: vehículo V2 asignado a la solicitud 20 mientras lo usa la solicitud 7 … [entre procesos]` | "La sección crítica es *buscar un vehículo libre* y *marcarlo como ocupado*: dos pasos separados sobre memoria compartida. Entre uno y otro el planificador puede expropiar el hilo, y otro ve el mismo vehículo todavía libre. Es un *check-then-act*." |
| `[entre procesos]` y `[mismo proceso]` | "Pasa entre hilos del mismo proceso **y** entre procesos distintos, porque el arreglo de la flota es un `RawArray` en `/dev/shm` que los cuatro procesos mapean: el mismo inodo, las mismas páginas físicas." |
| `entregas con vehículo a la vez: máx=6 con 3 vehículos` | "Ésta es la prueba de que el resultado es incorrecto: seis entregas en ruta con tres vehículos." |
| `REGISTROS INCONSISTENTES al liberar = 15` | "Actualizaciones perdidas: dos hilos escriben el mismo registro y una escritura desaparece." |
| `exit code: 1` | "El programa 'funciona' y termina bien; incluso *rinde más* (6.8 solicitudes/s) porque usa vehículos que no tiene. Por eso nuestra auditoría devuelve código de salida 1: sin instrumentación, este error pasa desapercibido." |

**Después (`--modo seguro --espera bloqueante`):**

| Qué señalar | Qué decir |
|---|---|
| `DOBLES ASIGNACIONES: sonda en vivo=0`, auditoría en 0 | "Un `Lock` (mutex) hace indivisible buscar-y-marcar: exclusión mutua sobre la sección crítica." |
| `entregas con vehículo a la vez: máx=3 con 3 vehículos` | "Y un `BoundedSemaphore(3)` cuenta los vehículos libres, así el hilo que no alcanza vehículo **se duerme** en vez de dar vueltas." |
| `espera por el mutex de la flota (ms): prom=0.00` | "El mutex cuesta centésimas de milisegundo: la sección crítica es fina, sólo cubre el arreglo. El tiempo extra frente a la versión insegura no es el costo de sincronizar, es el costo de **respetar** que sólo hay 3 vehículos." |

**Requisitos:** 4 (información compartida de vehículos), 7 (condición de carrera provocada),
8 (corrección con mecanismos de sincronización), 15 (comparación antes/después con la misma carga).

### B.2 Paso 3 — Interbloqueo (3 min)

**1) `--interbloqueo sin_orden` (se bloquea):**

| Qué señalar | Qué decir |
|---|---|
| `INTERBLOQUEO DETECTADO (ciclo en el grafo de espera): despachador-2-2 [tiene V2, espera A2] -> inspector-1 [tiene A2, espera V2] -> despachador-2-2` | "El cargue pide **vehículo y luego andén**; la inspección, en el proceso taller, pide **andén y luego vehículo**. Orden opuesto: espera circular." |
| las 4 condiciones | "Se cumplen las cuatro de Coffman: exclusión mutua (un andén, un ocupante), retención y espera (cada uno conserva el primer recurso mientras pide el segundo), no expropiación (nadie se lo puede quitar) y espera circular (el ciclo que ven en pantalla)." |
| `ps -L …`: los hilos del ciclo en `futex_do_wait`, `%CPU 0.0`, estado `Sl` | "Esto no es lentitud: están dormidos en un futex y el kernel **no los volverá a despertar nunca**, porque quien debe despertarlos espera a su vez. Consumen 0 % de CPU: un interbloqueo no se nota en `top`." |
| `no terminó en 3.0 s: se envía SIGTERM` | "Ni siquiera responden al cierre ordenado: hay que matarlos. Nuestro vigilante lo detectó tomando dos fotos del grafo de espera con 0.5 s de diferencia y buscando un ciclo." |

**2) `--interbloqueo orden`** → `INTERBLOQUEOS: detectados=0`, `FIN … (correcto)`.
> "**Prevención**: se rompe la espera circular imponiendo un orden global —todos piden primero
> vehículo y después andén, sin excepción—. Es la estrategia por defecto porque no cuesta nada en
> tiempo de ejecución."

**3) `--interbloqueo deteccion`** → `INTERBLOQUEO DETECTADO … / RECUPERACIÓN ordenada: víctima
inspector-1` y al final `detectados=2 | recuperaciones=2` con `FIN … (correcto)`.
> "**Detección y recuperación**: se deja ocurrir, el vigilante encuentra el ciclo y expropia a una
> víctima. Elegimos al inspector porque su trabajo es el más barato de repetir. También
> implementamos **`timeout`**, que es evasión: si un recurso no llega en 100 ms, se suelta todo y se
> reintenta. Medimos las tres con la misma carga: orden 5.17 s, timeout 5.31 s, detección 5.98 s."

**Terminal 2 (Juan), mientras está bloqueado:**
```bash
ps -L -o pid,lwp,stat,pcpu,wchan:22,comm -p $(pgrep -d, -P $(pgrep -xo centro_despacho))
cat /proc/$(pgrep -x taller)/task/*/comm
```

**Requisitos:** 10 (recursos tomados en orden distinto), 11 (estrategia de prevención/detección),
13 parcialmente. **Si el ciclo no se forma** (ocurre en ~8 de cada 10 ejecuciones) el script
reintenta 3 veces; si aun así no sale, decirlo con naturalidad —"es exactamente lo que hace difícil
un interbloqueo: es probabilístico"— y mostrar `evidencias/fase5/e1_observacion.txt`.

---

## 5. Bloque C — Juan: CPU, memoria y cierre

```bash
scripts/demo.sh 4 5 7    # terminal 1
```

### C.1 Paso 4 — Hilos frente a procesos y el GIL (1.5 min)

Carga puramente de CPU: 32 rutas de 9 puntos, ruta óptima por fuerza bruta (9! = 362 880
recorridos por solicitud), sin tiempos de espera simulados.

| Configuración | En `top -H` | Resultado |
|---|---|---|
| 1 proceso × 4 hilos | **un solo hilo en `R`**, los cuatro ~25 % | 7.40 s · `real/CPU = 3.19` |
| 4 procesos × 1 hilo | **los cuatro en `R`**, ~92 % cada uno | 3.90 s · `real/CPU = 1.05` |

> "`top -H` muestra hilos en vez de procesos. Con hilos, el GIL —un lock global del intérprete—
> deja ejecutar bytecode de Python a **un solo hilo a la vez**: cada ruta tarda 3.2 veces su tiempo
> de CPU porque pasa el resto esperando el GIL, que en `ps` aparece como `futex_do_wait`. Con
> procesos, cada uno tiene su propio intérprete y su propio GIL, y el `real/CPU` baja a 1.05: el
> paralelismo es real. No llega a 4× porque este equipo tiene **2 núcleos físicos con
> Hyper-Threading**: 4 CPU lógicas, pero 2 unidades de ejecución. La conclusión de diseño es la que
> ya aplicamos: hilos para lo que espera (E/S, locks) y procesos para lo que calcula."

### C.2 Paso 5 — Espera activa (1 min)

16 despachadores compiten por 2 vehículos; mismo trabajo, sólo cambia **cómo esperan**.

| | tiempo total | CPU de los trabajadores | cambios de contexto voluntarios |
|---|---|---|---|
| `--espera activa` | 7.01 s | **10.01 s (137.7 %)** | 1 680 505 |
| `--espera bloqueante` | 7.02 s | **0.15 s (2.1 %)** | 797 |

> "Es el tercer síntoma del enunciado: CPU elevada. **El mismo tiempo total y el mismo resultado**,
> pero la espera activa quema 67 veces más CPU preguntando '¿ya hay vehículo?' en un bucle, y
> provoca casi dos millones de cambios de contexto. Con el semáforo el hilo se bloquea en el
> kernel y sólo lo despierta quien libera un vehículo. En un servidor real esto es la diferencia
> entre un núcleo al 100 % sin hacer nada y un núcleo libre."

### C.3 Paso 7 — Memoria (1 min)

Cada entrega guarda una traza de 256 KB con el detalle de la ruta.

| Historial | RSS | PSS | Privada modificada |
|---|---|---|---|
| sin límite (`--historial 0`) | 35.4 MB | 23.0 MB | 18.8 MB |
| acotado (`--historial 20`) | 26.9 MB | 14.5 MB | 10.3 MB |

> "Sin límite el historial crece con cada entrega: es el patrón de una fuga de memoria —memoria
> que se retiene sin necesitarse—. Acotado, se descartan las trazas viejas y se estabiliza.
> Medimos con **RSS**, **PSS** y **memoria privada modificada** de `/proc/<pid>/smaps_rollup`, no
> con VSZ: VSZ es memoria virtual reservada que en gran parte nunca se toca. PSS reparte las
> páginas compartidas entre los procesos que las comparten, que es lo correcto después de un
> `fork`, donde padre e hijo comparten páginas con copia al escribir."

### C.4 Cierre (1.5 min)

Mostrar la tabla 8.4 de la bitácora o abrir `evidencias/fase8/graficas/g1_dobles_asignaciones.svg`.

> "Todo lo que mostramos está medido con una batería de **63 ejecuciones** automáticas, no con
> ejecuciones sueltas: 78 % de asignaciones en conflicto → 0; interbloqueo en 6 de 6 ejecuciones →
> 0 de 18 con cualquiera de las tres estrategias; 99 veces menos CPU al esperar. Además del
> enunciado, documentamos **siete problemas reales** que aparecieron durante el desarrollo —por
> ejemplo que `multiprocessing.Event.set()` se bloquea si muere un proceso que esperaba, o que
> `Value(lock=True)` pierde el 62 % de los incrementos si no se toma `get_lock()`— cada uno con su
> causa, su corrección y su medición antes y después. Todo está en la bitácora técnica y en
> `evidencias/`."

**Requisitos:** 13 (consumo elevado de CPU: dos causas distintas, espera activa y cálculo limitado
por el GIL), 15, punto 19 del informe (pruebas de CPU y memoria).

---

## 6. Los comandos de Linux, uno por uno

Esto es lo que el enunciado pide en el punto transversal 9.4. Tabla de bolsillo:

| Comando | Qué muestra | Concepto de SO que demuestra | Dónde aparece |
|---|---|---|---|
| `pstree -p -t <PID>` | árbol de procesos; hilos entre `{}` | jerarquía padre-hijo, hilos dentro del proceso | Paso 1 |
| `ps -o pid,ppid,pgid,stat,nlwp,rss,vsz,etime,comm` | identidad y recursos por proceso | PPID, grupo de procesos (destino de Ctrl+C), nº de hilos, residente vs. virtual | Paso 1, `observar.sh` |
| `ps -eLf` | **todos** los hilos del sistema | `LWP` = TID del kernel; un hilo es una tarea planificable | Paso 1, `observar.sh` |
| `ps -L -o …,stat,pcpu,wchan:22,comm` | estado, CPU y **canal de espera** de cada hilo | `futex_do_wait` = bloqueado en lock/semáforo · `hrtimer_nanosleep` = dormido por tiempo · `pipe_read` = E/S | Pasos 1 y 3 |
| `top -H -b -n 2 -p <PIDs>` | CPU y memoria **por hilo** | planificación: quién está en `R`; efecto del GIL | Paso 4 |
| `/proc/<pid>/status` | `State`, `PPid`, `Threads`, `VmRSS`, cambios de contexto | el kernel expone el proceso como archivos | `observar.sh`, resumen del log |
| `/proc/<pid>/task/<tid>/{comm,stat}` | nombre, estado y ticks de cada hilo | los hilos son tareas con su propia contabilidad | `monitor_so.sh` |
| `/proc/<pid>/smaps_rollup` | `Rss`, `Pss`, `Private_Dirty` | memoria compartida vs. privada tras `fork` | Paso 7 |
| `/proc/<pid>/maps` | segmentos mapeados | mismo **inodo** de `/dev/shm` en varios procesos = memoria compartida real | `observar.sh` |
| `ls /dev/shm` | `pym-*` (RawArray/RawValue), `sem.*` (semáforos POSIX) | objetos IPC con nombre | terminal 2 |
| `kill -INT -- -<PGID>` | Ctrl+C a todo el grupo | señales y grupos de procesos | Paso 1 |
| `kill -STOP` / `-CONT` | congelar y reanudar (estado `T`) | señales no ignorables, estados de proceso | Paso 6 |
| `kill -TERM` / `-KILL` | cierre ordenado vs. forzado | manejadores de señal; `SIGKILL` no se puede atrapar | Paso 3, Fase 1 |
| `kill -USR1 <PID>` | vuelca la pila de todos los hilos | señal definida por el usuario + `faulthandler` | a pedido |
| `pgrep -xo centro_despacho`, `pgrep -P <PID>` | buscar el principal y sus hijos por nombre | nombres de proceso en el kernel (`comm`) | todos |
| `getconf CLK_TCK` | ticks por segundo (100) | cómo se convierte `utime`/`stime` a segundos | `monitor_so.sh` |

**Estados (`STAT`)**: `R` ejecutando o listo · `S` dormido interrumpible · `D` dormido no
interrumpible (E/S de disco) · `T` detenido por `SIGSTOP` · `Z` zombi (terminó, el padre no ha
hecho `waitpid`). Modificadores: `l` multihilo · `s` líder de sesión · `+` primer plano.

**Los dos scripts propios son sólo envoltorios de esos comandos**, y conviene decirlo:
`scripts/observar.sh` = foto completa (pstree + ps + `ps -eLf` + `/proc` + `/dev/shm`);
`scripts/monitor_so.sh` = vista en vivo calculada a mano desde `/proc/<pid>/stat`.

---

## 7. Los 15 requisitos, dónde se ven y quién los explica

| # | Requisito | Se ve en | Responsable |
|---|---|---|---|
| 1 | Proceso principal administrador | Paso 1 (`pstree`, `INICIO centro de despacho`) | Edwar |
| 2 | Procesos trabajadores | Paso 1 (`CREADO trabajador-N -> PID`) | Edwar |
| 3 | Múltiples hilos por proceso | Paso 1 (`pstree -t`, `ps -eLf`) | Edwar |
| 4 | Información compartida de vehículos | Paso 2 (dobles `[entre procesos]`), `/proc/<pid>/maps` | Marlon |
| 5 | Cola productor-consumidor acotada | Paso 1 (`en cola ~N`, `PRODUCTOR BLOQUEADO/DESBLOQUEADO`) | Edwar |
| 6 | Llegada simultánea de solicitudes | Paso 1 (`RÁFAGA n: 2 generadores liberados simultáneamente`) | Edwar |
| 7 | Condición de carrera en la asignación | Paso 2 antes (`DOBLE ASIGNACIÓN`, `máx=6 con 3 vehículos`) | Marlon |
| 8 | Corrección con sincronización | Paso 2 después (mutex + semáforo, 0 dobles) | Marlon |
| 9 | Tiempos de despacho y entrega | `--despacho`, `--entrega`, `-s` (semilla) en cualquier ejecución | Marlon |
| 10 | Recursos pedidos en orden distinto | Paso 3 (`sin_orden`, ciclo vehículo↔andén) | Marlon |
| 11 | Estrategia contra interbloqueos | Paso 3 (`orden`, `timeout`, `deteccion`) | Marlon |
| 12 | Registro: recibidas, pendientes, vehículos, finalizadas | Paso 6 (líneas `ESTADO`, `.estado.csv`) | Edwar |
| 13 | Consumo elevado de CPU | Pasos 4 y 5 (GIL y espera activa) | Juan |
| 14 | Observación con herramientas del SO | Pasos 1, 3, 4 + `observar.sh` | Edwar |
| 15 | Comparación antes/después | Pasos 2, 5, 7 + batería de 63 ejecuciones (Fase 8) | Juan |

| Transversal | Se ve en | Responsable |
|---|---|---|
| 9.1 Diseño | introducción + diagrama (bitácora 9.2) | Edwar |
| 9.2 Implementación | los 7 pasos + `scripts/verificar.sh` (15/15) | Edwar |
| 9.3 Fallo y corrección en 8 pasos | Pasos 2 y 3 (y los hallazgos H1–H7) | Marlon |
| 9.4 Evidencias del SO | tabla de la sección 6 de este plan | Juan |

---

## 8. Reparto de preguntas

Si preguntan algo del tema de otro, **responde el dueño del tema**; nadie interrumpe. Si nadie lo
sabe: "no lo medimos, pero se puede comprobar con …" y decir el comando. Nunca inventar un número.

| Tema de la pregunta | Responde | Preparación |
|---|---|---|
| arquitectura, por qué procesos y no sólo hilos, `fork` vs. `forkserver`, señales, zombis, huérfanos, cola acotada | Edwar | PREGUNTAS §Diseño, §Implementación, §Procesos/hilos |
| mutex vs. semáforo, sección crítica, por qué falla el *check-then-act*, Coffman, las 4 estrategias, inanición | Marlon | PREGUNTAS §Concurrencia, §Interbloqueos |
| GIL, Hyper-Threading, RSS/PSS/VSZ, espera activa, cambios de contexto, cómo se midió | Juan | PREGUNTAS §CPU y memoria, §Evidencias |

Tres preguntas casi seguras y quién las toma:
- *"¿Por qué la versión insegura es más rápida?"* → **Marlon**: "porque usa vehículos que no tiene;
  rendir más con un resultado incorrecto no es rendir".
- *"¿Cómo saben que no hay interbloqueo, y no que simplemente es lento?"* → **Marlon**: "0 % de CPU
  y `futex_do_wait` permanente, más el ciclo en el grafo de espera del vigilante".
- *"¿Por qué con hilos no va 4 veces más rápido?"* → **Juan**: "el GIL, y además 2 núcleos físicos".

---

## 9. Si algo sale mal

| Situación | Qué hacer |
|---|---|
| El interbloqueo no se forma | El script reintenta 3 veces. Si no sale: decir que es probabilístico (~8 de 10) y mostrar `evidencias/fase5/e1_observacion.txt` |
| Quedó un proceso vivo de un intento anterior | `pkill -x centro_despacho` y verificar con `pgrep -x centro_despacho` (sin salida) |
| La terminal quedó sucia o con colores raros | `reset` o `clear` |
| Los números de CPU salen raros | Hay algo pesado abierto; cerrarlo y repetir sólo ese paso: `scripts/demo.sh 4` |
| Se acaba el tiempo | Saltar el paso 7 (memoria) y el `deteccion` del paso 3; nunca saltar los pasos 2 y 3 |
| Falla todo el equipo | Plan B: la misma demostración en el navegador, `python3 web/servidor.py --abrir`; plan C: las evidencias ya capturadas en `evidencias/` |
| Piden ver el código de una corrección | `despacho/flota.py` (mutex + semáforo), `despacho/recursos.py` (orden global), `despacho/vigilante.py` (grafo de espera) |

---

## 10. Versión comprimida de 10 minutos

| Min | Quién | Qué |
|---|---|---|
| 0–1 | Edwar | Introducción y arquitectura |
| 1–3 | Edwar | `scripts/demo.sh 1` (procesos, hilos, cierre sin zombis) |
| 3–5 | Marlon | `scripts/demo.sh 2` (carrera antes/después) |
| 5–7.5 | Marlon | `scripts/demo.sh 3` (interbloqueo + orden global; omitir `deteccion` si aprieta) |
| 7.5–9 | Juan | `scripts/demo.sh 4 5` (GIL y espera activa) |
| 9–10 | Juan | Cierre con la tabla antes/después |

Se omiten los pasos 6 (monitor) y 7 (memoria); se mencionan en una frase y se ofrecen si preguntan:
`scripts/demo.sh 6` y `scripts/demo.sh 7`.

---

## Anexo. La misma demostración sin `scripts/demo.sh`

Por si el profesor pide teclear los comandos a mano.

```bash
# --- Procesos e hilos (terminal 1) ---
python3 main.py -n 0 --tam-rafaga 3 --intervalo 0.5

# --- (terminal 2) ---
P=$(pgrep -xo centro_despacho)
pstree -p -t $P
ps -L -o pid,ppid,lwp,stat,pcpu,wchan:22,comm -p $P,$(pgrep -d, -P $P)
scripts/observar.sh
scripts/monitor_so.sh 1 5
kill -STOP $(pgrep -x trabajador-1); sleep 4; kill -CONT $(pgrep -x trabajador-1)
# Ctrl+C en la terminal 1 para el cierre ordenado

# --- Condición de carrera: antes y después (misma carga y semilla) ---
python3 main.py -n 24 -g 4 -v 3 --modo inseguro --espera activa    -i 0 -a 100 -p 0 --traza-kb 0 --vista resumen; echo "salida=$?"
python3 main.py -n 24 -g 4 -v 3 --modo seguro   --espera bloqueante -i 0 -a 100 -p 0 --traza-kb 0 --vista resumen; echo "salida=$?"

# --- Interbloqueo ---
python3 main.py -n 24 -g 4 -v 3 -a 2 -i 1 -p 0 --interbloqueo sin_orden --espera-fin 3 --vista resumen
python3 main.py -n 24 -g 4 -v 3 -a 2 -i 1 -p 0 --interbloqueo orden     --vista resumen
python3 main.py -n 12 -g 4 -v 3 -a 1 -i 2 -p 0 --interbloqueo deteccion --vista resumen

# --- CPU: hilos frente a procesos ---
C="-n 32 -g 4 -k 32 -p 9 --despacho 0-0 --entrega 0-0 -v 100 -a 100 -i 0 --traza-kb 0 --ventana 0"
python3 main.py -w 1 -t 4 $C --vista resumen     # y en otra terminal: top -H -p $(pgrep -d, -f main.py)
python3 main.py -w 4 -t 1 $C --vista resumen

# --- Espera activa ---
C="-w 4 -t 4 -g 4 -n 24 -k 24 -v 2 --ventana 0 -i 0 -a 100 -p 0 --traza-kb 0"
python3 main.py $C --espera activa --reintento 0 --vista resumen
python3 main.py $C --espera bloqueante --vista resumen

# --- Memoria ---
C="-n 120 --tam-rafaga 10 --intervalo 0.2 -k 40 --despacho 0.01-0.02 --entrega 0.02-0.05 --traza-kb 256 -v 100 -a 100 -i 0 -p 0 --ventana 0"
python3 main.py $C --historial 0  --vista resumen
python3 main.py $C --historial 20 --vista resumen
```
