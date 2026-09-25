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
    puntos: tuple = ()     # puntos de entrega (x, y) para planificar la ruta


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
    vehiculo: int = -1     # índice del vehículo asignado (-1 = ninguno)
    t_asignado: float = 0.0
    t_liberado: float = 0.0
    reintentos: int = 0    # búsquedas fallidas de vehículo (espera activa)
    espera_mutex: float = 0.0   # segundos esperando el mutex de la flota
    costo_ruta: float = 0.0     # longitud de la ruta óptima (misma carga -> mismo valor)
    t_ruta_cpu: float = 0.0     # CPU consumida por el hilo al planificar (thread_time)
    t_ruta_real: float = 0.0    # tiempo real transcurrido al planificar
