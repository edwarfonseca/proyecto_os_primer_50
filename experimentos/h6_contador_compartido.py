"""Hallazgo H6: `Value(lock=True)` no hace atómico `v.value += 1`.

Varios procesos (o hilos) incrementan un mismo contador compartido. Se comparan tres
formas de hacerlo:

    RawValue           v.value += 1                    sin ningún lock
    Value(lock=True)   v.value += 1                    el Value "trae" un lock...
    get_lock()         with v.get_lock(): v.value += 1 el lock envuelve la secuencia

`v.value += 1` son dos operaciones: leer v.value y escribir v.value. Value(lock=True)
toma y suelta su lock en CADA una por separado, así que entre la lectura y la escritura
otro proceso puede leer el mismo valor: los dos escriben valor+1 y se pierde un
incremento (actualización perdida). Sólo el tercer caso protege la sección crítica.

    python3 experimentos/h6_contador_compartido.py [INCREMENTOS] [PARTICIPANTES]
"""

import multiprocessing as mp
import sys
import threading
import time

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
P = int(sys.argv[2]) if len(sys.argv) > 2 else 4


def sumar(v, protegido):
    for _ in range(N):
        if protegido:
            with v.get_lock():
                v.value += 1
        else:
            v.value += 1


def medir(ctx, crear, protegido, con_hilos):
    v = crear()
    tipo = threading.Thread if con_hilos else ctx.Process
    t0 = time.monotonic()
    ps = [tipo(target=sumar, args=(v, protegido)) for _ in range(P)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    return v.value, time.monotonic() - t0


def main():
    ctx = mp.get_context("fork")
    casos = [
        ("RawValue: v.value += 1", lambda: ctx.RawValue("i", 0), False),
        ("Value(lock=True): v.value += 1", lambda: ctx.Value("i", 0), False),
        ("with v.get_lock(): v.value += 1", lambda: ctx.Value("i", 0), True),
    ]
    esperado = N * P
    print(f"{P} participantes x {N} incrementos = {esperado} esperados\n")
    print(f"{'PARTICIPANTES':<14} {'FORMA':<34} {'OBTENIDO':>9} {'PERDIDOS':>9} {'%':>6} {'TIEMPO':>8}")
    for con_hilos in (False, True):
        for nombre, crear, protegido in casos:
            valor, dt = medir(ctx, crear, protegido, con_hilos)
            perdidos = esperado - valor
            print(f"{'hilos' if con_hilos else 'procesos':<14} {nombre:<34} {valor:>9} "
                  f"{perdidos:>9} {100 * perdidos / esperado:>5.1f}% {dt:>7.2f}s")


if __name__ == "__main__":
    main()
