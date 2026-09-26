"""Servidor de la demostración gráfica (sólo biblioteca estándar).

    python3 web/servidor.py [--puerto 8080] [--abrir]
    -> abrir http://127.0.0.1:8080 en el navegador

Lanza el sistema (main.py) con los mismos escenarios que scripts/demo.sh y lo muestra en
vivo en el navegador desde dos puntos de vista:

  - el SO, como observador externo: árbol de procesos e hilos, estado, canal de espera
    (wchan), CPU y memoria leídos de /proc por este servidor;
  - el propio programa: su log de eventos, la serie del monitor (<log>.estado.csv) y la del
    muestreador (<log>.recursos.csv), y las estadísticas finales.

Seguridad: sólo escucha en 127.0.0.1; sólo ejecuta los escenarios definidos aquí o
parámetros validados contra una lista blanca; sólo envía señales a procesos hijos de la
ejecución en curso. Una ejecución a la vez.
"""

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from despacho import so_utils  # noqa: E402  (tras ajustar sys.path)
from despacho.metricas import extraer  # noqa: E402

ESTATICOS = Path(__file__).resolve().parent / "static"
LOGS = RAIZ / "logs" / "web"

# --- escenarios: los mismos pasos de scripts/demo.sh -------------------------------------

AISLADO = ["-i", "0", "-a", "100", "-p", "0", "--traza-kb", "0"]
VIVO = ["--intervalo-monitor", "0.5", "--muestreo", "0.5"]
CPU = ["-n", "32", "-g", "4", "-k", "32", "-p", "9", "--despacho", "0-0", "--entrega", "0-0",
       "-v", "100", "-a", "100", "-i", "0", "--traza-kb", "0", "--ventana", "0"]
ESPERA = ["-w", "4", "-t", "4", "-g", "4", "-n", "24", "-k", "24", "-v", "2", "--ventana", "0",
          *AISLADO]
MEMORIA = ["-n", "120", "--tam-rafaga", "10", "--intervalo", "0.2", "-k", "40", "--despacho",
           "0.01-0.02", "--entrega", "0.02-0.05", "--traza-kb", "256", "-v", "100", "-a", "100",
           "-i", "0", "-p", "0", "--ventana", "0"]
INTERB = ["-n", "24", "-g", "4", "-v", "3", "-a", "2", "-i", "1", "-p", "0", "--traza-kb", "0"]

