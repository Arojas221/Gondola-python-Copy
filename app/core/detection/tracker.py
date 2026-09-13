"""
Tracking de personas utilizando el tracker integrado de Ultralytics (ByteTrack).

Nota de diseño:
Este módulo utiliza su propia instancia de YOLO con el tracking activado (.track) para
mantener los track_ids estables a lo largo del video. Se separa de detector.py para
permitir que detector.py sea un componente de detección pura reusable (sin el overhead
de mantener estados de tracking) mientras que tracker.py se encarga de la persistencia temporal.
"""
from typing import List
import numpy as np
from ultralytics import YOLO

from app.core.detection.schemas import TrackedPerson
from app.utils.config import DETECTION_MODEL_NAME, DETECTION_CONF_THRESHOLD, DETECTION_IOU_THRESHOLD, TRACKER_CONFIG

class PersonTracker:
    """Administra el tracking persistente de personas entre frames."""

    def __init__(self, model_name: str = DETECTION_MODEL_NAME, tracker_config: str = TRACKER_CONFIG):
        self.model = YOLO(model_name)
        self.tracker_config = tracker_config

    def track(self, frame: np.ndarray, frame_index: int) -> List[TrackedPerson]:
        """
        Realiza el seguimiento de personas en el frame.
        Retorna la lista de personas trackeadas con su respectivo track_id.
        """
        results = self.model.track(
            frame,
            persist=True,
            tracker=self.tracker_config,
            conf=DETECTION_CONF_THRESHOLD,
            iou=DETECTION_IOU_THRESHOLD,
            classes=[0],  # 0 es la clase 'persona' en COCO
            verbose=False
        )
        
        tracked_people = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                # Verificar si tiene ID de tracking asignado
                if box.id is None:
                    continue

                track_id = int(box.id[0].item())
                conf = float(box.conf[0].item())
                
                # xyxy es una tupla/lista [x1, y1, x2, y2]
                xyxy = box.xyxy[0].cpu().tolist()
                bbox = (xyxy[0], xyxy[1], xyxy[2], xyxy[3])

                tracked_people.append(
                    TrackedPerson(
                        bbox=bbox,
                        confidence=conf,
                        frame_index=frame_index,
                        track_id=track_id
                    )
                )

        return tracked_people
