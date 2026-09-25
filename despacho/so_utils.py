"""Utilidades para interactuar con el SO a través de /proc y señales."""

import faulthandler
import os
import signal

_TICKS = os.sysconf("SC_CLK_TCK")
_PAGINA_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def nombrar_proceso(nombre: str) -> None:
    """Cambia el nombre del proceso en el kernel escribiendo /proc/self/comm.

    Es el nombre que muestran `ps -o comm`, `pstree`, `top` y `pgrep`. El kernel
    lo limita a 15 caracteres (TASK_COMM_LEN - 1).
    """
    with open("/proc/self/comm", "w") as f:
        f.write(nombre[:15])


def info_proceso(pid: int) -> dict | None:
    """Lee el estado de un proceso desde /proc. Devuelve None si ya no existe."""
    try:
        with open(f"/proc/{pid}/status") as f:
            campos = dict(linea.split(":", 1) for linea in f if ":" in linea)
        with open(f"/proc/{pid}/stat") as f:
            # El nombre (campo 2) va entre paréntesis y puede tener espacios:
            # se separa por el último ')' para ubicar bien los campos siguientes.
            resto = f.read().rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None

    utime, stime = int(resto[11]), int(resto[12])      # campos 14 y 15 de stat
    return {
        "pid": pid,
        "nombre": campos["Name"].strip(),
        "estado": campos["State"].strip(),
        "ppid": int(campos["PPid"]),
        "hilos": int(campos["Threads"]),
        "rss_kb": int(campos.get("VmRSS", "0 kB").split()[0]),
        "cpu_s": (utime + stime) / _TICKS,
    }


def memoria_proceso(pid: int) -> dict:
    """Resumen de memoria de /proc/<pid>/smaps_rollup en kB (Rss, Pss, Private_Dirty...).

    PSS reparte cada página compartida entre los procesos que la comparten: la suma de los
    PSS de varios procesos es la memoria física que realmente ocupan entre todos.
    """
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            return {k: int(v.split()[0]) for k, v in
                    (linea.split(":", 1) for linea in f if linea.endswith("kB\n"))}
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return {}


def hilos_proceso(pid: int) -> list[dict]:
    """Lista los hilos (tareas) de un proceso: /proc/<pid>/task/<tid>."""
    hilos = []
    try:
        tids = sorted(int(t) for t in os.listdir(f"/proc/{pid}/task"))
    except (FileNotFoundError, ProcessLookupError):
        return hilos
    for tid in tids:
        try:
            with open(f"/proc/{pid}/task/{tid}/comm") as f:
                nombre = f.read().strip()
            with open(f"/proc/{pid}/task/{tid}/stat") as f:
                estado = f.read().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            # El hilo terminó entre el listado del directorio y la lectura: el kernel
            # responde ENOENT o ESRCH. /proc es una vista viva, no una foto consistente.
            continue
        hilos.append({"tid": tid, "nombre": nombre, "estado": estado})
    return hilos


def habilitar_volcado_hilos() -> None:
    """`kill -USR1 <pid>` imprime en stderr la pila de TODOS los hilos del proceso.

    Herramienta de diagnóstico: muestra en qué línea está bloqueado cada hilo sin
    detener el programa (útil ante bloqueos e interbloqueos).
    """
    faulthandler.register(signal.SIGUSR1, all_threads=True)


def describir_salida(exitcode: int | None) -> str:
    """Traduce el exitcode de multiprocessing (negativo = terminado por señal)."""
    if exitcode is None:
        return "en ejecución"
    if exitcode < 0:
        return f"terminado por señal {signal.Signals(-exitcode).name}"
    return f"exit({exitcode})"
