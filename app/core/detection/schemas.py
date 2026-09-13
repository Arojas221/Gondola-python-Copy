"""
Definición de los contratos de datos y esquemas de validación (Pydantic) para el pipeline de detección.
"""
from typing import Literal, Tuple, List
from uuid import uuid4
from pydantic import BaseModel, Field

class Detection(BaseModel):
    """Representa una detección de persona en un frame específico."""
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    confidence: float = Field(ge=0.0, le=1.0)
    frame_index: int

class TrackedPerson(Detection):
    """Representa una persona detectada con un ID de tracking persistente."""
    track_id: int

class Keypoint(BaseModel):
    """Coordenadas de un punto de articulación (keypoint) y su confianza."""
    x: float
    y: float
    confidence: float = Field(ge=0.0, le=1.0)

class PoseResult(BaseModel):
    """Keypoints de interés (muñecas, codos y hombros) asociados a un track ID."""
    track_id: int
    frame_index: int
    left_wrist: Keypoint
    right_wrist: Keypoint
    left_elbow: Keypoint
    right_elbow: Keypoint
    left_shoulder: Keypoint
    right_shoulder: Keypoint

class Zone(BaseModel):
    """Geometría de una zona de la góndola."""
    zone_id: str = Field(description="Identificador único (nombre de archivo en data/zones/<video_id>/)")
    video_id: str = Field(description="Video/cámara al que pertenece esta zona (evita mezclar zonas entre videos distintos)")
    name: str = Field(description="Nombre legible de la zona (ej: Góndola A1)")
    polygon: List[Tuple[float, float]] = Field(description="Puntos (x, y) que cierran la zona")
    zone_type: Literal["product", "staff"] = Field(
        default="product",
        description="'product' = zona de góndola (dwell time); 'staff' = zona de personal (excluye de métricas de cliente)",
    )

class ZoneSignal(BaseModel):
    """Señales de interacción entre una persona trackeada y una zona en un frame."""
    track_id: int = Field(description="ID de la persona trackeada")
    zone_id: str = Field(description="Zona evaluada en este frame")
    frame_index: int = Field(description="Índice del frame procesado")
    wrist_inside: bool = Field(description="¿La muñeca está dentro del polígono de la zona?")
    arm_extended: bool = Field(description="¿El brazo está extendido (ratio distancia hombro-muñeca/codo-hombro)?")


def _new_event_id() -> str:
    """Genera el UUID único de auditoría de un InteractionEvent."""
    return str(uuid4())


class InteractionEvent(BaseModel):
    """Evento final de interacción enviado al bus de eventos y guardado localmente."""
    track_id: int = Field(description="Identificador efímero de la persona en esta sesión de video")
    zone_id: str = Field(description="Zona de góndola donde ocurrió la interacción")
    action: Literal["reaching", "holding", "taken", "returned"] = Field(
        description=(
            "Tipo de interacción detectada. La máquina de estados solo distingue "
            "'taken'/'returned' (no hay detección de producto): la primera interacción "
            "de una persona con una zona en la sesión es 'taken', las siguientes "
            "alternan a 'returned'/'taken' (heurístico, ver state_machine.py). "
            "'reaching'/'holding' quedan reservados para una futura granularidad."
        )
    )
    timestamp: float = Field(description="Segundos traducidos al video original (o wall-clock en vivo)")
    event_id: str = Field(default_factory=_new_event_id, description="UUID para auditoría y deduplicación")
    is_employee: bool = Field(
        default=False,
        description="True si el track fue marcado como empleado (StaffZoneTracker) antes o durante este evento",
    )

class PositionSample(BaseModel):
    """
    Muestra de posición continua de una persona en un frame.

    Es el tipo de dato base para heatmaps de circulación/dwell time:
    a diferencia de `InteractionEvent` (discreto, disparado por la máquina
    de estados), se publica por cada frame procesado y por cada track activo.
    """
    track_id: int = Field(description="Identificador efímero de la persona en esta sesión")
    frame_index: int = Field(description="Índice en el stream de frames procesado")
    original_timestamp_sec: float = Field(
        description="Segundos traducidos al video original (o wall-clock en vivo)"
    )
    foot_position: Tuple[float, float] = Field(
        description="Bottom-center del bbox como proxy del pie (x, y)"
    )
    camera_id: str = Field(default="cam_1", description="Escalable a multi-cámara en el futuro")
    is_employee: bool = Field(
        default=False,
        description="True si el track fue marcado como empleado (StaffZoneTracker) al momento de esta muestra",
    )


class DwellRecord(BaseModel):
    """Registro de tiempo de permanencia de una persona dentro de una zona de producto."""
    event_type: Literal["dwell"] = "dwell"
    track_id: int = Field(description="Identificador efímero de la persona en esta sesión")
    zone_id: str = Field(description="Zona de producto donde se registró la permanencia")
    entry_timestamp: float = Field(description="Segundos (video original) en que la persona entró a la zona")
    exit_timestamp: float = Field(description="Segundos (video original) en que la persona salió de la zona")
    duration_sec: float = Field(description="Duración de la permanencia, en segundos")
    is_employee: bool = Field(default=False, description="True si el track estaba marcado como empleado al salir de la zona")
    event_id: str = Field(default_factory=_new_event_id, description="UUID para auditoría y deduplicación")
