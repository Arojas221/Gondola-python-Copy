"""
Script de depuración visual para el pipeline de detección de Scapder Vision (Módulo 2).
Permite validar la detección, tracking, estimación de pose y estados en video real sin la UI de PySide6.
Usa `VideoFileFrameSource` (carga el frame_mapping del sidecar y traduce timestamps automáticamente).
"""
import argparse
from pathlib import Path
import cv2
import numpy as np

from app.core.ingestion.frame_source import VideoFileFrameSource
from app.core.detection.tracker import PersonTracker
from app.core.detection.pose import PoseEstimator
from app.core.detection.zone import ZoneManager, check_zone_signal
from app.core.detection.state_machine import InteractionStateMachine, InteractionState
from app.core.detection.event_publisher import LocalEventPublisher

def parse_args():
    parser = argparse.ArgumentParser(description="Validación visual del pipeline de detección.")
    parser.add_argument(
        "--video",
        type=str,
        required=True,
        help="Ruta al video limpio (.mp4) a procesar.",
    )
    return parser.parse_args()

def main():
    args = parse_args()
    video_path = Path(args.video)

    # La framemapping del frame_mapping (sidecar .json) la maneja la fuente
    source = VideoFileFrameSource(video_path)

    # Inicializar componentes del pipeline (excepto state_machine que requiere fps)
    tracker = PersonTracker()
    pose_estimator = PoseEstimator()
    zone_manager = ZoneManager()
    event_publisher = LocalEventPublisher(mode="stdout")

    zones = zone_manager.load_zones(source.video_id)
    print(f"Zonas cargadas para '{source.video_id}': {[z.name for z in zones]}")

    fps = source.fps
    # Instanciar state_machine con fps real del video
    state_machine = InteractionStateMachine(fps=fps)
    cv2.namedWindow("Scapder Vision - Debug Pipeline", cv2.WINDOW_NORMAL)

    frame_index = 0
    while True:
        sample = source.next_frame()
        if sample is None:
            break

        frame = sample.frame
        frame_index = sample.frame_index

        # 1. Ejecutar tracking de personas
        tracked_people = tracker.track(frame, frame_index)

        # 2. Estimar Pose
        pose_results = pose_estimator.estimate(frame, frame_index, tracked_people)

        # 3. Evaluar señales de zonas
        all_signals = []
        for pose in pose_results:
            signals = check_zone_signal(pose, zones)
            all_signals.extend(signals)

        # 4. Procesar señales en la máquina de estados
        events = state_machine.process(all_signals)

        # 5. Traducir y publicar eventos (timestamp ya traducido por la fuente)
        for event in events:
            event.timestamp = sample.timestamp_sec
            event_publisher.publish(event)

        # --- DIBUJADO DE DEPURACIÓN (Visualización local) ---
        # A. Dibujar zonas
        for zone in zones:
            if len(zone.polygon) >= 3:
                pts = np.array(zone.polygon, dtype=np.int32)
                # Dibujar polígono en verde
                cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                # Colocar el nombre de la zona
                cv2.putText(
                    frame,
                    zone.name,
                    (int(zone.polygon[0][0]), int(zone.polygon[0][1]) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

        # B. Dibujar personas trackeadas, pose y estados
        for person in tracked_people:
            tid = person.track_id
            bbox = person.bbox
            x1, y1, x2, y2 = map(int, bbox)

            # Obtener el estado consolidado de la persona (si está interactuando con alguna zona)
            current_state = InteractionState.IDLE
            active_zone = ""
            for (t_id, z_id), (state, _) in state_machine.states.items():
                if t_id == tid and state != InteractionState.IDLE:
                    current_state = state
                    active_zone = z_id
                    break

            # Determinar color de caja según el estado
            if current_state == InteractionState.HOLDING:
                color = (0, 0, 255)  # Rojo para HOLDING
                label = f"ID: {tid} - HOLDING ({active_zone})"
            elif current_state == InteractionState.REACHING:
                color = (0, 255, 255)  # Amarillo para REACHING
                label = f"ID: {tid} - REACHING ({active_zone})"
            else:
                color = (255, 0, 0)  # Azul para IDLE
                label = f"ID: {tid}"

            # Dibujar bounding box de la persona
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        # C. Dibujar los keypoints de pose asociados
        for pose in pose_results:
            # Dibujar articulaciones de interés
            joints = [
                pose.left_shoulder, pose.right_shoulder,
                pose.left_elbow, pose.right_elbow,
                pose.left_wrist, pose.right_wrist
            ]
            for kp in joints:
                if kp.confidence > 0.3:
                    cv2.circle(
                        frame,
                        (int(kp.x), int(kp.y)),
                        5,
                        (0, 255, 255),
                        -1
                    )
            
            # Dibujar líneas de brazos (hombro -> codo -> muñeca)
            # Brazo izquierdo
            if pose.left_shoulder.confidence > 0.3 and pose.left_elbow.confidence > 0.3:
                cv2.line(
                    frame,
                    (int(pose.left_shoulder.x), int(pose.left_shoulder.y)),
                    (int(pose.left_elbow.x), int(pose.left_elbow.y)),
                    (255, 128, 0),
                    2
                )
            if pose.left_elbow.confidence > 0.3 and pose.left_wrist.confidence > 0.3:
                cv2.line(
                    frame,
                    (int(pose.left_elbow.x), int(pose.left_elbow.y)),
                    (int(pose.left_wrist.x), int(pose.left_wrist.y)),
                    (255, 128, 0),
                    2
                )
            # Brazo derecho
            if pose.right_shoulder.confidence > 0.3 and pose.right_elbow.confidence > 0.3:
                cv2.line(
                    frame,
                    (int(pose.right_shoulder.x), int(pose.right_shoulder.y)),
                    (int(pose.right_elbow.x), int(pose.right_elbow.y)),
                    (0, 128, 255),
                    2
                )
            if pose.right_elbow.confidence > 0.3 and pose.right_wrist.confidence > 0.3:
                cv2.line(
                    frame,
                    (int(pose.right_elbow.x), int(pose.right_elbow.y)),
                    (int(pose.right_wrist.x), int(pose.right_wrist.y)),
                    (0, 128, 255),
                    2
                )

        # Mostrar frame
        cv2.imshow("Scapder Vision - Debug Pipeline", frame)
        frame_index += 1

        # Presionar 'q' para salir
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    source.close()
    cv2.destroyAllWindows()
    print(f"Depuración terminada. Se procesaron {frame_index} frames.")

if __name__ == "__main__":
    main()
