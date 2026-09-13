"""
Fuentes de frames para el pipeline de detección (Team 1).

Abstracción que desacopla el pipeline del tipo de entrada:

- `VideoFileFrameSource`: video limpio de `data/processed/` con su
  `frame_mapping.json` al lado — traduce el timestamp de cada frame al
  video original reutilizando `app.core.detection.frame_mapping` (no se
  duplica esa lógica aquí).
- `LiveFrameSource`: cámara en vivo — webcam local, RTSP de una cámara
  IP o MJPEG por HTTP. No hay "video original" al que mapear: los
  timestamps son los segundos transcurridos desde que se conectó.

El pipeline solo consume `FrameSource`, así que el resto del sistema
no sabe ni le importa si el origen es archivo o cámara.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union
import json
import os
import time

import cv2
import numpy as np

from app.core.detection.frame_mapping import translate_to_original_timestamp


@dataclass
class FrameSample:
    """Un frame listo para procesar, con su índice y timestamp resuelto."""
    frame: np.ndarray
    frame_index: int
    timestamp_sec: float  # Segundos en el video original (o wall-clock en vivo)


class FrameSource(ABC):
    """Interfaz de fuente de frames: el pipeline itera con `next_frame()`."""

    @property
    @abstractmethod
    def fps(self) -> float:
        """Frames por segundo del stream (usado para la máquina de estados)."""
        pass

    @property
    @abstractmethod
    def video_id(self) -> str:
        """Identificador de esta fuente (nombre de archivo o id de cámara), usado para
        cargar solo las zonas que le corresponden y no mezclarlas con las de otro video/cámara."""
        pass

    @property
    def is_live(self) -> bool:
        """
        True si la fuente es una cámara en directo.

        Cambia dos cosas para quien la consume: no hay un total de frames
        que permita calcular un porcentaje de avance, y el análisis no
        termina solo — hay que detenerlo.
        """
        return False

    @abstractmethod
    def next_frame(self) -> Optional[FrameSample]:
        """Devuelve el siguiente frame o None cuando el stream se agota."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Libera recursos (cap, socket, etc.)."""
        pass


class VideoFileFrameSource(FrameSource):
    """Lector de video limpio + `frame_mapping.json` (Módulo 1).

    Si no se pasa `frame_mapping`, intenta cargar el `.json` con el mismo
    nombre que el video. Si tampoco existe, los timestamps caen a un
    fallback por FPS (comportamiento actual del pipeline).
    """

    def __init__(
        self,
        video_path: Union[str, Path],
        frame_mapping: Optional[List[Dict]] = None,
        fps: Optional[float] = None,
        frame_stride: int = 1,
    ):
        """
        `frame_stride` procesa 1 de cada N frames del video limpio. Con N=1
        (default) el comportamiento es el de siempre. Con N>1 los frames
        intermedios se saltan con `cap.grab()` — se avanza el decodificador
        sin decodificar la imagen, que es lo caro — pero el contador de
        frames sigue avanzando de uno en uno, así que el `frame_mapping`
        (y con él el timestamp del video original) sigue siendo exacto.
        """
        video_path_obj = Path(video_path)
        if not video_path_obj.exists():
            raise FileNotFoundError(f"No se encontró el video: {video_path}")

        self.video_path = video_path_obj
        self._video_id = video_path_obj.stem
        self.cap = cv2.VideoCapture(str(video_path_obj))
        if not self.cap.isOpened():
            raise IOError(f"No se pudo abrir el archivo de video: {video_path}")

        self._fps = fps or (self.cap.get(cv2.CAP_PROP_FPS) or 30.0)

        # Cargar el frame_mapping si no se pasó explícitamente
        if frame_mapping is None:
            json_path = video_path_obj.with_suffix(".json")
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        self.frame_mapping = json.load(f).get("frame_mapping", [])
                except Exception as e:
                    print(f"Advertencia: No se pudo leer el mapeo de frames desde {json_path}: {e}")
                    self.frame_mapping = []
            else:
                self.frame_mapping = []
        else:
            self.frame_mapping = frame_mapping

        if not self.frame_mapping:
            print(
                "Advertencia: Ejecutando sin mapeo de frames. "
                "Los timestamps serán aproximados al frame rate del video limpio."
            )

        self._frame_index = 0
        self._frame_stride = max(1, int(frame_stride))

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def video_id(self) -> str:
        return self._video_id

    @property
    def frame_stride(self) -> int:
        return self._frame_stride

    def next_frame(self) -> Optional[FrameSample]:
        # Saltar los frames intermedios sin decodificarlos (grab), pero
        # contándolos: el índice tiene que seguir correspondiendo al frame
        # real del video limpio para que `frame_mapping` lo traduzca bien.
        for _ in range(self._frame_stride - 1):
            if not self.cap.grab():
                return None
            self._frame_index += 1

        ret, frame = self.cap.read()
        if not ret:
            return None

        frame_index = self._frame_index
        self._frame_index += 1

        if self.frame_mapping:
            timestamp_sec = translate_to_original_timestamp(frame_index, self.frame_mapping)
        else:
            timestamp_sec = frame_index / self._fps

        return FrameSample(frame=frame, frame_index=frame_index, timestamp_sec=timestamp_sec)

    def close(self) -> None:
        self.cap.release()


