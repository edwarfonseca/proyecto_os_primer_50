"""Proceso principal: centro de despacho que crea y administra los trabajadores."""

import multiprocessing as mp
import os
import signal
import time

from . import registro, so_utils
from .config import Config
from .trabajador import proceso_trabajador


class CentroDespacho:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.trabajadores: list[mp.Process] = []
        self._senal: int | None = None
        self._caidos: set[int] = set()

    def ejecutar(self) -> int:
        so_utils.nombrar_proceso("centro_despacho")
        mp.current_process().name = "centro_despacho"
        self.log = registro.configurar(self.cfg.ruta_log)
        self.log.info("INICIO centro de despacho | método=%s | trabajadores=%d | log=%s",
                      self.cfg.metodo_inicio, self.cfg.trabajadores, self.cfg.ruta_log)

        so_utils.habilitar_volcado_hilos()
        ctx = mp.get_context(self.cfg.metodo_inicio)
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

        # Los procesos se crean ANTES de lanzar cualquier hilo en el principal: hacer
        # fork() de un proceso con varios hilos sólo copia el hilo que llama y puede
        # dejar locks tomados por hilos que no existen en el hijo.
        self._crear_trabajadores(ctx, listos)
        self._instalar_senales()
        self._esperar_arranque(listos)
        self._registrar_jerarquia()
        self._supervisar()
        return self._finalizar()

    # -- creación -----------------------------------------------------------------

    def _crear_trabajadores(self, ctx, listos) -> None:
        # Se ignora SIGINT mientras se crean los hijos: con fork heredan esa disposición
        # y quedan protegidos desde el primer instante (sin ventana de carrera).
        previo = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            for i in range(1, self.cfg.trabajadores + 1):
                p = ctx.Process(target=proceso_trabajador, name=f"trabajador-{i}",
                                args=(i, self.detener, listos, self.cfg))
                p.start()
                self.trabajadores.append(p)
                self.log.info("CREADO %s -> PID %d", p.name, p.pid)
        finally:
            signal.signal(signal.SIGINT, previo)

    def _instalar_senales(self) -> None:
        # El manejador sólo anota la señal. Coordinar el cierre (tomar locks, escribir
        # en el log) desde un manejador puede interbloquear al hilo principal consigo
        # mismo si la señal llega mientras ese hilo ya tiene el lock; el cierre se hace
        # luego desde el flujo normal en _supervisar().
        def manejador(signum, _frame):
            self._senal = signum
        signal.signal(signal.SIGINT, manejador)
        signal.signal(signal.SIGTERM, manejador)

    def _esperar_arranque(self, listos) -> None:
        limite = time.monotonic() + 10
        for n in range(self.cfg.trabajadores):
            if not listos.acquire(timeout=max(0.0, limite - time.monotonic())):
                self.log.error("ARRANQUE incompleto: sólo %d de %d trabajadores listos",
                               n, self.cfg.trabajadores)
                return
        self.log.info("SINCRONIZADO: %d trabajadores listos", self.cfg.trabajadores)

    # -- observación y supervisión -----------------------------------------------

    def _registrar_jerarquia(self) -> None:
        self.log.info("JERARQUÍA de procesos (leída de /proc):")
        self.log.info("  %-7s %-7s %-16s %-6s %-6s %-9s", "PID", "PPID", "NOMBRE",
                      "ESTADO", "HILOS", "RSS(kB)")
        for pid in [os.getpid()] + [p.pid for p in self.trabajadores]:
            i = so_utils.info_proceso(pid)
            if i:
                self.log.info("  %-7d %-7d %-16s %-6s %-6d %-9d", i["pid"], i["ppid"],
                              i["nombre"], i["estado"][0], i["hilos"], i["rss_kb"])

    def _supervisar(self) -> None:
        fin = time.monotonic() + self.cfg.duracion if self.cfg.duracion > 0 else None
        while True:
            if self._senal is not None:
                self.log.info("SEÑAL %s recibida: se inicia el cierre ordenado",
                              signal.Signals(self._senal).name)
                break
            if fin is not None and time.monotonic() >= fin:
                self.log.info("DURACIÓN cumplida (%.1f s): se inicia el cierre ordenado",
                              self.cfg.duracion)
                break
            if not self._vigilar_trabajadores():
                self.log.error("NINGÚN trabajador activo: se inicia el cierre")
                break
            time.sleep(0.2)

    def _vigilar_trabajadores(self) -> bool:
        """Detecta trabajadores que terminaron inesperadamente. Devuelve si queda alguno."""
        vivos = 0
        for p in self.trabajadores:
            # is_alive() hace waitpid(WNOHANG): si el hijo terminó, lo recoge y así no
            # queda como zombi (estado Z) en la tabla de procesos.
            if p.is_alive():
                vivos += 1
            elif p.pid not in self._caidos:
                self._caidos.add(p.pid)
                self.log.warning("CAÍDO %s (PID %d): %s", p.name, p.pid,
                                 so_utils.describir_salida(p.exitcode))
        return vivos > 0

    # -- cierre ---------------------------------------------------------------------

    def _finalizar(self) -> int:
        self.detener.value = 1
        for p in self.trabajadores:
            p.join(timeout=self.cfg.espera_fin)
            if p.is_alive():
                self.log.warning("%s (PID %d) no terminó en %.1f s: se envía SIGTERM",
                                 p.name, p.pid, self.cfg.espera_fin)
                p.terminate()
                p.join(timeout=self.cfg.espera_fin)
            if p.is_alive():
                # Un proceso detenido (estado T) deja SIGTERM pendiente y no lo atiende;
                # SIGKILL no se puede capturar ni ignorar y el kernel lo aplica siempre.
                self.log.warning("%s (PID %d) ignoró SIGTERM (estado %s): se envía SIGKILL",
                                 p.name, p.pid,
                                 (so_utils.info_proceso(p.pid) or {}).get("estado", "?"))
                p.kill()
                p.join()

        self.log.info("RESUMEN de terminación:")
        for p in self.trabajadores:
            self.log.info("  %-14s PID %-7d %s", p.name, p.pid,
                          so_utils.describir_salida(p.exitcode))
        huerfanos = [p.pid for p in self.trabajadores if so_utils.info_proceso(p.pid)]
        self.log.info("VERIFICACIÓN: procesos hijos que siguen en /proc: %s",
                      huerfanos or "ninguno (sin zombis ni huérfanos)")

        exito = all(p.exitcode == 0 for p in self.trabajadores)
        self.log.info("FIN centro de despacho (%s)", "correcto" if exito else "con fallos")
        return 0 if exito else 1
