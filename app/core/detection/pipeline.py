"""
Orquestador principal del pipeline de detección de Scapder Vision.

Consume una `FrameSource` (video limpio con frame_mapping, o cámara en
vivo con timestamps wall-clock) y orquesta: tracking, pose, señales de
zona, máquina de estados, trayectoria continua y publicación de eventos.
"""
from pathlib import Path
from typing import Callable, List, Optional, Union

from app.core.ingestion.frame_source import FrameSource, VideoFileFrameSource
from app.core.detection.tracker import PersonTracker
from app.core.detection.pose import PoseEstimator
from app.core.detection.zone import ZoneManager, check_zone_signal
from app.core.detection.state_machine import InteractionStateMachine
from app.core.detection.event_publisher import EventPublisher
from app.core.detection.trajectory import TrajectoryCapture, compute_foot_position
from app.core.detection.presence import DwellTracker
from app.core.detection.staff import StaffZoneTracker
from app.core.detection.schemas import PositionSample


class DetectionPipeline:
    """Orquesta el flujo de tracking, pose, validación de zonas, traducción y envío de eventos."""

    def __init__(
        self,
        tracker: PersonTracker,
        pose_estimator: PoseEstimator,
        zone_manager: ZoneManager,
        state_machine: InteractionStateMachine,
        event_publisher: EventPublisher,
        trajectory: Optional[TrajectoryCapture] = None,
        dwell_tracker: Optional[DwellTracker] = None,
        staff_tracker: Optional[StaffZoneTracker] = None,
    ):
        self.tracker = tracker
        self.pose_estimator = pose_estimator
        self.zone_manager = zone_manager
        self.state_machine = state_machine
        self.event_publisher = event_publisher
        self.trajectory = trajectory or TrajectoryCapture()
        self.dwell_tracker = dwell_tracker or DwellTracker()
        self.staff_tracker = staff_tracker or StaffZoneTracker()

    def run(
        self,
        source: Union[FrameSource, str, Path],
        progress_callback: Optional = None,
        frame_callback: Optional[Callable[..., None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Ejecuta el pipeline sobre una fuente de frames.

        Acepta un `FrameSource` (video con frame_mapping o cámara en vivo)
        o, por compatibilidad, una ruta a un video limpio: en ese caso se
        construye internamente un `VideoFileFrameSource`.
        `progress_callback(frame_index)` se invoca por cada frame procesado
        (opcional; usado por workers de QThread).
        `frame_callback(frame, tracked_people, pose_results)` se invoca por
        cada frame, justo después de tracking + pose (opcional; usado por
        la UI para mostrar el video anotado en vivo). Si no se pasa nada,
        el comportamiento del pipeline es idéntico al de antes de este
        parámetro.
        `should_stop()` se consulta al inicio de cada frame; si devuelve
        True, el loop termina de inmediato (igual que agotar la fuente) —
        permite cancelar un análisis en curso sin esperar a que termine el
        video completo (ej. `QThread.requestInterruption`, ver
        `DetectionPipelineWorker`).
        """
        if isinstance(source, (str, Path)):
            source = VideoFileFrameSource(source)

        zones = self.zone_manager.load_zones(source.video_id)
        if not zones:
            print(f"Advertencia: No hay zonas de góndola definidas para '{source.video_id}' en {self.zone_manager.storage_path}")

        frames_processed = 0
        try:
            while True:
                if should_stop and should_stop():
                    break

                sample = source.next_frame()
                if sample is None:
                    break

                frame_index = sample.frame_index

                # 1. Trackear personas
                tracked_people = self.tracker.track(sample.frame, frame_index)

                # 2. Estimar pose
                pose_results = self.pose_estimator.estimate(sample.frame, frame_index, tracked_people)

                # 2.5 Exponer frame + detecciones a quien llame el pipeline
                # (por ejemplo la UI, para dibujar cajas/keypoints en vivo).
                # No afecta el resto del flujo: es solo un "aviso" hacia afuera.
                if frame_callback:
                    frame_callback(sample.frame, tracked_people, pose_results)

                # 2.6 Estimar posición de pies, detectar staff y medir dwell time.
                # Se hace cada frame (no cada N frames como TrajectoryCapture)
                # porque tanto la detección de staff como el dwell time
                # necesitan precisión temporal fina para no perder entradas/
                # salidas cortas de una zona.
                for person in tracked_people:
                    foot_x, foot_y = compute_foot_position(person)
                    position_sample = PositionSample(
                        track_id=person.track_id,
                        frame_index=frame_index,
                        original_timestamp_sec=sample.timestamp_sec,
                        foot_position=(foot_x, foot_y),
                        camera_id=self.trajectory.camera_id,
                    )
                    is_emp = self.staff_tracker.update(position_sample, zones)
                    position_sample.is_employee = is_emp

                    dwell_records = self.dwell_tracker.update(
                        position_sample, zones, sample.timestamp_sec,
                    )
                    for dwell_record in dwell_records:
                        dwell_record.is_employee = self.staff_tracker.is_employee(dwell_record.track_id)
                        self.event_publisher.publish(dwell_record)

                # 3. Calcular señales de zona
                all_signals = []
                for pose in pose_results:
                    all_signals.extend(check_zone_signal(pose, zones))

                # 4. Pasar señales a la máquina de estados
                events = self.state_machine.process(all_signals)

                # 5. Traducir timestamps y publicar eventos de interacción
                for event in events:
                    # El timestamp ya viene traducido por la FrameSource
                    # (video original vía frame_mapping, o wall-clock en vivo)
                    event.timestamp = sample.timestamp_sec
                    event.is_employee = self.staff_tracker.is_employee(event.track_id)
                    self.event_publisher.publish(event)

                # 6. Publicar muestras de posición continua (heatmaps de circulación)
                trajectory_samples = self.trajectory.process(frame_index, tracked_people, sample.timestamp_sec)
                for position_sample in trajectory_samples:
                    position_sample.is_employee = self.staff_tracker.is_employee(position_sample.track_id)
                    self.event_publisher.publish(position_sample)

                frames_processed += 1
                if progress_callback:
                    progress_callback(frames_processed)
        finally:
            source.close()
            print(f"Procesamiento completado. Se procesaron {frames_processed} frames.")

    def run_video(self, video_path: str) -> None:
        """Conveniencia: corre el pipeline sobre una ruta de video limpio."""
        self.run(video_path)