# Banco de preguntas de sustentación — Proyecto 6

Organizado por los criterios de evaluación del enunciado. Cada respuesta es la versión corta
para decir en voz alta; la referencia indica dónde está la evidencia (F = fase, E = escenario de
evidencia, H = hallazgo, D = decisión de diseño; todo en `docs/BITACORA_TECNICA.md`).

## Diseño de la solución (10 %)

**¿Por qué procesos y además hilos?**
Procesos para el paralelismo real de CPU (cada uno tiene su propio GIL) y para el aislamiento
(la caída de un trabajador no corrompe a los demás). Hilos para las esperas (preparación, ruta,
vehículo), que son la mayor parte del trabajo: son baratos y comparten memoria. Medido: 16 hilos en
2–4 procesos logran el mejor tiempo con 2.9 veces menos memoria que 16 procesos. → F6-E3, F2-E3.

**¿Cuál es la jerarquía de procesos?**
`centro_despacho` → `trabajador-1..W` (hilos `despachador-w-t`) y `taller` (hilos `inspector-i`).
El principal tiene los hilos `generador-i`, `vigilante`, `monitor` y `muestreador`. Se reconstruye
con PID/PPID en `pstree -p -t`. → F9 (diseño final), F1-E1.

**¿Qué recursos se comparten y cómo se protege cada uno?**
Cola de solicitudes (semáforos `vacios`/`llenos` + mutex), flota de vehículos (mutex + semáforo
contador), vehículos y andenes físicos (un lock cada uno, adquiridos en orden global), contadores
del monitor (un lock por secuencia) e historial de trazas de cada proceso (`threading.Lock`). →
F9 (tabla de recursos).

**¿Por qué `fork` y no el método por defecto?**
En Python 3.14 el defecto en Linux es `forkserver`: los trabajadores quedarían como hijos de un
proceso servidor y no del principal, y se perdería la jerarquía PID/PPID. → F1 D1.1, F1-E4.

**¿Por qué crean los procesos antes que los hilos?**
`fork()` copia sólo el hilo que lo llama. Si otro hilo tuviera un lock tomado, el hijo lo
heredaría tomado y sin dueño. → F1 D1.2.

## Implementación (20 %)

**¿Cómo se implementa el productor-consumidor?**
Productores: hilos `generador-i`; consumidores: hilos `despachador-w-t` de todos los trabajadores;
búfer: `ColaAcotada`, la solución clásica con semáforos sobre un pipe:
`P(vacios); P(mutex); escribir; V(mutex); V(llenos)`. → F2 D2.3.

**¿Por qué no usaron `multiprocessing.Queue`?**
Su `get()` retiene el lock de lectores durante toda la espera. Si muere el proceso que lo tiene,
ningún consumidor vuelve a leer: inanición en 4 de 10 pruebas; con la cola propia, 0 de 10. → H3.

**¿Cómo se simula la llegada simultánea?**
Los generadores se esperan en una `threading.Barrier` y se liberan juntos: 8 solicitudes en menos
de 3 ms. → F2-E1.

**¿Cómo termina el sistema sin dejar procesos colgados?**
Cierre normal: un centinela por hilo despachador (llegan detrás de todas las solicitudes, porque la
cola es FIFO). Cierre anticipado (Ctrl+C): indicador compartido, las solicitudes en cola se cancelan
y se contabilizan. Si un proceso no responde: `SIGTERM` y luego `SIGKILL`. Se verifica que no quedan
zombis ni huérfanos. → F1 D1.4–D1.6, F2 D2.8.

**¿Qué pasa si el principal muere de golpe?**
El kernel re-asigna los hijos a `systemd --user` (subreaper); cada trabajador detecta el cambio de
PPID y termina. → H2, F1-E5.

**¿Qué pasa si muere un trabajador?**
El principal lo detecta con `waitpid` (evita el zombi), lo registra y el resto sigue. Con la cola
propia los demás consumidores no se ven afectados. → F1-E2, H3.

## Concurrencia y sincronización (20 %)

**¿Dónde está la condición de carrera?**
En asignar vehículo: `if estado[v] == 0` (check) … `estado[v] = id` (act) sin exclusión mutua. La
sección crítica es la secuencia completa, no cada acceso. → F3 3.2–3.3.

**¿Cómo demuestran que es reproducible?**
10 de 10 ejecuciones con la misma semilla fallan, y la cantidad varía (16–19): la carga es fija, el
intercalado lo decide el planificador. Dos detectores independientes coinciden en cada ejecución. →
F3-E2.

**¿La carrera ocurre sólo por el `sleep` de validación?**
No: sin ventana artificial falla en 3 de 10; con 6 procesos, en 10 de 10. La ventana sólo la hace
reproducible. → F3-E3, E4.

