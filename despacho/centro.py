"""Proceso principal: centro de despacho que crea y administra los trabajadores."""

import multiprocessing as mp
import os
import queue
import resource
import signal
import statistics
import time
from collections import Counter, defaultdict

from . import registro, so_utils
from .cola import ColaAcotada
from .config import Config
from .flota import Flota
from .generador import crear_generadores
from .modelo import CANCELADA, ENTREGADA, Resultado
from .recursos import Recursos
from .taller import proceso_taller
from .trabajador import proceso_trabajador
from .vigilante import Vigilante


class CentroDespacho:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.trabajadores: list[mp.Process] = []
        self.taller: mp.Process | None = None
        self.vigilante: Vigilante | None = None
        self.generadores = []
        self.resultados_recibidos: list[Resultado] = []
        self._senal: int | None = None
        self._caidos: set[int] = set()
        self._plazo_cierre: float | None = None
        self.detener_anticipado = False     # parada por señal, duración o error

    def ejecutar(self) -> int:
        so_utils.nombrar_proceso("centro_despacho")
        mp.current_process().name = "centro_despacho"
        self.log = registro.configurar(self.cfg.ruta_log)
        c = self.cfg
        self.log.info("INICIO centro de despacho | método=%s | trabajadores=%d x %d hilos | "
                      "generadores=%d | solicitudes=%s | cola=%s(%d) | vehículos=%d | "
                      "modo=%s | espera=%s | sección=%s | ventana=%.4f s | andenes=%d | "
                      "inspectores=%d | interbloqueo=%s | semilla=%d | log=%s",
                      c.metodo_inicio, c.trabajadores, c.hilos, c.generadores,
                      c.solicitudes or "continuo", c.tipo_cola, c.capacidad_cola, c.vehiculos,
                      c.modo, c.espera, c.seccion, c.ventana, c.andenes, c.inspectores,
                      c.interbloqueo, c.semilla, c.ruta_log)

        so_utils.habilitar_volcado_hilos()
        ctx = mp.get_context(c.metodo_inicio)
        # Indicador de parada: un byte en memoria compartida sin lock. Sólo el principal
        # escribe y la escritura de un byte es atómica. No se usa multiprocessing.Event
        # porque su set() espera la confirmación de cada proceso que duerme en wait():
        # si uno muere (p. ej. SIGKILL) el principal queda bloqueado para siempre
        # (ver hallazgo H1 en la bitácora).
        self.detener = ctx.RawValue("b", 0)
        # Semáforo de arranque: cada trabajador hace release() al estar listo. Cada
        # operación es un único sem_post/sem_wait, así que la muerte de un trabajador
        # no deja el semáforo inconsistente.
        listos = ctx.Semaphore(0)
        # Cola acotada productor-consumidor compartida por todos los despachadores.
        # "semaforos": implementación propia (vacíos/llenos/mutex, ver cola.py).
        # "mp": multiprocessing.Queue, que retiene su lock de lectores mientras espera
        # (se conserva para reproducir el hallazgo H3).
        if c.tipo_cola == "semaforos":
            self.cola = ColaAcotada(ctx, c.capacidad_cola)
        else:
            self.cola = ctx.Queue(maxsize=c.capacidad_cola)
        # Cola de resultados (sin límite): trabajadores -> principal.
        self.resultados = ctx.Queue()
        # Flota compartida: se crea antes del fork para que todos los procesos hereden el
        # mismo segmento de memoria compartida (/dev/shm) mapeado en su espacio de direcciones.
        self.flota = Flota(ctx, c)
        # Locks de vehículos en el patio y de andenes, con el registro para el grafo de espera.
        self.recursos = Recursos(ctx, c)

        # Los procesos se crean ANTES de lanzar cualquier hilo en el principal: hacer
        # fork() de un proceso con varios hilos sólo copia el hilo que llama y puede
        # dejar locks tomados por hilos que no existen en el hijo.
        self._crear_trabajadores(ctx, listos)
        self._instalar_senales()
        self._esperar_arranque(listos)

        self.t_inicio = time.monotonic()
        try:
            self.vigilante = Vigilante(self.recursos, self._pid_de_slot, self.log)
            self.vigilante.start()
            self.generadores = crear_generadores(c, self.cola, self.detener, self.log)
            for g in self.generadores:
                g.start()
            self._registrar_jerarquia()
            self._operar()
        except Exception:
            # Un error inesperado en el principal no debe dejar trabajadores sin control:
            # se registra y se ejecuta el mismo cierre ordenado.
            self.log.exception("ERROR en el principal: se inicia el cierre")
            self.detener.value = 1
            self.detener_anticipado = True
        return self._finalizar()

    # -- creación -----------------------------------------------------------------

    def _crear_trabajadores(self, ctx, listos) -> None:
        # Se ignora SIGINT mientras se crean los hijos: con fork heredan esa disposición
        # y quedan protegidos desde el primer instante (sin ventana de carrera).
        previo = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            for i in range(1, self.cfg.trabajadores + 1):
                p = ctx.Process(target=proceso_trabajador, name=f"trabajador-{i}",
                                args=(i, self.detener, listos, self.cola, self.resultados,
                                      self.flota, self.recursos, self.cfg))
                p.start()
                self.trabajadores.append(p)
                self.log.info("CREADO %s -> PID %d", p.name, p.pid)
            if self.cfg.inspectores:
                self.taller = ctx.Process(target=proceso_taller, name="taller",
                                          args=(self.detener, listos, self.recursos, self.cfg))
                self.taller.start()
                self.log.info("CREADO taller -> PID %d", self.taller.pid)
        finally:
            signal.signal(signal.SIGINT, previo)

    def _instalar_senales(self) -> None:
        # El manejador sólo anota la señal. Coordinar el cierre (tomar locks, escribir
        # en el log) desde un manejador puede interbloquear al hilo principal consigo
        # mismo si la señal llega mientras ese hilo ya tiene el lock; el cierre se hace
        # luego desde el flujo normal en _operar().
        def manejador(signum, _frame):
            self._senal = signum
        signal.signal(signal.SIGINT, manejador)
        signal.signal(signal.SIGTERM, manejador)

    def _esperar_arranque(self, listos) -> None:
        esperados = len(self._hijos())
        limite = time.monotonic() + 10
        for n in range(esperados):
            if not listos.acquire(timeout=max(0.0, limite - time.monotonic())):
                self.log.error("ARRANQUE incompleto: sólo %d de %d procesos hijos listos",
                               n, esperados)
                return
        self.log.info("SINCRONIZADO: %d procesos hijos listos", esperados)

    def _hijos(self) -> list:
        return self.trabajadores + ([self.taller] if self.taller else [])

    def _pid_de_slot(self, slot: int) -> int:
        if slot < self.recursos.n_despachadores:
            return self.trabajadores[slot // self.cfg.hilos].pid
        return self.taller.pid

    # -- observación y supervisión -----------------------------------------------

    def _registrar_jerarquia(self) -> None:
        self.log.info("JERARQUÍA de procesos e hilos (leída de /proc):")
        self.log.info("  %-7s %-7s %-16s %-6s %-6s %-9s", "PID", "PPID", "NOMBRE",
                      "ESTADO", "HILOS", "RSS(kB)")
        for pid in [os.getpid()] + [p.pid for p in self._hijos()]:
            i = so_utils.info_proceso(pid)
            if not i:
                continue
            self.log.info("  %-7d %-7d %-16s %-6s %-6d %-9d", i["pid"], i["ppid"],
                          i["nombre"], i["estado"][0], i["hilos"], i["rss_kb"])
            for h in so_utils.hilos_proceso(pid):
                self.log.info("      └ TID %-7d %-16s %s", h["tid"], h["nombre"], h["estado"])

    def _operar(self) -> None:
        """Bucle del principal: recoge resultados, envía centinelas y vigila procesos."""
        c = self.cfg
        fin = self.t_inicio + c.duracion if c.duracion > 0 else None
        centinelas = None                       # None = aún no toca enviarlos
        while True:
            self._recoger_resultados(timeout=0.2)

            if self._senal is not None and not self.detener.value:
                self._abortar(f"SEÑAL {signal.Signals(self._senal).name} recibida")
            if self.vigilante.aborto_solicitado and not self.detener.value:
                self._abortar("INTERBLOQUEO sin recuperación posible")
            if fin is not None and time.monotonic() >= fin and not self.detener.value:
                self._abortar(f"DURACIÓN máxima cumplida ({c.duracion:.1f} s)")

            if centinelas is None and not any(g.is_alive() for g in self.generadores):
                centinelas = 0 if self.detener.value else c.trabajadores * c.hilos
                if centinelas:
                    self.log.info("GENERACIÓN terminada: se envían %d centinelas "
                                  "(uno por hilo despachador)", centinelas)
            if centinelas:
                centinelas = self._enviar_centinelas(centinelas)

            if not self._vigilar_trabajadores():
                break
            if self._plazo_cierre is not None and time.monotonic() >= self._plazo_cierre:
                self.log.warning("PLAZO de cierre vencido con trabajadores activos")
                break

    def _abortar(self, motivo: str) -> None:
        self.log.info("%s: se detiene la generación y se cancelan las solicitudes en cola",
                      motivo)
        self.detener.value = 1
        self.detener_anticipado = True
        self._plazo_cierre = time.monotonic() + self.cfg.espera_fin

    def _enviar_centinelas(self, pendientes: int) -> int:
        """Encola centinelas (None) sin bloquear al principal; devuelve los que faltan."""
        while pendientes:
            try:
                self.cola.put_nowait(None)
            except queue.Full:
                break
            pendientes -= 1
        return pendientes

    def _recoger_resultados(self, timeout: float) -> None:
        # El principal es el único lector de `resultados`. Debe vaciarla continuamente:
        # un proceso que escribió en una Queue no puede terminar hasta que su hilo
        # alimentador (QueueFeederThread) entregue todo al pipe, y si el pipe se llena
        # porque nadie lee, el trabajador quedaría bloqueado al salir.
        try:
            r = self.resultados.get(timeout=timeout)
        except queue.Empty:
            return
        while True:
            self.resultados_recibidos.append(r)
            try:
                r = self.resultados.get_nowait()
            except queue.Empty:
                return

    def _vigilar_trabajadores(self) -> bool:
        """Detecta trabajadores que terminaron inesperadamente. Devuelve si queda alguno."""
        vivos = 0
        for p in self._hijos():
            # is_alive() hace waitpid(WNOHANG): si el hijo terminó, lo recoge y así no
            # queda como zombi (estado Z) en la tabla de procesos.
            if p.is_alive():
                vivos += p is not self.taller      # el taller no atiende solicitudes
            elif p.pid not in self._caidos:
                self._caidos.add(p.pid)
                nivel = self.log.info if p.exitcode == 0 else self.log.warning
                nivel("%s %s (PID %d): %s", "TERMINÓ" if p.exitcode == 0 else "CAÍDO",
                      p.name, p.pid, so_utils.describir_salida(p.exitcode))
        return vivos > 0

    # -- cierre ---------------------------------------------------------------------

    def _esperar_proceso(self, p, segundos: float) -> None:
        """join() con plazo que sigue vaciando la cola de resultados mientras espera."""
        limite = time.monotonic() + segundos
        while p.is_alive() and time.monotonic() < limite:
            self._recoger_resultados(timeout=0.05)

    def _finalizar(self) -> int:
        self.detener.value = 1
        if self.vigilante:
            self.vigilante.fin.set()
            self.vigilante.join(timeout=2)
        for p in self._hijos():
            self._esperar_proceso(p, self.cfg.espera_fin)
            if p.is_alive():
                self.log.warning("%s (PID %d) no terminó en %.1f s: se envía SIGTERM",
                                 p.name, p.pid, self.cfg.espera_fin)
                p.terminate()
                self._esperar_proceso(p, self.cfg.espera_fin)
            if p.is_alive():
                # Un proceso detenido (estado T) deja SIGTERM pendiente y no lo atiende;
                # SIGKILL no se puede capturar ni ignorar y el kernel lo aplica siempre.
                self.log.warning("%s (PID %d) ignoró SIGTERM (estado %s): se envía SIGKILL",
                                 p.name, p.pid,
                                 (so_utils.info_proceso(p.pid) or {}).get("estado", "?"))
                p.kill()
                p.join()
        for g in self.generadores:
            g.join(timeout=self.cfg.espera_fin)
        self._recoger_resultados(timeout=0.05)

        self.log.info("RESUMEN de terminación:")
        for p in self._hijos():
            self.log.info("  %-14s PID %-7d %s", p.name, p.pid,
                          so_utils.describir_salida(p.exitcode))
        huerfanos = [p.pid for p in self._hijos() if so_utils.info_proceso(p.pid)]
        self.log.info("VERIFICACIÓN: procesos hijos que siguen en /proc: %s",
                      huerfanos or "ninguno (sin zombis ni huérfanos)")
        cuadra = self._estadisticas()

        exito = all(p.exitcode == 0 for p in self._hijos()) and cuadra
        self.log.info("FIN centro de despacho (%s)", "correcto" if exito else "con fallos")
        return 0 if exito else 1

    def _estadisticas(self) -> bool:
        """Registra las métricas de la ejecución. Devuelve si el balance cuadra."""
        rs = self.resultados_recibidos
        entregadas = [r for r in rs if r.estado == ENTREGADA]
        canceladas = sum(1 for r in rs if r.estado == CANCELADA)
        generadas = sum(g.generadas for g in self.generadores)
        perdidas = generadas - len(entregadas) - canceladas
        L = self.log

        L.info("ESTADÍSTICAS:")
        L.info("  solicitudes: generadas=%d entregadas=%d canceladas=%d no atendidas=%d",
               generadas, len(entregadas), canceladas, perdidas)
        L.info("  productores: bloqueos por cola llena=%d, tiempo bloqueados=%.3f s",
               sum(g.bloqueos for g in self.generadores),
               sum(g.t_bloqueado for g in self.generadores))
        if entregadas:
            esperas = [(r.t_inicio - r.t_llegada) * 1000 for r in entregadas]
            # Servicio = uso del vehículo (desde que se asignó hasta la entrega); la espera
            # por un vehículo libre se reporta aparte en las métricas de la flota.
            servicios = [r.t_fin - r.t_asignado for r in entregadas]
            inicio = min(r.t_llegada for r in entregadas)
            makespan = max(r.t_fin for r in entregadas) - inicio
            L.info("  espera en cola (ms): mín=%.0f prom=%.0f máx=%.0f",
                   min(esperas), statistics.fmean(esperas), max(esperas))
            L.info("  servicio con vehículo (s): prom=%.3f | trabajo total (suma)=%.2f s",
                   statistics.fmean(servicios), sum(servicios))
            L.info("  tiempo total=%.2f s | rendimiento=%.2f solicitudes/s | "
                   "concurrencia efectiva (trabajo/tiempo)=%.2f",
                   makespan, len(entregadas) / makespan, sum(servicios) / makespan)
            L.info("  hilos ocupados a la vez: máx=%d (capacidad = %d trabajadores x %d hilos"
                   " = %d)", self._concurrencia_maxima(entregadas, "t_inicio", "t_fin"),
                   self.cfg.trabajadores, self.cfg.hilos,
                   self.cfg.trabajadores * self.cfg.hilos)
            por_trab = Counter(r.trabajador for r in entregadas)
            por_hilo = Counter(r.hilo for r in entregadas)
            L.info("  reparto por trabajador: %s",
                   ", ".join(f"trabajador-{k}={v}" for k, v in sorted(por_trab.items())))
            L.info("  reparto por hilo: %s",
                   ", ".join(f"{k}={v}" for k, v in sorted(por_hilo.items())))
        # CPU consumida (usuario + sistema) según el kernel. RUSAGE_CHILDREN sólo incluye
        # hijos ya recogidos con wait(), por eso se consulta al final.
        yo = resource.getrusage(resource.RUSAGE_SELF)
        hijos = resource.getrusage(resource.RUSAGE_CHILDREN)
        pared = time.monotonic() - self.t_inicio
        L.info("  CPU: principal=%.2f s, trabajadores=%.2f s | tiempo real=%.2f s | "
               "uso medio de CPU de los trabajadores=%.1f %%",
               yo.ru_utime + yo.ru_stime, hijos.ru_utime + hijos.ru_stime, pared,
               100 * (hijos.ru_utime + hijos.ru_stime) / pared)
        L.info("  cambios de contexto trabajadores: voluntarios=%d, involuntarios=%d",
               hijos.ru_nvcsw, hijos.ru_nivcsw)
        dobles = self._estadisticas_flota(entregadas)
        interbloqueos = self._estadisticas_recursos()
        if perdidas:
            L.warning("  BALANCE: %d solicitudes quedaron sin registrar (trabajador caído o "
                      "cola bloqueada)", perdidas)
        # Sin parada anticipada deben haberse generado exactamente las solicitudes pedidas.
        incompletas = (self.cfg.solicitudes > 0 and not self.detener_anticipado
                       and generadas != self.cfg.solicitudes)
        if incompletas:
            L.warning("  BALANCE: se pidieron %d solicitudes y se generaron %d",
                      self.cfg.solicitudes, generadas)
        return perdidas == 0 and not incompletas and dobles == 0 and interbloqueos == 0

    def _estadisticas_flota(self, entregadas) -> int:
        """Métricas de la flota y auditoría de dobles asignaciones. Devuelve las detectadas."""
        L, fl = self.log, self.flota
        con_vehiculo = [r for r in entregadas if r.vehiculo >= 0]
        L.info("  FLOTA: %d vehículos | modo=%s | espera=%s | sección=%s | asignaciones=%d | "
               "reparto: %s", fl.n, fl.modo, fl.espera, fl.seccion, len(con_vehiculo),
               ", ".join(f"V{v + 1}={k}" for v, k in
                         sorted(Counter(r.vehiculo for r in con_vehiculo).items())))
        if con_vehiculo:
            en_ruta = self._concurrencia_maxima(con_vehiculo, "t_asignado", "t_liberado")
            (L.warning if en_ruta > fl.n else L.info)(
                "  entregas con vehículo a la vez: máx=%d con %d vehículos%s", en_ruta, fl.n,
                " (¡más entregas que vehículos!)" if en_ruta > fl.n else "")
        if con_vehiculo:
            esperas = [(r.t_asignado - r.t_inicio) * 1000 for r in con_vehiculo]
            L.info("  espera por vehículo (ms): prom=%.0f máx=%.0f | reintentos de búsqueda "
                   "(espera activa)=%d", statistics.fmean(esperas), max(esperas),
                   sum(r.reintentos for r in self.resultados_recibidos))
            if fl.modo == "seguro":
                mutex = [r.espera_mutex * 1000 for r in con_vehiculo]
                L.info("  espera por el mutex de la flota (ms): prom=%.2f máx=%.2f",
                       statistics.fmean(mutex), max(mutex))

        # 1) Detector en vivo: la sonda contó ocupantes simultáneos de un mismo vehículo.
        en_vivo = fl.dobles.value
        # 2) Auditoría independiente: intervalos de uso [asignado, liberado] que se solapan
        #    en el mismo vehículo. t_asignado se toma DESPUÉS de marcar el vehículo y
        #    t_liberado ANTES de liberarlo, así una ejecución correcta nunca solapa.
        solapes = self._auditar_solapamientos(con_vehiculo)
        conflictivas = len({id(b) for _, _, b in solapes})
        entre = sum(1 for _, a, b in solapes if a.trabajador != b.trabajador)
        nivel = L.warning if (en_vivo or solapes) else L.info
        nivel("  DOBLES ASIGNACIONES: sonda en vivo=%d | auditoría: asignaciones sobre un "
              "vehículo ocupado=%d, pares solapados=%d (entre procesos=%d, entre hilos del "
              "mismo proceso=%d)", en_vivo, conflictivas, len(solapes), entre,
              len(solapes) - entre)
        for v, a, b in solapes[:5]:
            L.warning("    V%d: solicitud %d [%s] y solicitud %d [%s] lo usaron a la vez "
                      "durante %.0f ms", v + 1, a.id, a.hilo, b.id, b.hilo,
                      (min(a.t_liberado, b.t_liberado) - b.t_asignado) * 1000)
        nivel = L.warning if fl.inconsistencias.value else L.info
        nivel("  REGISTROS INCONSISTENTES al liberar (actualizaciones perdidas)=%d",
              fl.inconsistencias.value)
        L.info("  estado final de la flota: libres=%d/%d", fl.libres(), fl.n)
        return max(en_vivo, conflictivas, fl.inconsistencias.value)

    def _estadisticas_recursos(self) -> int:
        """Métricas de andenes, taller e interbloqueos. Devuelve los no resueltos."""
        rc, L = self.recursos, self.log
        detectados = self.vigilante.detectados if self.vigilante else 0
        L.info("  RECURSOS: %d vehículos + %d andenes | estrategia=%s | cargues=%d | "
               "inspecciones=%d", rc.nv, rc.na, rc.estrategia, rc.operaciones[0],
               rc.operaciones[1])
        nivel = L.warning if detectados and rc.estrategia != "deteccion" else L.info
        nivel("  INTERBLOQUEOS: detectados=%d | recuperaciones (víctimas)=%d | reintentos por "
              "tiempo límite=%d", detectados, rc.recuperaciones.value, rc.reintentos.value)
        # Con detección y recuperación los ciclos se resuelven: no son un fallo del sistema.
        return 0 if rc.estrategia == "deteccion" else detectados

    @staticmethod
    def _auditar_solapamientos(rs):
        por_vehiculo = defaultdict(list)
        for r in rs:
            por_vehiculo[r.vehiculo].append(r)
        solapes = []
        for v, lista in sorted(por_vehiculo.items()):
            lista.sort(key=lambda r: r.t_asignado)
            activos = []
            for r in lista:
                activos = [a for a in activos if a.t_liberado > r.t_asignado]
                solapes.extend((v, a, r) for a in activos)
                activos.append(r)
        return solapes

    @staticmethod
    def _concurrencia_maxima(rs, inicio: str, fin: str) -> int:
        """Máximo de intervalos [inicio, fin] superpuestos (barrido de eventos)."""
        eventos = sorted([(getattr(r, inicio), 1) for r in rs] +
                         [(getattr(r, fin), -1) for r in rs],
                         key=lambda e: (e[0], e[1]))
        actual = maximo = 0
        for _, delta in eventos:
            actual += delta
            maximo = max(maximo, actual)
        return maximo