PASOS = [
    {"paso": 1, "titulo": "Procesos e hilos", "requisitos": "1–3 y 14",
     "observar": "Árbol: el principal y sus 3 hijos; los hilos de cada proceso con su nombre, "
                 "estado y canal de espera. PPID de los trabajadores = PID del principal.",
     "decir": "Los procesos cuelgan del padre; los hilos, de su proceso. futex_do_wait = "
              "esperando un lock o semáforo; hrtimer_nanosleep = durmiendo por tiempo. Al "
              "detener, Ctrl+C llega a todo el grupo y sólo el principal coordina el cierre.",
     "escenarios": [{"id": "procesos", "nombre": "Ejecución continua", "continuo": True,
                     "args": ["-n", "0", "--tam-rafaga", "3", "--intervalo", "0.5"]}]},
    {"paso": 2, "titulo": "Condición de carrera", "requisitos": "7, 8 y 15",
     "observar": "Antes: eventos DOBLE ASIGNACIÓN, vehículos con dos solicitudes, hasta 6 "
                 "entregas con 3 vehículos, código de salida 1. Después: cero, y la flota nunca "
                 "supera 3. Compare ambas en la pestaña Comparar.",
     "decir": "Buscar un vehículo libre y marcarlo son dos pasos separados: dos despachadores "
              "ven el mismo libre. El mutex hace indivisible buscar y marcar (cuesta 0.01 ms); "
              "el semáforo cuenta los vehículos libres. La versión corregida tarda más porque "
              "respeta los 3 vehículos: la insegura usaba vehículos que no tenía.",
     "escenarios": [
         {"id": "carrera_antes", "nombre": "Antes (inseguro)",
          "args": ["-n", "24", "-g", "4", "-v", "3", "--modo", "inseguro", "--espera", "activa",
                   *AISLADO]},
         {"id": "carrera_despues", "nombre": "Después (corregido)",
          "args": ["-n", "24", "-g", "4", "-v", "3", "--modo", "seguro", "--espera",
                   "bloqueante", *AISLADO]}]},
    {"paso": 3, "titulo": "Interbloqueo", "requisitos": "10 y 11",
     "observar": "Sin orden: el grafo de espera con el ciclo (hilo → recurso → hilo), los hilos "
                 "del ciclo en futex_do_wait con 0 % de CPU y la parada con SIGTERM. Orden: "
                 "cero interbloqueos. Detección: el ciclo aparece y la víctima suelta lo suyo.",
     "decir": "El cargue pide vehículo y luego andén; la inspección, andén y luego vehículo. Se "
              "cumplen las cuatro condiciones de Coffman. No es lentitud: el kernel no volverá a "
              "ejecutar esos hilos. El orden global rompe la espera circular; la detección "
              "expropia a una víctima.",
     "escenarios": [
         {"id": "interbloqueo_sin_orden", "nombre": "Sin orden (se bloquea)",
          "args": [*INTERB, "--interbloqueo", "sin_orden", "--espera-fin", "4"]},
         {"id": "interbloqueo_orden", "nombre": "Orden global",
          "args": [*INTERB, "--interbloqueo", "orden"]},
         {"id": "interbloqueo_timeout", "nombre": "Tiempo límite",
          "args": [*INTERB, "--interbloqueo", "timeout"]},
         {"id": "interbloqueo_deteccion", "nombre": "Detección y recuperación",
          "args": ["-n", "12", "-g", "4", "-v", "3", "-a", "1", "-i", "2", "-p", "0",
                   "--traza-kb", "0", "--interbloqueo", "deteccion"]}]},
    {"paso": 4, "titulo": "CPU: hilos frente a procesos", "requisitos": "13",
     "observar": "1 × 4: un solo hilo en R a la vez, CPU del trabajador ≈ 100 % (un núcleo), "
                 "real/CPU ≈ 3. 4 × 1: los cuatro en R, CPU ≈ 300–400 %, la mitad del tiempo.",
     "decir": "El GIL deja ejecutar Python a un hilo a la vez; cada proceso tiene su propio GIL. "
              "No llega a 4x porque este equipo tiene 2 núcleos físicos con Hyper-Threading.",
     "escenarios": [
         {"id": "cpu_hilos", "nombre": "1 proceso × 4 hilos", "args": ["-w", "1", "-t", "4", *CPU]},
         {"id": "cpu_procesos", "nombre": "4 procesos × 1 hilo",
          "args": ["-w", "4", "-t", "1", *CPU]}]},
    {"paso": 5, "titulo": "Espera activa frente a bloqueante", "requisitos": "síntoma de CPU",
     "observar": "Mismo tiempo total; la CPU de los trabajadores: ≈ 130 % con espera activa "
                 "frente a ≈ 2 % bloqueante. Hilos en R (activa) frente a futex_do_wait.",
     "decir": "Es el síntoma de CPU elevada del enunciado: los hilos sin vehículo preguntaban en "
              "un bucle. Con el semáforo duermen en el kernel hasta que alguien libera un vehículo.",
     "escenarios": [
         {"id": "espera_activa", "nombre": "Espera activa",
          "args": [*ESPERA, "--espera", "activa", "--reintento", "0"]},
         {"id": "espera_bloqueante", "nombre": "Espera bloqueante",
          "args": [*ESPERA, "--espera", "bloqueante"]}]},
    {"paso": 6, "titulo": "Monitor en vivo", "requisitos": "12",
     "observar": "Use Detener (SIGSTOP) en ambos trabajadores: las cifras se congelan y a los 3 s "
                 "aparece SIN PROGRESO; con Reanudar (SIGCONT) el sistema se recupera solo.",
     "decir": "El registro del requisito 12: recibidas, pendientes, vehículos disponibles y "
              "asignados, finalizadas. El monitor detecta que el sistema no avanza por cualquier "
              "causa; el vigilante explica por qué cuando es un interbloqueo.",
     "escenarios": [{"id": "monitor", "nombre": "Ejecución continua", "continuo": True,
                     "args": ["-n", "0", "--tam-rafaga", "3", "--intervalo", "0.5",
                              "--alerta-sin-progreso", "3"]}]},
    {"paso": 7, "titulo": "Memoria", "requisitos": "CPU y memoria",
     "observar": "RSS por trabajador en la gráfica de memoria: sin límite crece en línea recta; "
                 "acotado se estabiliza (compárelos en la pestaña Comparar).",
     "decir": "Sin límite, cada entrega deja 256 KB: es una fuga. Acotado, se descartan las "
              "trazas viejas y la memoria se estabiliza. Se mide con RSS y PSS, no con VSZ.",
     "escenarios": [
         {"id": "memoria_sin_limite", "nombre": "Historial sin límite",
          "args": [*MEMORIA, "--historial", "0"]},
         {"id": "memoria_acotada", "nombre": "Historial acotado (20)",
          "args": [*MEMORIA, "--historial", "20"]}]},
]
ESCENARIOS = {e["id"]: {**e, "paso": p["paso"]} for p in PASOS for e in p["escenarios"]}

