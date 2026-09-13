"""
Captura de trayectoria continua: registra la posición de cada persona
por frame, para generar mapas de calor de circulación general.

Nota de diseño: el timestamp original (traducido vía `frame_mapping`
cuando aplica) lo provee la `FrameSource`; este módulo NO duplica esa
lógica — solo anota posición + tiempo por frame y track activo.
"""
from typing import Tuple

from app.core.detection.schemas import PositionSample, TrackedPerson
from app.utils.config import TRAJECTORY_SAMPLE_EVERY_N_FRAMES


def compute_foot_position(person: TrackedPerson) -> Tuple[float, float]:
    """Bottom-center del bbox como proxy de la posición del pie de una persona."""
    x1, y1, x2, y2 = person.bbox
    return (x1 + x2) / 2.0, float(y2)


class TrajectoryCapture:
    """
    Captura continua de posición por frame y por persona trackeada.

    Por cada frame procesado, registra:
    - track_id de la persona
    - índice de frame en el stream procesado
    - timestamp original (video original con frame_mapping, o wall-clock en vivo)
    - posición del pie (bottom-center del bbox como proxy)

    La frecuencia de muestreo es configurable para limitar el volumen
    de datos (por defecto cada N frames).
    """

    def __init__(
        self,
        sample_every_n_frames: int = TRAJECTORY_SAMPLE_EVERY_N_FRAMES,
        camera_id: str = "cam_1",
    ):
        self.sample_every_n_frames = max(1, sample_every_n_frames)
        self.camera_id = camera_id

    def process(
        self,
        frame_index: int,
        tracked_people: list[TrackedPerson],
        timestamp_sec: float,
    ) -> list[PositionSample]:
        """
        Procesa un frame: devuelve una PositionSample por persona trackeada
        (si el frame coincide con la frecuencia de muestreo).
        """
        if frame_index % self.sample_every_n_frames != 0:
            return []

        samples: list[PositionSample] = []
        for person in tracked_people:
            foot_x, foot_y = compute_foot_position(person)

            samples.append(
                PositionSample(
                    track_id=person.track_id,
                    frame_index=frame_index,
                    original_timestamp_sec=timestamp_sec,
                    foot_position=(foot_x, foot_y),
                    camera_id=self.camera_id,
                )
            )

        return samples
