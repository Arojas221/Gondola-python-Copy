"""
Carga de video y extracción de metadatos.
Esta capa NO hace UI ni limpieza: solo abre el archivo, valida que sea
legible y devuelve información estructurada (VideoInfo).

Punto de entrada de archivos de fuentes no confiables (el usuario sube lo
que quiera): además de validar que el video sea legible, `load_video`
rechaza lo que no es realmente un video (extensión falseada), lo que
podría colgar el proceso (contenedor corrupto/malformado) y lo que
reporta metadatos fuera de todo rango razonable (header manipulado). Ver
`app/utils/security.py` para el detalle de cada mecanismo.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2

from app.utils.config import (
    MAX_VIDEO_DURATION_SEC,
    MAX_VIDEO_FRAME_COUNT,
    MAX_VIDEO_HEIGHT,
    MAX_VIDEO_SIZE_MB,
    MAX_VIDEO_WIDTH,
    SUPPORTED_VIDEO_EXTENSIONS,
    VIDEO_LOAD_TIMEOUT_SEC,
)
from app.utils.security import has_valid_video_signature, run_with_timeout


@dataclass
class VideoInfo:
    path: Path
    filename: str
    duration_sec: float
    fps: float
    width: int
    height: int
    frame_count: int
    size_mb: float
    status: str = "cargado"          # cargado | limpiando | limpio | error
    error_message: Optional[str] = None
    thumbnail_path: Optional[Path] = None
    output_path: Optional[Path] = None
    cleaning_report: Optional[dict] = field(default=None)


class VideoLoadError(Exception):
    pass


def is_supported_video(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def _open_and_read_first_frame(path: Path) -> tuple[float, int, int, int]:
    """
    Abre el video y lee su primer frame para confirmar que es legible.
    Aislado en su propia función para poder correrlo bajo `run_with_timeout`
    (ver `load_video`) — el paso donde un contenedor corrupto se cuelga.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise VideoLoadError(f"No se pudo abrir el video (posible corrupción): {path.name}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise VideoLoadError(f"El video no tiene frames legibles: {path.name}")

    return fps, frame_count, width, height


def load_video(path: str | Path) -> VideoInfo:
    """
    Abre el video, extrae metadatos básicos y hace una validación rápida
    de que el archivo realmente se puede leer (no está corrupto en el
    header, no está vacío, etc.). No recorre todos los frames.

    Orden de las validaciones: primero las baratas y sin abrir el archivo
    (existencia, tipo, extensión, tamaño, firma de contenedor) y recién al
    final la que sí requiere invocar a OpenCV — así un archivo obviamente
    inválido nunca llega a esa parte más costosa (y potencialmente
    colgante) del proceso.
    """
    path = Path(path)

    if not path.exists():
        raise VideoLoadError(f"El archivo no existe: {path}")

    if not path.is_file():
        raise VideoLoadError(f"No es un archivo válido (¿carpeta, symlink roto o dispositivo?): {path}")

    if not is_supported_video(path):
        raise VideoLoadError(
            f"Formato no soportado: {path.suffix}. "
            f"Formatos válidos: {SUPPORTED_VIDEO_EXTENSIONS}"
        )

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb <= 0:
        raise VideoLoadError(f"El archivo está vacío: {path.name}")
    if MAX_VIDEO_SIZE_MB is not None and size_mb > MAX_VIDEO_SIZE_MB:
        raise VideoLoadError(
            f"El video pesa {size_mb:.1f} MB, supera el máximo permitido "
            f"de {MAX_VIDEO_SIZE_MB} MB: {path.name}"
        )

    # La extensión sola no prueba nada: un script o ejecutable renombrado a
    # ".mp4" pasaría el chequeo anterior. Se valida el encabezado real del
    # archivo contra el contenedor que dice ser.
    if not has_valid_video_signature(path):
        raise VideoLoadError(
            f"El archivo no parece ser un video {path.suffix} válido (la firma "
            f"del contenedor no coincide) — puede estar corrupto o ser un "
            f"archivo renombrado: {path.name}"
        )

    try:
        fps, frame_count, width, height = run_with_timeout(
            lambda: _open_and_read_first_frame(path),
            VIDEO_LOAD_TIMEOUT_SEC,
            f"Tiempo de espera agotado abriendo el video (posible archivo "
            f"corrupto o malformado): {path.name}",
        )
    except TimeoutError as exc:
        raise VideoLoadError(str(exc)) from exc

    if width <= 0 or height <= 0:
        raise VideoLoadError(f"El video reporta una resolución inválida ({width}x{height}): {path.name}")
    if width > MAX_VIDEO_WIDTH or height > MAX_VIDEO_HEIGHT:
        raise VideoLoadError(
            f"Resolución {width}x{height} supera el máximo soportado "
            f"({MAX_VIDEO_WIDTH}x{MAX_VIDEO_HEIGHT}) — posible header manipulado: {path.name}"
        )
    if frame_count < 0 or frame_count > MAX_VIDEO_FRAME_COUNT:
        raise VideoLoadError(
            f"El video reporta {frame_count} frames, fuera de todo rango "
            f"esperado (posible header corrupto/manipulado): {path.name}"
        )

    if fps <= 0:
        # Algunos contenedores no reportan fps correctamente; usamos un
        # valor por defecto conservador para no dividir por cero después.
        fps = 25.0

    duration_sec = frame_count / fps if fps > 0 else 0.0

    if MAX_VIDEO_DURATION_SEC is not None and duration_sec > MAX_VIDEO_DURATION_SEC:
        raise VideoLoadError(
            f"El video dura {duration_sec:.0f}s, supera el máximo permitido "
            f"de {MAX_VIDEO_DURATION_SEC}s: {path.name}"
        )

    return VideoInfo(
        path=path,
        filename=path.name,
        duration_sec=duration_sec,
        fps=fps,
        width=width,
        height=height,
        frame_count=frame_count,
        size_mb=round(size_mb, 2),
    )


def extract_thumbnail(video_info: VideoInfo, output_path: Path, frame_position_ratio: float = 0.1) -> Path:
    """
    Extrae un frame representativo (por defecto al 10% del video) y lo
    guarda como imagen para usarlo de preview en la UI.
    """
    def _seek_and_read() -> "cv2.typing.MatLike":
        cap = cv2.VideoCapture(str(video_info.path))
        if not cap.isOpened():
            cap.release()
            raise VideoLoadError(f"No se pudo reabrir el video para extraer miniatura: {video_info.filename}")
        target_frame = int(video_info.frame_count * frame_position_ratio)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise VideoLoadError(f"No se pudo extraer miniatura de: {video_info.filename}")
        return frame

    try:
        frame = run_with_timeout(
            _seek_and_read,
            VIDEO_LOAD_TIMEOUT_SEC,
            f"Tiempo de espera agotado extrayendo la miniatura de: {video_info.filename}",
        )
    except TimeoutError as exc:
        raise VideoLoadError(str(exc)) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), frame)
    return output_path
