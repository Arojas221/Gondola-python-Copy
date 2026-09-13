"""
Limpieza de video.

Qué hace "limpiar" en este proyecto (etapa 0 del pipeline, previa a
detección/tracking):
  1. Elimina frames negros (cortes de señal, tapado de cámara).
  2. Elimina frames "congelados" (cámara trabada repitiendo el mismo frame).
  3. Normaliza FPS y/o resolución si se configura (útil para que todos los
     videos que entren al pipeline de CV tengan el mismo formato).
  4. Reencoda a un contenedor/codec consistente.

No hace nada de detección de personas ni tracking: esa es la siguiente
etapa del pipeline (futuro módulo `app/core/detector.py`).
"""
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from app.core.ingestion.video_loader import VideoInfo, VideoLoadError
from app.utils import config


@dataclass
class CleaningReport:
    frames_read: int = 0
    frames_written: int = 0
    black_frames_removed: int = 0
    frozen_frames_removed: int = 0
    output_fps: float = 0.0
    output_resolution: tuple = (0, 0)
    output_path: str = ""

    # Mapeo: cada posicion es un frame del video LIMPIO (en orden), y el
    # valor es el numero de frame que ese mismo contenido tenia en el
    # video ORIGINAL. Necesario porque al quitar frames negros/congelados
    # los indices se corren, y esa correspondencia no se puede reconstruir
    # despues de limpiar.
    frame_mapping: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Optional[Path] = None) -> Path:
        """
        Guarda este reporte (incluido el mapeo de frames) como JSON junto
        al video limpio, para que quede como evidencia y para que otras
        etapas del pipeline lo puedan leer sin reprocesar el video.
        """
        path = path or Path(self.output_path).with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.as_dict(), f, indent=2, ensure_ascii=False)
        return path


ProgressCallback = Callable[[int, int], None]  # (frame_actual, frame_total)


def _is_black_frame(frame: np.ndarray) -> bool:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray)) < config.BLACK_FRAME_MEAN_THRESHOLD


def _frames_are_frozen(frame_a: np.ndarray, frame_b: np.ndarray) -> bool:
    diff = cv2.absdiff(
        cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY),
    )
    return float(np.std(diff)) < config.FROZEN_FRAME_STD_THRESHOLD


def clean_video(
    video_info: VideoInfo,
    output_dir: Optional[Path] = None,
    target_fps: Optional[float] = config.DEFAULT_TARGET_FPS,
    target_resolution: Optional[tuple] = config.DEFAULT_TARGET_RESOLUTION,
    progress_callback: Optional[ProgressCallback] = None,
) -> CleaningReport:
    """
    Recorre el video frame a frame, descarta frames negros/congelados y
    escribe un video limpio y normalizado en output_dir.
    """
    output_dir = output_dir or config.PROCESSED_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_info.path))
    if not cap.isOpened():
        raise VideoLoadError(f"No se pudo abrir el video para limpieza: {video_info.filename}")

    out_fps = target_fps or video_info.fps
    out_width, out_height = target_resolution or (video_info.width, video_info.height)

    output_path = output_dir / f"{video_info.path.stem}_clean{config.OUTPUT_EXTENSION}"
    fourcc = cv2.VideoWriter_fourcc(*config.OUTPUT_CODEC)
    writer = cv2.VideoWriter(str(output_path), fourcc, out_fps, (out_width, out_height))

    report = CleaningReport(
        output_fps=out_fps,
        output_resolution=(out_width, out_height),
        output_path=str(output_path),
    )

    prev_frame = None
    consecutive_frozen = 0
    total_frames = video_info.frame_count or 1

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_idx += 1
        report.frames_read += 1

        if progress_callback:
            progress_callback(frame_idx, total_frames)

        # --- Filtro 1: frame negro ---
        if _is_black_frame(frame):
            report.black_frames_removed += 1
            prev_frame = frame
            continue

        # --- Filtro 2: frame congelado (cámara trabada) ---
        if prev_frame is not None and _frames_are_frozen(frame, prev_frame):
            consecutive_frozen += 1
            if consecutive_frozen >= config.MAX_CONSECUTIVE_FROZEN_FRAMES:
                report.frozen_frames_removed += 1
                prev_frame = frame
                continue
        else:
            consecutive_frozen = 0

        # --- Normalización de resolución ---
        if (frame.shape[1], frame.shape[0]) != (out_width, out_height):
            frame = cv2.resize(frame, (out_width, out_height))

        writer.write(frame)

        # Antes de este frame se escribieron report.frames_written frames,
        # asi que esta es su posicion (0-indexada) en el video limpio.
        clean_frame_idx = report.frames_written
        original_frame_idx = frame_idx - 1  # frame_idx ya se incremento arriba
        report.frame_mapping.append({
            "clean_frame": clean_frame_idx,
            "original_frame": original_frame_idx,
            "original_timestamp_sec": round(original_frame_idx / video_info.fps, 3),
        })

        report.frames_written += 1
        prev_frame = frame

    cap.release()
    writer.release()

    report.save()

    return report