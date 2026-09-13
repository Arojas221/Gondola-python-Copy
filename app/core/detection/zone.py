"""
Gestión de zonas de góndola y operaciones geométricas.
"""
import json
import math
from pathlib import Path
from typing import Dict, List
from shapely.geometry import Point, Polygon

from app.core.detection.schemas import Zone, ZoneSignal, PoseResult, Keypoint
from app.utils.config import ZONES_STORAGE_PATH, ARM_EXTENSION_MIN_RATIO, MIN_KEYPOINT_CONFIDENCE
from app.utils.security import sanitize_filename_component

# Cache de objetos Polygon de Shapely, para no reconstruirlos en cada llamada:
# se invoca por cada persona, por cada zona, en cada frame del video, y
# Polygon(zone.polygon) tiene un costo de construcción no trivial que no
# vale la pena repetir si el polígono de la zona no cambió.
_polygon_cache: Dict[str, Polygon] = {}


def normalize_video_id(video_id: str, is_live: bool = False) -> str:
    """
    Normaliza un `video_id` a la forma canónica de la sesión.

    El pipeline real siempre corre sobre el video ya limpiado
    (`<nombre>_clean.mp4`, ver `app/core/ingestion/video_cleaner.py`), así
    que sus zonas siempre deberían vivir en `data/zones/<nombre>_clean/`.
    Si en el editor de zonas se cargó el video crudo (sin limpiar) como
    frame de referencia, sin esto se crearía una segunda carpeta de zonas
    (`<nombre>` además de `<nombre>_clean`) para lo que en realidad es la
    misma sesión — el bug reportado de "carpetas duplicadas" en
    `data/zones/`.

    También sanitiza `video_id` (ver `sanitize_filename_component`): este
    valor se usa tal cual como nombre de carpeta en disco, y en último
    término viene del nombre de un archivo subido por el usuario.

    `is_live=True` es para las sesiones de cámara en directo: ahí no hay
    ningún archivo que limpiar, así que el sufijo `_clean` sería una
    mentira ("camara_movil_clean" no existe en ninguna parte). Se sanitiza
    igual, porque el id termina siendo un nombre de carpeta.
    """
    video_id = sanitize_filename_component(video_id, fallback="video")
    if is_live:
        return video_id
    return video_id if video_id.endswith("_clean") else f"{video_id}_clean"


def _get_cached_polygon(zone: Zone) -> Polygon:
    cache_key = f"{zone.zone_id}:{zone.video_id}:{tuple(zone.polygon)}"
    poly = _polygon_cache.get(cache_key)
    if poly is None:
        poly = Polygon(zone.polygon)
        _polygon_cache[cache_key] = poly
    return poly


def is_point_in_polygon(x: float, y: float, zone: Zone) -> bool:
    """Verifica si un punto (x, y) está dentro del polígono de una zona."""
    if len(zone.polygon) < 3:
        return False
    return Point(x, y).within(_get_cached_polygon(zone))

class ZoneManager:
    """
    Carga y persistencia de las zonas, agrupadas por video o cámara.

    **El `video_id` llega ya normalizado.** `ZoneManager` solo lo sanitiza
    para poder usarlo como nombre de carpeta; no le añade ni le quita
    sufijos. Antes normalizaba por su cuenta y eso rompía las sesiones en
    directo: el editor guardaba las zonas en `camara_movil_clean/` mientras
    el pipeline las buscaba en `camara_movil/`, así que un análisis en vivo
    no encontraba ninguna zona y no medía ni una interacción, en silencio.

    Quien crea la sesión decide la forma canónica del id, una sola vez, con
    `normalize_video_id(..., is_live=...)`.
    """

    def __init__(self, storage_path: str = ZONES_STORAGE_PATH):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def save_zone(self, zone: Zone) -> None:
        """
        Guarda una zona en un archivo JSON, dentro de la subcarpeta de su
        video (sobreescribe si `zone.zone_id` ya existe — así una edición
        de puntos actualiza el mismo archivo en vez de crear uno nuevo).
        """
        video_id = sanitize_filename_component(zone.video_id, fallback="video")
        zone_id = sanitize_filename_component(zone.zone_id, fallback="zone")
        if video_id != zone.video_id or zone_id != zone.zone_id:
            zone = zone.model_copy(update={"video_id": video_id, "zone_id": zone_id})
        video_dir = self.storage_path / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        file_path = video_dir / f"{zone.zone_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(zone.model_dump(), f, indent=4)

    def load_zones(self, video_id: str) -> List[Zone]:
        """Carga las zonas guardadas para un video/cámara específico (no mezcla con otros)."""
        zones = []
        video_dir = self.storage_path / sanitize_filename_component(video_id, fallback="video")
        if not video_dir.exists():
            return zones
        for file_path in video_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    zones.append(Zone(**data))
            except Exception:
                # Silenciosamente omitir si el archivo está corrupto o no cumple el esquema
                pass
        return zones

    def delete_zone(self, video_id: str, zone_id: str) -> bool:
        """
        Elimina el archivo JSON de una zona guardada para un video/cámara.

        Devuelve True si el archivo existía y se borró, False si no
        existía (no lanza excepción en ese caso: para la UI, "ya no
        existe" y "se acaba de borrar" tienen el mismo resultado neto).
        """
        zone_id = sanitize_filename_component(zone_id, fallback="zone")
        file_path = (
            self.storage_path
            / sanitize_filename_component(video_id, fallback="video")
            / f"{zone_id}.json"
        )
        if not file_path.exists():
            return False
        file_path.unlink()
        return True