# Parámetros permitidos en el escenario personalizado: bandera -> (tipo, mínimo/opciones, máximo)
PERMITIDOS = {
    "-w": ("int", 1, 16), "-t": ("int", 1, 32), "-g": ("int", 1, 16), "-n": ("int", 0, 1000),
    "--tam-rafaga": ("int", 0, 200), "--intervalo": ("float", 0.05, 10), "-k": ("int", 1, 1000),
    "-v": ("int", 1, 100), "--ventana": ("float", 0, 0.5), "-a": ("int", 1, 100),
    "-i": ("int", 0, 8), "-p": ("int", 0, 9), "--traza-kb": ("int", 0, 1024),
    "--historial": ("int", 0, 1000), "-s": ("int", 0, 10**6), "--reintento": ("float", 0, 1),
    "--modo": ("opcion", ["seguro", "inseguro"]), "--espera": ("opcion", ["bloqueante", "activa"]),
    "--interbloqueo": ("opcion", ["sin_orden", "orden", "timeout", "deteccion"]),
    "--cola": ("opcion", ["semaforos", "mp"]), "--seccion": ("opcion", ["fina", "gruesa"]),
}
SENALES = {"STOP": signal.SIGSTOP, "CONT": signal.SIGCONT, "TERM": signal.SIGTERM,
           "KILL": signal.SIGKILL, "USR1": signal.SIGUSR1}


def validar_personalizado(params: dict) -> list[str]:
    args = []
    for bandera, valor in params.items():
        if bandera not in PERMITIDOS or valor in ("", None):
            continue
        tipo, a, *b = PERMITIDOS[bandera]
        if tipo == "opcion":
            if valor not in a:
                raise ValueError(f"{bandera}: valor no permitido")
        else:
            v = int(valor) if tipo == "int" else float(valor)
            if not a <= v <= b[0]:
                raise ValueError(f"{bandera}: fuera de rango [{a}, {b[0]}]")
            valor = str(v)
        args += [bandera, str(valor)]
    return args


# --- interpretación del log ----------------------------------------------------------------