class LiveFrameSource(FrameSource):
    """
    Cámara en vivo: webcam local, RTSP de una cámara IP, o MJPEG por HTTP.

    Diferencias de fondo con un archivo de video, que explican casi todo lo
    que hay aquí:

    - **No hay `frame_mapping`.** No existe una grabación original a la que
      volver, así que el `timestamp_sec` es el reloj de la sesión (segundos
      desde que se conectó). Se usa un reloj monotónico y no la hora del
      sistema: si el equipo ajusta la hora a mitad de un análisis, los
      timestamps no pueden saltar hacia atrás.
    - **El stream no "termina", se corta.** Un archivo se acaba y ya; una
      cámara puede fallar un frame por congestión de la red y seguir viva.
      Por eso una lectura fallida no cierra la fuente: se reintenta hasta
      `max_read_retries` veces antes de darla por terminada.
    - **Los frames viejos no sirven.** El buffer interno de OpenCV
      acumula frames mientras el pipeline procesa; sin bajarlo a 1, el
      análisis se va quedando cada vez más atrás del tiempo real.
    """

    # Tamaño de búfer de captura: solo interesa el frame más reciente.
    BUFFER_SIZE = 1
    # Lecturas fallidas seguidas que se toleran antes de dar el stream por
    # muerto. A ~30 fps son unos dos segundos de margen.
    DEFAULT_MAX_RETRIES = 60
    # Espera entre reintentos, para no quemar CPU con un stream caído.
    RETRY_SLEEP_SEC = 0.05

    def __init__(
        self,
        source: Union[int, str] = 0,
        source_id: str = "camara_vivo",
        fps: Optional[float] = None,
        max_read_retries: int = DEFAULT_MAX_RETRIES,
        open_timeout_sec: float = 10.0,
    ):
        """
        `source` es un índice de webcam (0, 1, ...) o una URL de stream
        (`rtsp://...`, `http://.../video`). `source_id` es el identificador
        de la sesión: con él se guardan y se buscan las zonas, así que tiene
        que ser el mismo que use el editor.
        """
        self.source = source
        self.source_id = source_id
        self._max_read_retries = max(1, int(max_read_retries))

        self.cap = self._open_capture(source, open_timeout_sec)
        if not self.cap.isOpened():
            self.cap.release()
            raise IOError(
                f"No se pudo abrir la fuente de video en vivo: {source}. "
                "Revisa que la cámara esté conectada o que la URL sea "
                "accesible desde este equipo (misma red, sin aislamiento "
                "de clientes)."
            )

        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.BUFFER_SIZE)
        except Exception:  # noqa: BLE001 - no todos los backends lo soportan
            pass

        # Muchas cámaras RTSP reportan 0 o un valor absurdo: en ese caso se
        # usa un valor razonable en vez de propagar la basura a la máquina
        # de estados, cuyos umbrales están expresados en frames.
        reported = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        self._fps = float(fps) if fps else (reported if 1.0 <= reported <= 120.0 else 30.0)

        self._frame_index = 0
        self._start = time.monotonic()
        self._closed = False

    @staticmethod
    def _open_capture(source: Union[int, str], open_timeout_sec: float):
        """
        Abre la captura eligiendo el backend adecuado.

        Para URLs se fuerza FFMPEG y se pide transporte TCP: por UDP, que es
        el default de RTSP, el Wi-Fi pierde paquetes y la imagen llega
        troceada o directamente no llega.
        """
        if isinstance(source, int):
            return cv2.VideoCapture(source)
        text = str(source).strip()
        if text.isdigit():
            return cv2.VideoCapture(int(text))
        if "://" in text:
            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                f"rtsp_transport;tcp|stimeout;{int(open_timeout_sec * 1_000_000)}",
            )
            return cv2.VideoCapture(text, cv2.CAP_FFMPEG)
        # Una ruta de archivo también vale como "fuente en vivo": permite
        # ensayar el modo directo sin cámara, y es lo que usan los tests.
        return cv2.VideoCapture(text)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def video_id(self) -> str:
        return self.source_id

    @property
    def is_live(self) -> bool:
        return True

    def next_frame(self) -> Optional[FrameSample]:
        """
        Devuelve el frame más reciente, o None si el stream se cortó.

        Un fallo aislado de lectura no termina la sesión: se reintenta,
        porque en una cámara por Wi-Fi los cortes de un frame son normales.
        """
        if self._closed:
            return None

        for _ in range(self._max_read_retries):
            ok, frame = self.cap.read()
            if ok and frame is not None:
                frame_index = self._frame_index
                self._frame_index += 1
                return FrameSample(
                    frame=frame,
                    frame_index=frame_index,
                    timestamp_sec=time.monotonic() - self._start,
                )
            time.sleep(self.RETRY_SLEEP_SEC)

        return None

    def close(self) -> None:
        self._closed = True
        try:
            self.cap.release()
        except Exception:  # noqa: BLE001 - ya liberada o backend en teardown
            pass


def grab_reference_frame(
    source: Union[int, str],
    warmup_frames: int = 8,
    open_timeout_sec: float = 10.0,
):
    """
    Captura un frame de una fuente en vivo, para usarlo como referencia al
    dibujar las zonas.

    Descarta los primeros `warmup_frames`: una webcam entrega los primeros
    cuadros con la exposición y el balance de blancos todavía ajustándose, y
    un frame oscuro o lavado es justo el peor punto de partida para dibujar
    zonas y para el sugeridor automático de ROI.

    Devuelve `(frame, fps)` o `(None, 0.0)` si la fuente no se pudo abrir.
    """
    probe = None
    try:
        probe = LiveFrameSource(source, open_timeout_sec=open_timeout_sec)
    except IOError:
        return None, 0.0

    try:
        best = None
        for _ in range(max(1, warmup_frames)):
            sample = probe.next_frame()
            if sample is None:
                break
            best = sample.frame
        return (best.copy() if best is not None else None), probe.fps
    finally:
        probe.close()
