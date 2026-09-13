"""
Sesión de análisis: lo que la aplicación necesita saber para analizar algo.

Antes, la pestaña de zonas guardaba una **ruta de archivo** y con ella
construía un `VideoFileFrameSource`. Eso hacía imposible analizar una
cámara en directo sin llenar la interfaz de condicionales "si es archivo…
si es cámara…".

`AnalysisSession` guarda en su lugar **cómo crear la fuente**. La pestaña
de zonas pide `session.create_source()` y recibe la fuente que
corresponda; no sabe ni le importa de dónde salen los frames, que es
exactamente el desacople que `FrameSource` buscaba desde el principio.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import numpy as np

from app.core.detection.schemas import Zone
from app.core.ingestion.frame_source import (
    FrameSource,
    LiveFrameSource,
    VideoFileFrameSource,
)


@dataclass
class AnalysisSession:
    """
    Una sesión analizable: un video limpio o una cámara en directo.

    `video_id` es la identidad de la sesión en todo el sistema: con él se
    guardan las zonas en `data/zones/<video_id>/` y se etiquetan las filas
    en la base de datos. Tiene que venir ya normalizado
    (`zone.normalize_video_id`).
    """

    video_id: str
    title: str                       # nombre legible para la interfaz
    fps: float = 30.0
    reference_frame: Optional[np.ndarray] = None
    suggested_zones: List[Zone] = field(default_factory=list)

    # Exactamente uno de los dos define el origen de los frames.
    video_path: Optional[Path] = None
    live_source: Optional[Union[int, str]] = None

    @property
    def is_live(self) -> bool:
        return self.live_source is not None

    @classmethod
    def from_video(cls, video_id: str, video_path, fps: float, **kwargs) -> "AnalysisSession":
        path = Path(video_path)
        return cls(video_id=video_id, title=path.name, fps=fps, video_path=path, **kwargs)

    @classmethod
    def from_live(cls, video_id: str, source, fps: float, title: str = "", **kwargs) -> "AnalysisSession":
        return cls(
            video_id=video_id,
            title=title or f"Cámara en vivo ({source})",
            fps=fps,
            live_source=source,
            **kwargs,
        )

    def create_source(self, frame_stride: int = 1) -> FrameSource:
        """
        Construye la fuente de frames de esta sesión.

        `frame_stride` solo aplica a un archivo: en una cámara en directo no
        hay nada que "saltar" — el búfer de captura ya está en 1, así que
        cada lectura devuelve el frame más reciente y los intermedios se
        descartan solos mientras el pipeline procesa.
        """
        if self.is_live:
            return LiveFrameSource(self.live_source, source_id=self.video_id, fps=self.fps)
        if self.video_path is None:
            raise ValueError(f"La sesión '{self.video_id}' no tiene ni video ni cámara.")
        return VideoFileFrameSource(self.video_path, frame_stride=frame_stride)

    def describe_origin(self) -> str:
        """Texto corto para mostrar de dónde salen los frames."""
        if self.is_live:
            source = self.live_source
            if isinstance(source, int) or str(source).isdigit():
                return f"Webcam local #{source}"
            return f"Cámara de red · {source}"
        return f"Video: {self.title}"


def parse_live_source(text: str) -> Union[int, str]:
    """
    Interpreta lo que el usuario escribió como origen de cámara.

    Un número suelto es el índice de una webcam local ("0" es la integrada);
    cualquier otra cosa se trata como URL de stream. Se acepta `rtsp://` y
    también `http://…/video` (MJPEG), que es lo que sirven la mayoría de las
    aplicaciones que convierten un móvil en cámara IP.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError(
            "Escribe la dirección de la cámara (rtsp://… o http://…) o el "
            "número de una webcam local (0 para la integrada)."
        )
    if text.isdigit():
        return int(text)
    if "://" not in text:
        raise ValueError(
            f"'{text}' no parece ni una dirección de cámara ni un número de "
            "webcam. Una dirección se ve así: rtsp://192.168.1.42:8080/h264_ulaw.sdp"
        )
    return text