# (texto del evento, categoría, severidad). La severidad usa los estados reservados de la
# interfaz: critico, serio, aviso, bien; "info" es neutro.
CLASES = [
    ("DOBLE ASIGNACIÓN", "carrera", "critico"),
    ("REGISTRO INCONSISTENTE", "carrera", "critico"),
    ("INTERBLOQUEO DETECTADO", "interbloqueo", "critico"),
    ("INTERBLOQUEO sin recuperación", "interbloqueo", "critico"),
    ("DIAGNÓSTICO", "interbloqueo", "serio"),
    ("RECUPERACIÓN", "interbloqueo", "bien"),
    ("TIEMPO LÍMITE", "interbloqueo", "aviso"),
    ("SIN PROGRESO:", "monitor", "aviso"),   # con ":" para no confundirlo con el resumen final
    ("CAÍDO", "procesos", "critico"),
    ("HUÉRFANO", "procesos", "aviso"),
    ("se envía SIGKILL", "procesos", "serio"),
    ("se envía SIGTERM", "procesos", "aviso"),
    ("SEÑAL", "procesos", "info"),
    ("TERMINÓ", "procesos", "info"),
    ("CREADO", "procesos", "info"),
    ("SINCRONIZADO", "procesos", "bien"),
    ("INICIO taller", "procesos", "info"),
    ("INICIO trabajador", "procesos", "info"),
    ("RÁFAGA", "cola", "info"),
    ("GENERACIÓN terminada", "cola", "info"),
    ("PRODUCTOR BLOQUEADO", "cola", "info"),
    ("SIN VEHÍCULOS", "flota", "info"),
    ("FIN centro de despacho (correcto)", "sistema", "bien"),
    ("FIN centro de despacho (con fallos)", "sistema", "critico"),
    ("INICIO centro", "sistema", "info"),
]
RE_ESTADO = re.compile(r"recibidas=(\d+) en_cola=(-?\d+) en_proceso=(\d+) \(esperando vehículo="
                       r"(\d+)\) \| vehículos: asignados=(\d+) disponibles=(\d+) \[([^\]]*)\] \| "
                       r"finalizadas=(\d+) \(entregadas=(\d+) canceladas=(\d+)\) \| ([\d.]+)/s")
RE_DOBLE = re.compile(r"vehículo (V\d+) asignado a la solicitud (\d+) mientras lo usa la "
                      r"solicitud (\d+) .*\[(.*)\]")
RE_NODO = re.compile(r"([\w-]+) \[tiene ([^,\]]*), espera ([^\]]*)\]")
RE_VICTIMA = re.compile(r"víctima ([\w-]+)")


def parsear_linea(linea: str) -> dict | None:
    partes = linea.rstrip("\n").split(" | ", 6)
    if len(partes) < 7:
        return None
    hora, pid, _ppid, tid, proceso, hilo, msg = partes
    try:
        return {"hora": hora[:12], "pid": int(pid.split()[-1]), "tid": int(tid.split()[-1]),
                "proceso": proceso.strip(), "hilo": hilo.strip(), "msg": msg.strip()}
    except ValueError:
        return None


