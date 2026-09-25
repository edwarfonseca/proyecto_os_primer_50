"""Datos que viajan entre procesos por las colas (se serializan con pickle)."""

from dataclasses import dataclass

ENTREGADA = "ENTREGADA"
CANCELADA = "CANCELADA"


@dataclass(slots=True)
class Solicitud:
    id: int
    cliente: str
    origen: str
    destino: str
    generador: int
    rafaga: int
    t_despacho: float      # segundos de preparación en el centro de despacho
    t_entrega: float       # segundos de ruta hasta la entrega
    t_llegada: float = 0.0  # time.monotonic() al llegar al sistema


@dataclass(slots=True)
class Resultado:
    id: int
    estado: str            # ENTREGADA | CANCELADA
    trabajador: int
    hilo: str
    tid: int
    t_llegada: float
    t_inicio: float        # el despachador la sacó de la cola
    t_fin: float