def _euclidean_distance(kp1: Keypoint, kp2: Keypoint) -> float:
    """Calcula la distancia euclidiana entre dos keypoints."""
    return math.sqrt((kp1.x - kp2.x) ** 2 + (kp1.y - kp2.y) ** 2)


def check_zone_signal(pose: PoseResult, zones: List[Zone]) -> List[ZoneSignal]:
    """
    Chequea la posición de las muñecas respecto a las zonas y determina si el brazo está extendido.
    
    Heurística de brazo extendido:
    distancia(muñeca, hombro) / distancia(hombro, codo) >= ARM_EXTENSION_MIN_RATIO
    
    Se aplica filtro de confianza mínima de keypoints: ambas muñeca y hombro
    deben tener confianza >= MIN_KEYPOINT_CONFIDENCE para ser considerados válidos.
    """
    signals = []

    # Validar confianza de keypoints para brazo izquierdo
    left_valid = (pose.left_wrist.confidence >= MIN_KEYPOINT_CONFIDENCE and 
                  pose.left_shoulder.confidence >= MIN_KEYPOINT_CONFIDENCE)
    
    # Validar confianza de keypoints para brazo derecho
    right_valid = (pose.right_wrist.confidence >= MIN_KEYPOINT_CONFIDENCE and 
                   pose.right_shoulder.confidence >= MIN_KEYPOINT_CONFIDENCE)

    # Calcular distancias para brazo izquierdo (solo si es válido)
    left_extended = False
    if left_valid:
        left_wrist_shoulder = _euclidean_distance(pose.left_wrist, pose.left_shoulder)
        left_shoulder_elbow = _euclidean_distance(pose.left_shoulder, pose.left_elbow)
        if left_shoulder_elbow > 1e-5:
            left_extended = (left_wrist_shoulder / left_shoulder_elbow) >= ARM_EXTENSION_MIN_RATIO

    # Calcular distancias para brazo derecho (solo si es válido)
    right_extended = False
    if right_valid:
        right_wrist_shoulder = _euclidean_distance(pose.right_wrist, pose.right_shoulder)
        right_shoulder_elbow = _euclidean_distance(pose.right_shoulder, pose.right_elbow)
        if right_shoulder_elbow > 1e-5:
            right_extended = (right_wrist_shoulder / right_shoulder_elbow) >= ARM_EXTENSION_MIN_RATIO

    for zone in zones:
        if len(zone.polygon) < 3:
            continue

        # Evaluar si la muñeca izquierda está adentro (solo si es válida)
        left_inside = False
        if left_valid:
            left_inside = is_point_in_polygon(pose.left_wrist.x, pose.left_wrist.y, zone)
        
        # Evaluar si la muñeca derecha está adentro (solo si es válida)
        right_inside = False
        if right_valid:
            right_inside = is_point_in_polygon(pose.right_wrist.x, pose.right_wrist.y, zone)
        
        wrist_inside = left_inside or right_inside
        
        # Determinar si el brazo que está adentro (o al menos uno si ambos) está extendido
        arm_extended = False
        if left_inside and left_extended:
            arm_extended = True
        if right_inside and right_extended:
            arm_extended = True

        signals.append(
            ZoneSignal(
                track_id=pose.track_id,
                zone_id=zone.zone_id,
                frame_index=pose.frame_index,
                wrist_inside=wrist_inside,
                arm_extended=arm_extended,
            )
        )

    return signals