**Python tiene GIL, ¿no evita esto?**
No es sincronización: sólo impide que dos hilos del mismo proceso ejecuten bytecode a la vez. Cambia
de hilo cada ~5 ms o en cualquier operación bloqueante; entre procesos no existe. Con 1 ms de ventana
el peor caso fue "sólo hilos". → F3-E4, H6.

**¿Cómo lo corrigieron y por qué funciona?**
Un `Lock` hace indivisible buscar + marcar: quien llega segundo espera y, al entrar, ya ve el vehículo
marcado. Es un semáforo POSIX en memoria compartida: funciona entre hilos y entre procesos. →
F4 4.2–4.3.

**¿Para qué el semáforo contador si ya tienen el mutex?**
El mutex decide **cuál** vehículo; el semáforo, **cuántos** despachadores tienen vehículo, y bloquea
sin consumir CPU al que no consigue. Solo el semáforo sigue fallando en 8 de 10 ejecuciones; solo el
mutex obliga a sondear (2372 reintentos). → F4-E3.

**La versión corregida es más lenta, ¿es por el lock?**
No: el mutex cuesta 0.01 ms por asignación. La corregida opera en el máximo físico de la flota
(4.9 sol/s con 3 vehículos); la insegura rendía 8.5 sol/s porque ponía hasta 6 entregas en 3
vehículos. → F4-E1, F8 tabla 1.

**¿`Value(lock=True)` no es suficiente para un contador?**
No: protege la lectura y la escritura por separado, no la secuencia. Pierde el 62 % de los
incrementos con procesos y el 54 % con hilos. Se necesita `with v.get_lock(): v.value += 1`. → H6.

**¿Qué es una sección crítica fina y por qué importa?**
Contener sólo lo que necesita exclusión: reservar el vehículo dentro del mutex y validarlo fuera. Con
la validación adentro, la espera por el mutex sube 600 veces. → F4-E5.

## Interbloqueos (15 %)

**¿Cómo se produce el interbloqueo?**
Cargue: vehículo → andén (despachador). Inspección: andén → vehículo (proceso taller). Cada uno
retiene lo que el otro necesita. → F5 5.1–5.2.

**¿Cuáles son las condiciones de Coffman en su sistema?**
Exclusión mutua (un lock por recurso), retención y espera (retiene el vehículo mientras espera el
andén), no expropiación (nadie quita un lock ajeno) y espera circular (órdenes opuestos). → F5 5.3.

**¿Cómo saben que es interbloqueo y no lentitud?**
Ciclo en el grafo de espera + hilos en `futex_do_wait` con 0 CPU y 0 cambios de contexto en 2 s + 0
entregas nuevas. → F5-E1.

**¿Qué estrategias implementaron y cuál eligieron?**
`orden` (rompe la espera circular, por defecto: la más eficiente), `timeout` (rompe la retención y
espera) y `deteccion` (detecta el ciclo y expropia a una víctima). Las tres: 0 de 48 ejecuciones
bloqueadas. → F5-E3, F8 tabla 2.

**¿Qué diferencia hay entre prevención, evitación y detección?**
Prevención: romper una condición por diseño. Evitación: decidir cada asignación con información de
demandas futuras (banquero). Detección: dejar que ocurra y recuperarse. → F5 D5.5.

**¿Por qué no usaron el algoritmo del banquero?**
Exige conocer la demanda máxima de antemano y consultar un estado global en cada asignación. Aquí cada
operación necesita exactamente dos recursos conocidos, y el orden global lo resuelve sin ese costo. →
F5 D5.5.

**¿Qué es un livelock y cómo lo evitan?**
Hilos activos que reintentan sin avanzar. Espera aleatoria creciente antes de reintentar. Con un
límite de 0.01 s hubo 34 reintentos por falsas alarmas. → F5 D5.4, F5-E4.

**¿Qué pasa si un proceso muere con un recurso tomado?**
El lock queda tomado para siempre (los semáforos POSIX no registran dueño). Técnicamente otro proceso
podría liberarlo, pero no se hizo: el estado protegido podría haber quedado a medias; por eso los mutex
robustos avisan `EOWNERDEAD` en lugar de liberarse solos. → F5 D5.7.

## Procesos, hilos y recursos del SO (10 %)

**¿Qué es un zombi? ¿Y un huérfano?**
Zombi: proceso terminado cuyo padre aún no recogió su estado (`Z <defunct>`). Huérfano: proceso cuyo
padre murió; el kernel lo re-asigna. → F1-E2, F1-E5.

**¿Qué significan `S`, `R`, `T`, `Z` y `l` en `ps`?**
Dormido, ejecutándose o listo, detenido (`SIGSTOP`), zombi; `l` = multihilo. → Anexo B.

