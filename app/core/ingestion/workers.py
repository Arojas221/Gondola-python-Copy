"""
Workers de QThread. Cualquier tarea pesada (limpieza de video, elección
del frame de referencia, sugerencia de ROI) debe correr aquí, nunca en el
hilo de UI.
"""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.core.ingestion.video_cleaner import clean_video
from app.core.ingestion.video_loader import VideoInfo


class VideoCleaningWorker(QThread):
    progress_updated = Signal(str, int, int)   # filename, frame_actual, frame_total
    video_finished = Signal(str, dict)         # filename, reporte como dict
    video_failed = Signal(str, str)            # filename, mensaje de error
    all_finished = Signal()

    def __init__(self, videos: list[VideoInfo], parent=None):
        super().__init__(parent)
        self.videos = videos

    def run(self):
        for video_info in self.videos:
            filename = video_info.filename
            try:
                def _on_progress(current, total, fn=filename):
                    self.progress_updated.emit(fn, current, total)

                report = clean_video(video_info, progress_callback=_on_progress)
                self.video_finished.emit(filename, report.as_dict())
            except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo por video
                self.video_failed.emit(filename, str(exc))

        self.all_finished.emit()


class LiveSessionWorker(QThread):
    """
    Conecta con una cámara en directo y prepara su sesión.

    Corre en un hilo porque abrir un stream RTSP puede tardar varios
    segundos (o quedarse esperando hasta el timeout si la dirección está
    mal), y bloquear la interfaz mientras tanto haría parecer que la
    aplicación se colgó justo cuando el usuario más duda de si escribió
    bien la URL.
    """

    session_ready = Signal(object)   # AnalysisSession
    failed = Signal(str)
    progress_note = Signal(str)

    def __init__(self, source, video_id: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.video_id = video_id

    def run(self):
        from app.core.detection.roi_suggester import build_product_detector, suggest_zones
        from app.core.ingestion.frame_source import grab_reference_frame
        from app.core.ingestion.session import AnalysisSession

        try:
            self.progress_note.emit(f"Conectando con {self.source}…")
            frame, fps = grab_reference_frame(self.source)
            if frame is None:
                self.failed.emit(
                    "No se pudo abrir la cámara. Comprueba que el equipo y la "
                    "cámara estén en la misma red y que la red no aísle a los "
                    "dispositivos entre sí (es lo habitual en redes de "
                    "universidad: usa el punto de acceso del móvil)."
                )
                return

            height, width = frame.shape[:2]
            self.progress_note.emit(
                f"Conectado: {width}x{height} a {fps:.0f} fps. Proponiendo zonas…"
            )

            try:
                product_detector = build_product_detector()
            except Exception:  # noqa: BLE001 - la sugerencia por bordes funciona igual
                product_detector = None

            zones = suggest_zones(frame, self.video_id, product_detector=product_detector)
            self.session_ready.emit(AnalysisSession.from_live(
                video_id=self.video_id,
                source=self.source,
                fps=fps,
                reference_frame=frame,
                suggested_zones=zones,
            ))
        except Exception as exc:  # noqa: BLE001 - reportar cualquier fallo a la UI
            self.failed.emit(str(exc))


class ReferenceFrameWorker(QThread):
    """
    Prepara la sesión para la pestaña de zonas, sobre el video ya limpio.

    Hace las dos cosas caras que no pueden correr en el hilo de UI:

    1. Elegir un frame de referencia bueno (nítido y con la góndola lo más
       despejada posible) en vez del arbitrario "frame al 10%".
    2. Proponer zonas de góndola sobre ese frame.

    Los modelos de YOLO se cargan aquí dentro y no al importar el módulo:
    cargarlos tarda varios segundos y solo hacen falta cuando realmente se
    va a preparar una sesión.
    """

    session_ready = Signal(object)   # AnalysisSession
    failed = Signal(str)
    progress_note = Signal(str)

    def __init__(self, video_id: str, clean_video_path: Path, fps: float, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.clean_video_path = Path(clean_video_path)
        self.fps = fps

    def run(self):
        # Imports locales: mantienen `workers.py` importable (y la app
        # arrancable) aunque ultralytics tarde o falle en cargar.
        from app.core.detection.roi_suggester import build_product_detector, suggest_zones
        from app.core.ingestion.frame_picker import build_people_detector, pick_reference_frame

        try:
            self.progress_note.emit("Buscando el mejor frame de referencia...")
            try:
                people_detector = build_people_detector()
            except Exception as exc:  # noqa: BLE001 - sin modelo seguimos solo por nitidez
                people_detector = None
                self.progress_note.emit(
                    f"Aviso: sin detector de personas ({exc}); se elige el frame solo por nitidez."
                )

            reference = pick_reference_frame(self.clean_video_path, people_detector=people_detector)
            if reference is None:
                self.failed.emit(f"No se pudo leer el video limpio: {self.clean_video_path.name}")
                return

            self.progress_note.emit(
                f"Frame #{reference.frame_index} elegido entre {reference.candidates} candidatos "
                f"({reference.people} persona(s) en cuadro). Proponiendo zonas..."
            )

            try:
                product_detector = build_product_detector()
            except Exception:  # noqa: BLE001 - la sugerencia por bordes funciona igual
                product_detector = None

            zones = suggest_zones(reference.frame, self.video_id, product_detector=product_detector)

            from app.core.ingestion.session import AnalysisSession
            self.session_ready.emit(AnalysisSession.from_video(
                video_id=self.video_id,
                video_path=self.clean_video_path,
                fps=float(self.fps),
                reference_frame=reference.frame,
                suggested_zones=zones,
            ))
        except Exception as exc:  # noqa: BLE001 - reportar cualquier fallo a la UI
            self.failed.emit(str(exc))
