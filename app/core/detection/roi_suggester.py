"""
Sugerencia automática de zonas de góndola (ROI) sobre el frame de referencia.

YOLO-COCO no tiene una clase "estantería", así que no hay un detector
directo que resuelva esto. La propuesta se arma de forma híbrida, con dos
señales que se refuerzan entre sí:

1. **Estructura** (`boxes_from_edges`): una góndola es una caja rectangular
   con baldas horizontales muy marcadas. Canny saca los bordes, una
   dilatación con kernel ancho y bajo une los bordes de cada balda en una
   banda continua, y los contornos de esas bandas dan rectángulos
   candidatos.

2. **Contenido** (`boxes_from_products`): donde hay producto hay góndola.
   Las clases COCO que el YOLO ya cargado sí detecta y que en una tienda
   son producto de estante (botellas, tazas, cuencos, libros, floreros) se
   agrupan por cercanía, y cada grupo aporta otro candidato.

Los candidatos de ambas fuentes se fusionan por solapamiento, se filtran
por tamaño y forma, y se devuelven como `Zone` de tipo "product".

**Son sugerencias, no zonas guardadas.** Este módulo no escribe nada en
disco: quien lo llama (la pestaña de edición de zonas) las muestra para que
el usuario las corrija, acepte o descarte. Un heurístico de visión clásica
sobre video de CCTV se equivoca a menudo, y ensuciar `data/zones/` con
polígonos que nadie revisó sería peor que no sugerir nada.
"""
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.core.detection.schemas import Zone
from app.utils.config import (
    ROI_SUGGEST_MAX_ZONES,
    ROI_SUGGEST_MIN_AREA_RATIO,
    ROI_SUGGEST_MAX_AREA_RATIO,
    ROI_SUGGEST_MIN_ASPECT_RATIO,
    ROI_SUGGEST_MERGE_IOU,
)

Box = Tuple[float, float, float, float]  # (x1, y1, x2, y2)

# Clases COCO que en una tienda son producto de góndola. No pretende ser
# exhaustivo: son las que un modelo nano detecta con alguna fiabilidad y
# que, agrupadas, delatan dónde hay mercancía expuesta.
PRODUCT_CLASS_IDS = (39, 40, 41, 45, 46, 47, 49, 73, 75)

# Prefijo de los zone_id provisionales. Al aceptar una sugerencia, la UI le
# asigna su zone_id definitivo (zone_1, zone_2, ...) — este id solo vive en
# memoria mientras la zona está sin guardar.
SUGGESTED_ID_PREFIX = "sugerida_"


# ------------------------------------------------------------ geometría --
def box_iou(a: Box, b: Box) -> float:
    """Intersección sobre unión de dos rectángulos (x1, y1, x2, y2)."""
    inter_x1 = max(a[0], b[0])
    inter_y1 = max(a[1], b[1])
    inter_x2 = min(a[2], b[2])
    inter_y2 = min(a[3], b[3])

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    if intersection <= 0:
        return 0.0

    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def merge_boxes(boxes: Sequence[Box], iou_threshold: float = ROI_SUGGEST_MERGE_IOU) -> List[Box]:
    """
    Fusiona en su unión los rectángulos que se solapan por encima del umbral.

    A diferencia de un NMS clásico (que descarta el candidato más débil),
    aquí interesa quedarse con la extensión completa del estante: dos
    bandas que corresponden a dos baldas de la misma góndola deben terminar
    siendo una sola zona que las cubra a ambas, no la más grande de las dos.

    Se repite hasta que una pasada completa no fusiona nada, porque una
    fusión puede crear un rectángulo que ahora sí solapa con un tercero.
    """
    merged = [tuple(map(float, b)) for b in boxes]
    changed = True
    while changed:
        changed = False
        result: List[Box] = []
        for box in merged:
            for i, kept in enumerate(result):
                if box_iou(box, kept) >= iou_threshold:
                    result[i] = (
                        min(box[0], kept[0]),
                        min(box[1], kept[1]),
                        max(box[2], kept[2]),
                        max(box[3], kept[3]),
                    )
                    changed = True
                    break
            else:
                result.append(box)
        merged = result
    return merged


def filter_boxes(
    boxes: Sequence[Box],
    frame_size: Tuple[int, int],
    min_area_ratio: float = ROI_SUGGEST_MIN_AREA_RATIO,
    max_area_ratio: float = ROI_SUGGEST_MAX_AREA_RATIO,
    min_aspect_ratio: float = ROI_SUGGEST_MIN_ASPECT_RATIO,
) -> List[Box]:
    """
    Descarta candidatos que no pueden ser un estante.

    - Demasiado chicos: ruido de bordes, un cartel, el marco de una puerta.
    - Demasiado grandes: la pared entera o el piso, no una góndola.
    - Demasiado altos y angostos: una columna o el borde del encuadre; un
      estante tiende a ser al menos tan ancho como alto.
    """
    frame_w, frame_h = frame_size
    frame_area = float(frame_w * frame_h) or 1.0

    kept: List[Box] = []
    for x1, y1, x2, y2 in boxes:
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            continue
        area_ratio = (w * h) / frame_area
        if not (min_area_ratio <= area_ratio <= max_area_ratio):
            continue
        if (w / h) < min_aspect_ratio:
            continue
        kept.append((x1, y1, x2, y2))
    return kept


