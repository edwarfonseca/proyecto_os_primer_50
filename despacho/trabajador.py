"""Proceso trabajador: sus hilos despachadores atienden solicitudes de transporte.

Cada trabajador lanza T hilos despachadores (consumidores) que compiten por la cola de
solicitudes compartida con los hilos de los demás trabajadores. El hilo principal del
trabajador sólo los crea, vigila la orfandad y espera a que terminen.
"""

import math
import os
import queue
import random
import signal
import threading
import time

from . import registro, so_utils
from .carga import Historial, ruta_optima
from .modelo import CANCELADA, ENTREGADA, Resultado
from .recursos import Abortado

SONDEO = 0.1        # segundos entre revisiones del hilo principal del trabajador
ESPERA_COLA = 0.5   # timeout de get(): permite revisar las órdenes de parada


def proceso_trabajador(id_trabajador, detener, listos, cola, resultados, flota, recursos,
                       contadores, cfg) -> None:
    """Punto de entrada del proceso hijo.

    detener:    byte en memoria compartida (RawValue); el principal escribe 1 para abortar.
    listos:     semáforo compartido; cada trabajador hace release() al quedar listo.
    cola:       cola de solicitudes (productor-consumidor) compartida por todos.
    resultados: cola por la que se informa al principal cada solicitud terminada.
    flota:      estado compartido de los vehículos (memoria compartida).
    recursos:   locks de vehículos en el patio y de andenes, con su registro.
    contadores: contadores compartidos del sistema para el monitor.
    """
    so_utils.nombrar_proceso(f"trabajador-{id_trabajador}")
    # Ctrl+C envía SIGINT a todo el grupo de procesos del terminal. Sólo el principal
    # debe reaccionar y coordinar el cierre; los trabajadores lo ignoran.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    so_utils.habilitar_volcado_hilos()
    log = registro.configurar(cfg.ruta_log)

    ppid_original = os.getppid()
    parar = threading.Event()       # orden local (mismo proceso) para los despachadores
    historial = Historial(cfg.historial, cfg.traza_kb)   # compartido por los hilos del proceso
    hilos = [
        Despachador(id_trabajador, t, cola, resultados, flota, recursos, historial, contadores,
                    detener, parar, log)
        for t in range(1, cfg.hilos + 1)
    ]
    for h in hilos:
        h.start()
    log.info("INICIO trabajador %d con %d hilos despachadores", id_trabajador, len(hilos))
    listos.release()

    while any(h.is_alive() for h in hilos):
        if not parar.is_set() and os.getppid() != ppid_original:
            # El principal murió sin ordenar el cierre: el kernel re-asignó este proceso
            # a un "subreaper" (o a PID 1). Sin esta comprobación quedaría vivo para siempre.
            log.warning("HUÉRFANO: el principal (PID %d) terminó; adoptado por PID %d. "
                        "Se detienen los despachadores", ppid_original, os.getppid())
            parar.set()
        time.sleep(SONDEO)

    for h in hilos:
        h.join()
    log.info("FIN trabajador %d | atendidas por hilo: %s", id_trabajador,
             ", ".join(f"{h.name}={h.entregadas}" for h in hilos))
    entradas, tam = historial.resumen()
    mem = so_utils.memoria_proceso(os.getpid())
    log.info("MEMORIA trabajador %d | historial: %d trazas (%.1f MB), %d descartadas | "
             "RSS=%.1f MB, PSS=%.1f MB, privada modificada=%.1f MB", id_trabajador, entradas,
             tam / 2**20, historial.descartadas, mem.get("Rss", 0) / 1024,
             mem.get("Pss", 0) / 1024, mem.get("Private_Dirty", 0) / 1024)


