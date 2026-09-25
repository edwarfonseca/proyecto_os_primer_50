"""Contadores del sistema compartidos entre procesos, para el registro en vivo.

Todos los contadores comparten UN lock: cada actualización es atómica y el monitor puede
leer una foto consistente de todos a la vez (si cada uno tuviera su propio lock, la foto
mezclaría valores de instantes distintos).

Ojo con multiprocessing.Value(lock=True): `v.value += 1` NO es atómico aunque el Value
"tenga lock", porque son dos operaciones (leer y escribir) y el lock protege cada una por
separado, no la secuencia. Se pierden incrementos (hallazgo H6). Aquí el lock envuelve la
secuencia completa.
"""

CAMPOS = ("tomadas", "esperando_vehiculo", "entregadas", "canceladas", "centinelas")


class Contadores:
    def __init__(self, ctx):
        self._lock = ctx.Lock()
        self._valores = ctx.RawArray("i", len(CAMPOS))

    def sumar(self, campo: str, n: int = 1) -> None:
        i = CAMPOS.index(campo)
        with self._lock:                # leer-modificar-escribir dentro de la sección crítica
            self._valores[i] += n

    def foto(self) -> dict[str, int]:
        with self._lock:
            return dict(zip(CAMPOS, self._valores))
