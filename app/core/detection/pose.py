"""
Estimación de pose y extracción de keypoints corporales usando YOLO-Pose de Ultralytics.
"""
from typing import List, Optional
import numpy as np
from ultralytics import YOLO

from app.core.detection.schemas import PoseResult, Keypoint, TrackedPerson
from app.utils.config import POSE_MODEL_NAME, POSE_TRACK_MATCH_IOU_MIN, POSE_TRACK_MATCH_MAX_DIST_SQ

class PoseEstimator:
    """Encapsula el modelo YOLO-Pose para extraer articulaciones de personas trackeadas."""

    def __init__(self, model_name: str = POSE_MODEL_NAME):
        # Carga el modelo YOLO-Pose una sola vez
        self.model = YOLO(model_name)

    def estimate(self, frame: np.ndarray, frame_index: int, tracked_people: List[TrackedPerson]) -> List[PoseResult]:
        """
        Estima la pose en el frame y asocia los resultados a las personas trackeadas por proximidad/IoU.
        """
        if not tracked_people:
            return []

        results = self.model(frame, verbose=False)
        pose_results = []

        for result in results:
            if result.keypoints is None or result.boxes is None:
                continue

            # Verificar que conf esté disponible
            if result.keypoints.conf is None:
                continue

            # Obtenemos las coordenadas de las bboxes y keypoints estimadas por el modelo de pose
            pose_boxes = result.boxes.xyxy.cpu().tolist()
            # xy: (N, 17, 2), conf: (N, 17)
            keypoints_xy = result.keypoints.xy.cpu().tolist()
            keypoints_conf = result.keypoints.conf.cpu().tolist()

            for i, pose_box in enumerate(pose_boxes):
                # Encontrar a qué persona trackeada corresponde esta pose usando IoU
                matched_track = self._match_pose_to_track(pose_box, tracked_people)
                if matched_track is None:
                    continue

                kps = keypoints_xy[i]
                confs = keypoints_conf[i]

                # Asegurarse de tener suficientes keypoints (COCO tiene 17)
                if len(kps) < 17:
                    continue

                # COCO Keypoints índices:
                # 5: left_shoulder, 6: right_shoulder
                # 7: left_elbow,    8: right_elbow
                # 9: left_wrist,    10: right_wrist
                
                left_shoulder = Keypoint(x=kps[5][0], y=kps[5][1], confidence=confs[5])
                right_shoulder = Keypoint(x=kps[6][0], y=kps[6][1], confidence=confs[6])
                left_elbow = Keypoint(x=kps[7][0], y=kps[7][1], confidence=confs[7])
                right_elbow = Keypoint(x=kps[8][0], y=kps[8][1], confidence=confs[8])
                left_wrist = Keypoint(x=kps[9][0], y=kps[9][1], confidence=confs[9])
                right_wrist = Keypoint(x=kps[10][0], y=kps[10][1], confidence=confs[10])

                pose_results.append(
                    PoseResult(
                        track_id=matched_track.track_id,
                        frame_index=frame_index,
                        left_wrist=left_wrist,
                        right_wrist=right_wrist,
                        left_elbow=left_elbow,
                        right_elbow=right_elbow,
                        left_shoulder=left_shoulder,
                        right_shoulder=right_shoulder,
                    )
                )

        return pose_results

    def _match_pose_to_track(self, pose_box: List[float], tracked_people: List[TrackedPerson]) -> Optional[TrackedPerson]:
        """Asocia la pose a la persona trackeada usando la mayor coincidencia de Bounding Box (IoU)."""
        best_iou = 0.0
        best_match = None

        for person in tracked_people:
            iou = self._calculate_iou(pose_box, person.bbox)
            if iou > best_iou:
                best_iou = iou
                best_match = person

        # Si el IoU es aceptable, hacemos match
        if best_iou >= POSE_TRACK_MATCH_IOU_MIN:
            return best_match
            
        # Fallback por distancia del centroide si no hay solapamiento significativo
        best_dist = float("inf")
        best_dist_match = None
        pose_center_x = (pose_box[0] + pose_box[2]) / 2.0
        pose_center_y = (pose_box[1] + pose_box[3]) / 2.0
        
        for person in tracked_people:
            person_center_x = (person.bbox[0] + person.bbox[2]) / 2.0
            person_center_y = (person.bbox[1] + person.bbox[3]) / 2.0
            dist = (pose_center_x - person_center_x) ** 2 + (pose_center_y - person_center_y) ** 2
            if dist < best_dist:
                best_dist = dist
                best_dist_match = person
                
        # Umbral razonable de distancia cuadrada de centroides
        if best_dist < POSE_TRACK_MATCH_MAX_DIST_SQ:
            return best_dist_match

        return None

    def _calculate_iou(self, boxA: List[float], boxB: tuple) -> float:
        """Calcula el Intersection over Union (IoU) entre dos bounding boxes."""
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0.0, xB - xA) * max(0.0, yB - yA)
        if interArea == 0.0:
            return 0.0

        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

        iou = interArea / float(boxAArea + boxBArea - interArea)
        return iou