class Ejecucion:
    """Una ejecución de main.py: proceso, archivos y lo interpretado de su log."""

    def __init__(self, numero: int, escenario: dict, args: list[str]):
        self.numero = numero
        self.escenario = escenario
        self.args = args
        marca = time.strftime("%H%M%S")
        self.log = LOGS / f"{numero:02d}_{escenario['id']}_{marca}.log"
        self.err = self.log.with_suffix(".stderr.txt")
        self.inicio = time.time()
        self.fin: float | None = None
        self.exit: int | None = None
        self.metricas: dict | None = None
        self.eventos: deque = deque(maxlen=400)       # todos (incluye el detalle)
        self.importantes: deque = deque(maxlen=300)   # sólo los importantes: no los desplaza el detalle
        self.estado_monitor: dict | None = None
        self.conflictos: dict[str, dict] = {}       # vehículo -> última doble asignación
        self.ciclos: list[dict] = []                 # interbloqueos detectados
        self._offset = 0
        self._lock = threading.Lock()
        with open(self.err, "w") as err:
            # start_new_session: el sistema queda en su propio grupo de procesos (setsid),
            # como en scripts/demo.sh, y se le puede enviar SIGINT al grupo completo.
            self.proc = subprocess.Popen(
                [sys.executable, "main.py", *args, "--log", str(self.log)], cwd=RAIZ,
                stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        threading.Thread(target=self._esperar, name=f"espera-{numero}", daemon=True).start()

    @property
    def activa(self) -> bool:
        return self.exit is None

    def _esperar(self):
        codigo = self.proc.wait()
        time.sleep(0.2)                   # el log ya está completo al salir el proceso
        self.leer_log()
        texto = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        self.metricas = extraer(texto, extra=True)
        self.fin, self.exit = time.time(), codigo

    def leer_log(self):
        """Lee las líneas nuevas del log (desde la última posición) y las interpreta."""
        if not self.log.exists():
            return
        # Lo llaman el hilo que atiende al navegador y el que espera el fin de la ejecución:
        # el lock cubre la lectura Y la interpretación, para no procesar líneas dos veces ni
        # actualizar los eventos desde dos hilos a la vez.
        with self._lock:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                nuevas = f.readlines()
            if nuevas and not nuevas[-1].endswith("\n"):
                nuevas.pop()              # línea a medio escribir: se leerá en la próxima
            self._offset += sum(len(x.encode("utf-8")) for x in nuevas)
            for linea in nuevas:
                ev = parsear_linea(linea)
                if ev:
                    self._interpretar(ev)

    def _interpretar(self, ev: dict):
        msg = ev["msg"]
        if msg.startswith("ESTADO |"):
            m = RE_ESTADO.search(msg)
            if m:
                g = m.groups()
                flota = []
                for par in g[6].split():
                    v, s = par.split(":")
                    flota.append({"vehiculo": v, "solicitud": None if s == "-" else int(s)})
                self.estado_monitor = {
                    "hora": ev["hora"], "recibidas": int(g[0]), "en_cola": int(g[1]),
                    "en_proceso": int(g[2]), "esperando_vehiculo": int(g[3]),
                    "asignados": int(g[4]), "disponibles": int(g[5]), "flota": flota,
                    "finalizadas": int(g[7]), "entregadas": int(g[8]), "canceladas": int(g[9]),
                    "rendimiento": float(g[10])}
            return
        categoria, severidad = "detalle", "info"
        for texto, cat, sev in CLASES:
            if texto in msg:
                categoria, severidad = cat, sev
                break
        # Las esperas por cola llena o por vehículo son normales con carga alta: se ven en
        # "todos", pero no llenan la lista de eventos importantes.
        ev.update(categoria=categoria, severidad=severidad,
                  importante=categoria not in ("detalle", "cola", "flota"))
        self.eventos.append(ev)
        if ev["importante"]:
            self.importantes.append(ev)
        if categoria == "carrera" and (m := RE_DOBLE.search(msg)):
            self.conflictos[m.group(1)] = {"t": time.time(), "nueva": int(m.group(2)),
                                           "previa": int(m.group(3)), "ambito": m.group(4),
                                           "total": self.conflictos.get(m.group(1), {})
                                           .get("total", 0) + 1}
        elif "INTERBLOQUEO DETECTADO" in msg:
            nodos = [{"hilo": h, "tiene": t.strip(), "espera": e.strip()}
                     for h, t, e in RE_NODO.findall(msg)]
            self.ciclos.append({"hora": ev["hora"], "nodos": nodos, "victima": None})
        elif "RECUPERACIÓN ordenada" in msg and self.ciclos and (m := RE_VICTIMA.search(msg)):
            self.ciclos[-1]["victima"] = m.group(1)

    def resumen(self) -> dict:
        return {"numero": self.numero, "escenario": self.escenario["id"],
                "nombre": f"#{self.numero} {self.escenario['nombre']}",
                "paso": self.escenario.get("paso"), "args": " ".join(self.args),
                "inicio": time.strftime("%H:%M:%S", time.localtime(self.inicio)),
                "duracion": round((self.fin or time.time()) - self.inicio, 1),
                "exit": self.exit, "metricas": self.metricas}


# --- observación del SO desde /proc -----------------------------------------------------

class Observador:
    """Vista externa del sistema: procesos e hilos con CPU calculada entre dos lecturas."""

    def __init__(self):
        self._previo: dict[int, tuple[int, float]] = {}   # tid -> (ticks, instante)
        self._lock = threading.Lock()

    def arbol(self, pid: int) -> list[dict]:
        ahora = time.monotonic()
        procesos = []
        with self._lock:
            for p in [pid] + so_utils.hijos_proceso(pid):
                info = so_utils.info_proceso(p)
                if not info:
                    continue
                hilos = so_utils.hilos_proceso(p)
                for h in hilos:
                    prev = self._previo.get(h["tid"])
                    dt = ahora - prev[1] if prev else 0
                    h["cpu"] = round(100 * (h["ticks"] - prev[0]) / so_utils.TICKS_POR_SEGUNDO
                                     / dt, 1) if prev and dt > 0 else 0.0
                    self._previo[h["tid"]] = (h["ticks"], ahora)
                mem = so_utils.memoria_proceso(p)
                procesos.append({
                    "pid": p, "ppid": info["ppid"], "nombre": info["nombre"],
                    "estado": info["estado"], "hilos": hilos,
                    "cpu": round(sum(h["cpu"] for h in hilos), 1),
                    "rss_mb": round(info["rss_kb"] / 1024, 1),
                    "pss_mb": round(mem.get("Pss", 0) / 1024, 1),
                    "privada_mb": round(mem.get("Private_Dirty", 0) / 1024, 1)})
        return procesos


def leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, newline="") as f:
        filas = list(csv.DictReader(f))
    return filas[:-1] if filas and None in filas[-1].values() else filas