# ------------------------------------------------------ fuente: bordes --
def boxes_from_edges(frame: np.ndarray) -> List[Box]:
    """
    Candidatos a partir de la estructura del frame (Canny + morfología).

    El kernel de dilatación es ancho y bajo (25x3) a propósito: une los
    bordes horizontales de una misma balda sin pegar entre sí dos góndolas
    que están una encima de la otra.
    """
    if frame is None or frame.size == 0:
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Umbrales derivados de la mediana del frame: una cámara de tienda
    # oscura y una bien iluminada necesitan cortes distintos, y fijarlos a
    # mano hace que el sugeridor solo funcione con el video de prueba.
    median = float(np.median(blurred))
    lower = int(max(0, 0.66 * median))
    upper = int(min(255, 1.33 * median))
    edges = cv2.Canny(blurred, lower, upper)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    bands = cv2.dilate(edges, horizontal_kernel, iterations=2)
    bands = cv2.morphologyEx(bands, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))

    contours, _ = cv2.findContours(bands, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: List[Box] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        boxes.append((float(x), float(y), float(x + w), float(y + h)))
    return boxes


# --------------------------------------------------- fuente: productos --
def boxes_from_products(
    product_boxes: Sequence[Box],
    frame_size: Tuple[int, int],
    margin_ratio: float = 0.04,
) -> List[Box]:
    """
    Agrupa detecciones de producto en candidatos a zona.

    Cada caja de producto se expande un margen proporcional al ancho del
    frame; las cajas expandidas que se tocan quedan en el mismo grupo, y la
    unión de cada grupo es el candidato. Es un clustering espacial simple
    que no necesita elegir un número de clusters de antemano.
    """
    if not product_boxes:
        return []

    frame_w, frame_h = frame_size
    margin = max(4.0, frame_w * margin_ratio)

    expanded: List[Box] = []
    for x1, y1, x2, y2 in product_boxes:
        expanded.append((
            max(0.0, x1 - margin),
            max(0.0, y1 - margin),
            min(float(frame_w), x2 + margin),
            min(float(frame_h), y2 + margin),
        ))

    # iou_threshold bajo: dos productos vecinos apenas se solapan tras
    # expandirse, y aun así deben caer en el mismo estante.
    return merge_boxes(expanded, iou_threshold=0.01)


def build_product_detector(conf: float = 0.25) -> Callable[[np.ndarray], List[Box]]:
    """
    Detector de producto para `suggest_zones`, sobre el mismo YOLO del pipeline.

    Import perezoso de `ultralytics` por la misma razón que en
    `frame_picker.build_people_detector`: este módulo se importa desde tests
    que no necesitan cargar un modelo.
    """
    from ultralytics import YOLO  # import local: ver docstring

    from app.utils.config import DETECTION_MODEL_NAME

    model = YOLO(DETECTION_MODEL_NAME)

    def _detect(frame: np.ndarray) -> List[Box]:
        results = model.predict(frame, classes=list(PRODUCT_CLASS_IDS), conf=conf, verbose=False)
        boxes: List[Box] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().tolist()
                boxes.append((float(x1), float(y1), float(x2), float(y2)))
        return boxes

    return _detect


# --------------------------------------------------------- API pública --
def suggest_zones(
    frame: np.ndarray,
    video_id: str,
    max_zones: int = ROI_SUGGEST_MAX_ZONES,
    product_detector: Optional[Callable[[np.ndarray], List[Box]]] = None,
) -> List[Zone]:
    """
    Propone zonas de góndola sobre `frame`.

    Devuelve `Zone` de tipo "product" con `zone_id` provisional
    (`sugerida_N`) y polígono rectangular de 4 vértices, ordenadas de mayor
    a menor área. No persiste nada: ver la nota del encabezado del módulo.

    `product_detector` es opcional — sin él la sugerencia usa solo la
    estructura de bordes, que ya funciona; con él se suman las zonas donde
    hay mercancía visible.
    """
    if frame is None or frame.size == 0:
        return []

    frame_h, frame_w = frame.shape[:2]
    frame_size = (frame_w, frame_h)

    candidates = boxes_from_edges(frame)

    if product_detector is not None:
        try:
            product_boxes = product_detector(frame)
        except Exception:  # noqa: BLE001 - sin productos detectados seguimos con los bordes
            product_boxes = []
        candidates.extend(boxes_from_products(product_boxes, frame_size))

    candidates = filter_boxes(candidates, frame_size)
    candidates = merge_boxes(candidates)
    # Volver a filtrar: una fusión puede haber creado un rectángulo que
    # ahora supera el área máxima permitida.
    candidates = filter_boxes(candidates, frame_size)

    candidates.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)

    zones: List[Zone] = []
    for i, (x1, y1, x2, y2) in enumerate(candidates[:max_zones], start=1):
        zones.append(Zone(
            zone_id=f"{SUGGESTED_ID_PREFIX}{i}",
            video_id=video_id,
            name=f"Estante sugerido {i}",
            polygon=[
                (round(x1, 2), round(y1, 2)),
                (round(x2, 2), round(y1, 2)),
                (round(x2, 2), round(y2, 2)),
                (round(x1, 2), round(y2, 2)),
            ],
            zone_type="product",
        ))
    return zones
