"""
Worker de QThread para el pipeline de detección (Team 2).

Espejo del patrón de `app/core/ingestion/workers.py` (VideoCleaningWorker):
el pipeline corre en un hilo de fondo para que la publicación frecuente de
eventos (sobre todo el stream de `PositionSample`) nunca bloquee el hilo de
UI. Las señales Qt del `InProcessPublisher` llegan al hilo principal
automáticamente (conexiones en cola).
"""
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app.core.detection.pipeline import DetectionPipeline
from app.core.ingestion.frame_source import FrameSource


class DetectionPipelineWorker(QThread):
    progress_updated = Signal(int)   # frames procesados hasta ahora
    pipeline_finished = Signal(int)  # frames totales procesados
    pipeline_failed = Signal(str)    # mensaje de error

    # Frame anotable + detecciones de un frame procesado, reenviado desde el
    # hilo del pipeline hacia el hilo de UI (mismo mecanismo de conexión en
    # cola que progress_updated). Solo se emite si se pasó `frame_every_n`
    # al construir el worker; con frame_every_n=None (default) no se registra
    # ningún frame_callback y el comportamiento es idéntico al de antes de
    # este parámetro.
    # Orden de los argumentos: (frame, contador_de_llamada, tracked_people, pose_results)
    frame_processed = Signal(object, int, object, object)

    def __init__(
        self,
        pipeline: DetectionPipeline,
        source: FrameSource,
        parent=None,
        frame_every_n: Optional[int] = None,
    ):
        super().__init__(parent)
        self.pipeline = pipeline
        self.source = source
        self.frame_every_n = frame_every_n
        self._frames_processed = 0
        self._frame_call_count = 0

    def run(self):
        try:
            # pipeline.run() cierra la fuente al terminar (finally)
            frame_callback = self._on_frame if self.frame_every_n else None
            self.pipeline.run(
                self.source,
                progress_callback=self._on_progress,
                frame_callback=frame_callback,
                # `requestInterruption()`/`isInterruptionRequested()` es el
                # mecanismo estándar de QThread para pedir parar sin bloquear
                # quien lo pide — así el botón "Reiniciar" de la UI no tiene
                # que esperar a que el video termine de procesarse.
                should_stop=self.isInterruptionRequested,
            )
            self.pipeline_finished.emit(self._frames_processed)
        except Exception as exc:  # noqa: BLE001 - reportar cualquier fallo del pipeline
            self.pipeline_failed.emit(str(exc))

    def _on_progress(self, frame_index: int):
        self._frames_processed = frame_index
        self.progress_updated.emit(frame_index)

    def _on_frame(self, frame, tracked_people, pose_results):
        """Envuelve el `frame_callback` del pipeline: cuenta llamadas y solo
        emite `frame_processed` cada `frame_every_n` frames, para no saturar
        la cola de eventos de Qt con un frame por cada uno del video."""
        self._frame_call_count += 1
        if self._frame_call_count % self.frame_every_n != 0:
            return
        # Copia defensiva: `frame` es un buffer que el lector de video puede
        # reutilizar en la siguiente iteración, y este callback cruza al hilo
        # de UI de forma asíncrona (conexión en cola), no inmediata.
        self.frame_processed.emit(frame.copy(), self._frame_call_count, tracked_people, pose_results)