def series(ej: Ejecucion) -> dict:
    """Series del monitor y del muestreador del propio programa (últimos 240 puntos)."""
    monitor = [{k: float(v) for k, v in f.items()} for f in leer_csv(ej.log.with_suffix(".estado.csv"))]
    por_proceso: dict[str, list] = {}
    for f in leer_csv(ej.log.with_suffix(".recursos.csv")):
        por_proceso.setdefault(f["proceso"], []).append(
            (float(f["t_s"]), float(f["rss_kb"]) / 1024, float(f["cpu_s"])))
    recursos = {}
    for nombre, pts in por_proceso.items():
        cpu = [0.0] + [100 * (b[2] - a[2]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                       for a, b in zip(pts, pts[1:])]
        recursos[nombre] = [{"t": t, "rss": round(r, 1), "cpu": round(c, 1)}
                            for (t, r, _), c in zip(pts, cpu)][-240:]
    return {"monitor": monitor[-240:], "recursos": recursos}


# --- gestor y API ------------------------------------------------------------------------

class Gestor:
    def __init__(self):
        self.actual: Ejecucion | None = None
        self.historial: list[Ejecucion] = []
        self.observador = Observador()
        self._lock = threading.Lock()

    def iniciar(self, cuerpo: dict) -> dict:
        with self._lock:
            if self.actual and self.actual.activa:
                raise RuntimeError("ya hay una ejecución en curso: deténgala primero")
            if cuerpo.get("escenario") == "personalizado":
                escenario = {"id": "personalizado", "nombre": "Personalizado", "paso": None}
                args = validar_personalizado(cuerpo.get("params", {}))
            elif cuerpo.get("escenario") in ESCENARIOS:
                escenario = ESCENARIOS[cuerpo["escenario"]]
                args = list(escenario["args"])
            else:
                raise ValueError("escenario desconocido")
            LOGS.mkdir(parents=True, exist_ok=True)
            self.actual = Ejecucion(len(self.historial) + 1, escenario, [*args, *VIVO])
            self.historial.append(self.actual)
            return self.actual.resumen()

    def detener(self, forzar: bool) -> dict:
        ej = self.actual
        if not ej or not ej.activa:
            raise RuntimeError("no hay ninguna ejecución en curso")
        # SIGINT al grupo = Ctrl+C: el principal coordina el cierre ordenado.
        os.killpg(ej.proc.pid, signal.SIGKILL if forzar else signal.SIGINT)
        return {"ok": True}

    def senal(self, pid: int, nombre: str) -> dict:
        ej = self.actual
        if not ej or not ej.activa:
            raise RuntimeError("no hay ninguna ejecución en curso")
        if nombre not in SENALES:
            raise ValueError("señal no permitida")
        if pid not in so_utils.hijos_proceso(ej.proc.pid):
            raise ValueError("sólo se pueden enviar señales a los procesos hijos de la ejecución")
        os.kill(pid, SENALES[nombre])
        return {"ok": True}

    def estado(self) -> dict:
        ej = self.actual
        if not ej:
            return {"ejecucion": None, "historial": [e.resumen() for e in self.historial]}
        ej.leer_log()
        err = ej.err.read_text(errors="replace").splitlines()[-80:] if ej.err.exists() else []
        return {
            "ejecucion": {**ej.resumen(), "activa": ej.activa, "pid": ej.proc.pid,
                          "log": str(ej.log.relative_to(RAIZ))},
            "procesos": self.observador.arbol(ej.proc.pid) if ej.activa else [],
            "monitor": ej.estado_monitor,
            "eventos": list(ej.eventos)[-150:],
            "importantes": list(ej.importantes)[-150:],
            "conflictos": {v: {**c, "hace": round(time.time() - c["t"], 1)}
                           for v, c in ej.conflictos.items()},
            "ciclos": ej.ciclos[-3:],
            "stderr": err,
            "series": series(ej),
            "historial": [e.resumen() for e in self.historial],
        }


GESTOR = Gestor()


class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ESTATICOS), **k)

    def log_message(self, formato, *args):       # sin una línea por petición en la consola
        pass

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/api/escenarios":
            return self._json({"pasos": PASOS, "permitidos": {
                k: {"tipo": v[0], "rango": v[1:]} for k, v in PERMITIDOS.items()}})
        if self.path == "/api/estado":
            return self._json(GESTOR.estado())
        return super().do_GET()

    def do_POST(self):
        try:
            largo = int(self.headers.get("Content-Length", 0))
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            if self.path == "/api/ejecutar":
                return self._json(GESTOR.iniciar(cuerpo))
            if self.path == "/api/detener":
                return self._json(GESTOR.detener(bool(cuerpo.get("forzar"))))
            if self.path == "/api/senal":
                return self._json(GESTOR.senal(int(cuerpo["pid"]), str(cuerpo["senal"])))
            return self._json({"error": "ruta desconocida"}, 404)
        except (ValueError, KeyError, RuntimeError, ProcessLookupError) as e:
            return self._json({"error": str(e)}, 409 if isinstance(e, RuntimeError) else 400)


def main():
    p = argparse.ArgumentParser(description="Demostración gráfica del sistema de despacho.")
    p.add_argument("--puerto", type=int, default=8080)
    p.add_argument("--abrir", action="store_true", help="abrir el navegador al iniciar")
    a = p.parse_args()
    # Manejadores explícitos: un proceso lanzado en segundo plano desde un shell no
    # interactivo hereda SIGINT ignorado (POSIX) y Python no instalaría el suyo; así el
    # servidor siempre se puede cerrar con Ctrl+C o con `kill`, y detiene el sistema al salir.
    def salir(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, salir)
    signal.signal(signal.SIGTERM, salir)

    servidor = ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador)
    url = f"http://127.0.0.1:{a.puerto}"
    print(f"Demostración gráfica en {url}  (Ctrl+C para salir)")
    if a.abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ej = GESTOR.actual
        if ej and ej.activa:              # no dejar el sistema corriendo al cerrar el servidor
            print("Deteniendo la ejecución en curso (Ctrl+C a su grupo de procesos)…")
            os.killpg(ej.proc.pid, signal.SIGINT)
            try:
                ej.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(ej.proc.pid, signal.SIGKILL)
        servidor.server_close()


if __name__ == "__main__":
    main()