**¿Qué es `futex_do_wait`?**
El hilo duerme en el kernel esperando un futex, la base de los locks y semáforos de Linux: está
bloqueado en sincronización, no calculando. → F1 H1, F5-E1.

**¿Cómo prueban que dos procesos comparten memoria?**
El mismo inodo de `/dev/shm/pym-…` aparece mapeado en `/proc/<pid>/maps` de todos los procesos. →
F3-E5.

**¿Por qué la VSZ es tan grande con hilos?**
Cada hilo reserva 8 MB de pila y 64 MB de arena de `malloc`: espacio de direcciones reservado, no
memoria residente. → F2-E2.

**¿Por qué no se usan cambios de contexto de `/proc/<pid>/status` directamente?**
Son sólo los del hilo líder; hay que sumar `/proc/<pid>/task/*/status`. → F4 D4.6.

## CPU y memoria (10 %)

**¿Cuál es la tarea intensiva en CPU?**
La ruta óptima por fuerza bruta: P! recorridos por solicitud (9 puntos ≈ 220 ms). → F6.

**¿Por qué los hilos no aceleran el cálculo?**
El GIL: 8 hilos dan 0.98x; en `top -H` sólo un hilo está en `R`. → F6-E1, E2.

**¿Por qué 4 procesos dan 1.76x y no 4x?**
El equipo tiene 2 núcleos físicos con Hyper-Threading: la CPU total para el mismo trabajo se duplica
con 4 procesos, y el turbo baja la frecuencia. → F6-E1.

**¿Qué es un cambio de contexto involuntario?**
El kernel expropia a un proceso que quería seguir ejecutándose. Crece con más procesos que CPU (250 →
6 564). → F6-E1.

**¿Cómo simularon y controlaron el crecimiento de memoria?**
Historial de trazas GPS por proceso: sin límite crece linealmente (fuga); acotado se estabiliza.
Medido con RSS, PSS y memoria privada desde `/proc` cada 0.25 s. → F6-E4.

**RSS, PSS, VSZ, memoria privada: ¿cuál usar?**
VSZ = reservado; RSS = residente incluidas las páginas compartidas; PSS = reparte las compartidas (la
suma es real); `Private_Dirty` = lo escrito por el proceso (donde se ve una fuga). → F6 6.5.

## Evidencias (10 %)

**¿Las evidencias son de ejecuciones reales?**
Sí: cada archivo de `evidencias/` lo genera un script reproducible (`scripts/evidencias_faseN.sh`),
y la batería de la Fase 8 son 63 ejecuciones con sus datos crudos en `resultados.csv`.

**¿Cómo se relaciona cada síntoma con su causa y su corrección?**
Tabla 8.4 de la bitácora.

**¿Qué tan confiables son las mediciones?**
3 repeticiones por configuración en la batería y 10 a 30 en los fenómenos intermitentes; las
diferencias son de órdenes de magnitud frente a la dispersión. Amenazas declaradas: portátil con
turbo, tiempos simulados. → F8 D8.1, D8.4.

## Demostración gráfica (frontend)

**¿De dónde saca el frontend lo que muestra?**
De dos fuentes independientes: `/proc`, que el servidor lee como un observador externo (árbol de
procesos e hilos, estados, `wchan`, CPU y memoria), y los registros del propio programa (log, serie
del monitor y del muestreador). Cuando coinciden, la conclusión es firme. → F10 10.2.

**¿El frontend altera lo que se mide?**
No: ejecuta el mismo `main.py` con los mismos parámetros del guion; sólo muestrea más seguido.
Leer `/proc` no afecta a los procesos observados. → F10 10.7.

**¿Por qué los hilos que esperan el GIL aparecen como «espera lock/semáforo»?**
Porque el GIL es por dentro un lock sobre un futex: el SO los ve dormidos en `futex_do_wait`, y sólo
el que tiene el GIL está en `R`. → F10, captura 06.

**¿Qué pasa si el servidor recibe Ctrl+C con una ejecución en curso?**
Envía `SIGINT` al grupo del sistema (cierre ordenado) y, si no termina en 20 s, `SIGKILL`. →
F10 10.6 (H7).

## Sustentación (5 %)

**¿Qué aprendieron que no esperaban?**
Que las primitivas de sincronización pueden fallar por el comportamiento de sus participantes (un
proceso que muere reteniendo un lock: H1, H3), que un lock mal ubicado puede empeorar una carrera (H6),
que el GIL no protege y que una CPU lógica no es un núcleo físico.

**Si tuvieran que llevar esto a producción, ¿qué cambiarían?**
Mutex robustos o un supervisor que recupere recursos de procesos caídos; persistir el estado (la flota
vive en memoria); reemplazar la fuerza bruta por un algoritmo de rutas eficiente; Python sin GIL
(free-threaded) o procesos para la parte de CPU.
