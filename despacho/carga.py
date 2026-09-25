"""Carga de CPU y de memoria del despacho.

CPU — planificación de la ruta de reparto: cada solicitud trae P puntos de entrega y se
busca, por fuerza bruta, el recorrido más corto que sale del centro (0, 0), visita todos
los puntos y regresa (problema del viajante). Evalúa P! recorridos: 7 puntos ≈ 3 ms,
8 ≈ 25 ms, 9 ≈ 220 ms de CPU. Es Python puro: el hilo retiene el GIL todo el cálculo.

Memoria — historial de trazas GPS: al entregar, cada despachador guarda la traza del
recorrido (KB configurables) en un historial compartido por los hilos de su proceso.
    --historial N > 0: se conservan las N trazas más recientes (crecimiento controlado).
    --historial 0:     se conservan todas (crecimiento sin límite, como una fuga).
"""

import itertools
import math
import threading
from collections import OrderedDict


def ruta_optima(puntos) -> tuple[float, tuple[int, ...]]:
    """Devuelve (longitud del recorrido más corto, orden de visita de los puntos)."""
    nodos = [(0.0, 0.0)] + list(puntos)
    d = [[math.dist(a, b) for b in nodos] for a in nodos]
    mejor, orden = math.inf, ()
    for perm in itertools.permutations(range(1, len(nodos))):
        costo = d[0][perm[0]] + d[perm[-1]][0]
        for i in range(len(perm) - 1):
            costo += d[perm[i]][perm[i + 1]]
        if costo < mejor:
            mejor, orden = costo, perm
    return mejor, orden


class Historial:
    """Trazas GPS de las entregas de un proceso, compartidas por todos sus hilos.

    Es estado compartido entre HILOS del mismo proceso (un OrderedDict en el heap del
    proceso), así que se protege con un threading.Lock, que es más barato que un lock
    entre procesos porque no necesita memoria compartida del kernel.
    """

    def __init__(self, max_entradas: int, kb_por_traza: int):
        self.max_entradas = max_entradas
        self.bytes_por_traza = kb_por_traza * 1024
        self._lock = threading.Lock()
        self._trazas: OrderedDict[int, bytes] = OrderedDict()
        self.descartadas = 0

    def registrar(self, id_sol: int) -> None:
        if not self.bytes_por_traza:
            return
        # La traza se construye fuera del lock (sección crítica mínima). Se escriben todos
        # sus bytes: una reserva sin escribir (p. ej. bytes(n)) puede no ocupar páginas
        # físicas y no se reflejaría en el RSS.
        traza = (b"GPS:%08d;" % id_sol) * (self.bytes_por_traza // 13 + 1)
        traza = traza[:self.bytes_por_traza]
        with self._lock:
            self._trazas[id_sol] = traza
            while self.max_entradas and len(self._trazas) > self.max_entradas:
                self._trazas.popitem(last=False)      # descarta la más antigua
                self.descartadas += 1

    def resumen(self) -> tuple[int, int]:
        with self._lock:
            return len(self._trazas), len(self._trazas) * self.bytes_por_traza