class Despachador(threading.Thread):
    """Consumidor: toma una solicitud, le asigna un vehículo, la despacha y la entrega."""

    def __init__(self, id_trabajador, idx, cola, resultados, flota, recursos, historial,
                 contadores, detener, parar, log):
        super().__init__(name=f"despachador-{id_trabajador}-{idx}")
        self.id_trabajador = id_trabajador
        self.cola = cola
        self.resultados = resultados
        self.flota = flota
        self.recursos = recursos
        self.historial = historial
        self.contadores = contadores
        self.slot = recursos.slot_despachador(id_trabajador, idx)
        self.detener = detener
        self.parar = parar
        self.log = log
        self.entregadas = 0
        self.canceladas = 0

    def run(self):
        tid = threading.get_native_id()
        ocioso = False
        while True:
            try:
                s = self.cola.get(timeout=ESPERA_COLA)
            except queue.Empty:
                # Cola vacía (o el lock de lectores ocupado por otro consumidor).
                if self.parar.is_set() or self.detener.value:
                    break
                if not ocioso:
                    self.log.info("CONSUMIDOR ESPERANDO: cola vacía")
                    ocioso = True
                continue
            ocioso = False

            if s is None:                   # centinela: no habrá más solicitudes
                self.contadores.sumar("centinelas")
                self.log.info("CENTINELA recibido: el hilo termina")
                break

            t_inicio = time.monotonic()
            self.contadores.sumar("tomadas")
            costo, t_cpu, t_real = self._planificar(s) if not self.detener.value else (0, 0, 0)
            v, reintentos, espera_mutex = (None, 0, 0.0) if self.detener.value else \
                self.flota.asignar(s.id, self.detener, self.log)
            if v is None:
                # Parada solicitada antes de conseguir vehículo: la solicitud se retira sin
                # atenderla y se informa como cancelada para que el balance final cuadre.
                self.canceladas += 1
                self.contadores.sumar("canceladas")
                self.resultados.put(Resultado(s.id, CANCELADA, self.id_trabajador, self.name,
                                              tid, s.t_llegada, t_inicio, time.monotonic(),
                                              reintentos=reintentos))
                continue
            t_asignado = time.monotonic()

            self.log.info("DESPACHO solicitud %d en V%d (%s: %s -> %s) | esperó en cola %.0f ms"
                          ", por vehículo %.0f ms", s.id, v + 1, s.cliente, s.origen, s.destino,
                          (t_inicio - s.t_llegada) * 1000, (t_asignado - t_inicio) * 1000)
            # Cargue: el vehículo se prepara en el patio (retiene el vehículo) y luego se
            # carga en un andén (retiene vehículo y andén). Orden natural: vehículo -> andén.
            rc = self.recursos
            d = random.randrange(rc.na)
            try:
                rc.con_dos(self.slot, v, rc.anden(d), antes=s.t_despacho / 2,
                           durante=s.t_despacho / 2, detener=self.detener, log=self.log)
            except Abortado:
                self.flota.liberar(v, s.id, self.log)
                self.canceladas += 1
                self.contadores.sumar("canceladas")
                self.resultados.put(Resultado(s.id, CANCELADA, self.id_trabajador, self.name,
                                              tid, s.t_llegada, t_inicio, time.monotonic(),
                                              reintentos=reintentos))
                continue
            rc.registrar_operacion(0)
            self.log.info("EN RUTA solicitud %d en V%d (cargada en %s)", s.id, v + 1,
                          rc.nombre_recurso(rc.anden(d)))
            time.sleep(s.t_entrega)         # trayecto hasta la entrega
            t_liberado = time.monotonic()
            self.flota.liberar(v, s.id, self.log)
            self.historial.registrar(s.id)        # traza GPS del recorrido
            t_fin = time.monotonic()
            self.entregadas += 1
            self.contadores.sumar("entregadas")
            self.log.info("ENTREGADA solicitud %d | V%d liberado | servicio %.0f ms", s.id,
                          v + 1, (t_fin - t_inicio) * 1000)
            self.resultados.put(Resultado(s.id, ENTREGADA, self.id_trabajador, self.name,
                                          tid, s.t_llegada, t_inicio, t_fin, v, t_asignado,
                                          t_liberado, reintentos, espera_mutex, costo, t_cpu,
                                          t_real))

    def _planificar(self, s) -> tuple[float, float, float]:
        """Ruta óptima de la solicitud. Devuelve (costo, CPU del hilo, tiempo real).

        time.thread_time() mide la CPU que consumió ESTE hilo (CLOCK_THREAD_CPUTIME_ID del
        kernel). Si el tiempo real es mayor que la CPU, el hilo estuvo listo pero sin
        ejecutarse: esperando el GIL (otros hilos del proceso) o un núcleo libre.
        """
        if not s.puntos:
            return 0.0, 0.0, 0.0
        t0, c0 = time.monotonic(), time.thread_time()
        costo, _ = ruta_optima(s.puntos)
        t_real, t_cpu = time.monotonic() - t0, time.thread_time() - c0
        self.log.info("RUTA solicitud %d: %d puntos, %d recorridos, longitud %.1f | CPU %.0f ms, "
                      "real %.0f ms", s.id, len(s.puntos), math.factorial(len(s.puntos)), costo,
                      t_cpu * 1000, t_real * 1000)
        return costo, t_cpu, t_real
