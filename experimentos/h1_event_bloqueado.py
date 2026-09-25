"""Hallazgo H1: multiprocessing.Event.set() se bloquea si muere un proceso que esperaba.

Reproduce, de forma aislada, el bloqueo encontrado en la Fase 1 y su corrección.

    python3 experimentos/h1_event_bloqueado.py              # versión con el problema
    python3 experimentos/h1_event_bloqueado.py --corregido  # indicador RawValue

Mecanismo: Event.set() llama a Condition.notify_all(), que cuenta los procesos que
duermen en wait() y espera (_woken_count.acquire()) a que CADA UNO confirme que
despertó. Un proceso eliminado con SIGKILL mientras esperaba sigue contado como
durmiente pero nunca confirmará: set() queda bloqueado para siempre, y como lo hace
reteniendo el lock de la Condition, los demás procesos también se bloquean.
"""

import faulthandler
import multiprocessing as mp
import os
import signal
import sys
import threading
import time

ESPERA_VIGILANTE = 3.0


def hijo_event(evento, n):
    while not evento.wait(1.0):
        pass
    print(f"  hijo {n} (PID {os.getpid()}): recibió la orden y termina", flush=True)


def hijo_flag(bandera, n):
    while not bandera.value:
        time.sleep(0.1)
    print(f"  hijo {n} (PID {os.getpid()}): recibió la orden y termina", flush=True)


def main():
    corregido = "--corregido" in sys.argv
    ctx = mp.get_context("fork")
    if corregido:
        parada, destino = ctx.RawValue("b", 0), hijo_flag
    else:
        parada, destino = ctx.Event(), hijo_event

    hijos = [ctx.Process(target=destino, args=(parada, n)) for n in (1, 2, 3)]
    for h in hijos:
        h.start()
    print(f"Versión {'CORREGIDA (RawValue)' if corregido else 'CON EL PROBLEMA (Event)'} | "
          f"principal PID {os.getpid()} | hijos {[h.pid for h in hijos]}", flush=True)
    time.sleep(1.5)                      # los hijos ya están dentro de wait()

    victima = hijos[1]
    os.kill(victima.pid, signal.SIGKILL)
    print(f"SIGKILL al hijo 2 (PID {victima.pid}) mientras esperaba", flush=True)
    time.sleep(0.2)

    ordenado = threading.Event()

    def vigilante():
        if ordenado.wait(ESPERA_VIGILANTE):
            return
        print(f"\nBLOQUEADO: la orden de parada no retornó en {ESPERA_VIGILANTE} s. "
              "Pila de todos los hilos del principal:", flush=True)
        faulthandler.dump_traceback(all_threads=True)
        for h in hijos:
            if h.is_alive():
                h.kill()
        os._exit(1)

    threading.Thread(target=vigilante, name="vigilante", daemon=True).start()
    print("El principal ordena la parada...", flush=True)
    if corregido:
        parada.value = 1
    else:
        parada.set()
    ordenado.set()
    for h in hijos:
        h.join()
    print("Parada completada: todos los hijos terminaron.", flush=True)


if __name__ == "__main__":
    main()
