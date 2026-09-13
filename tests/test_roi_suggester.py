"""
Tests del sugeridor automático de zonas (ROI).

Cubren la geometría (que es donde un error pasa desapercibido y arruina
las sugerencias) y el comportamiento de extremo a extremo sobre un frame
sintético, sin necesidad de cargar ningún modelo de YOLO.
"""
import numpy as np
import pytest

from app.core.detection.roi_suggester import (
    SUGGESTED_ID_PREFIX,
    box_iou,
    boxes_from_edges,
    boxes_from_products,
    filter_boxes,
    merge_boxes,
    suggest_zones,
)


def _shelf_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """
    Frame sintético con una estantería: un rectángulo claro con dos baldas
    horizontales marcadas, sobre fondo oscuro.

    Ocupa ~13% del frame, dentro del rango de tamaño que el sugeridor
    considera plausible para un estante (una góndola real en una toma de
    CCTV ronda ese orden; las zonas del video de prueba del proyecto
    ocupan entre el 5% y el 10%).
    """
    frame = np.full((height, width, 3), 30, dtype=np.uint8)
    frame[180:320, 200:440] = 200                # cuerpo de la góndola
    for y in (230, 275):                          # baldas
        frame[y:y + 6, 200:440] = 40
    return frame


# ------------------------------------------------------------ geometría --
def test_box_iou_identical_boxes_is_one():
    box = (0.0, 0.0, 10.0, 10.0)
    assert box_iou(box, box) == pytest.approx(1.0)


def test_box_iou_disjoint_boxes_is_zero():
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_box_iou_half_overlap():
    # Dos cuadrados de 100 px² que comparten la mitad: intersección 50,
    # unión 150 -> IoU = 1/3.
    assert box_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_merge_boxes_unions_overlapping_pair():
    """Dos candidatos muy solapados deben salir como un solo rectángulo que los cubra."""
    merged = merge_boxes([(0, 0, 10, 10), (2, 2, 12, 12)], iou_threshold=0.25)
    assert merged == [(0.0, 0.0, 12.0, 12.0)]


def test_merge_boxes_keeps_separate_shelves_apart():
    """Dos góndolas distintas no deben fusionarse en una sola zona."""
    merged = merge_boxes([(0, 0, 10, 10), (100, 100, 110, 110)], iou_threshold=0.25)
    assert len(merged) == 2


def test_merge_boxes_is_transitive():
    """Si A solapa con B y B con C, las tres terminan en un único rectángulo."""
    merged = merge_boxes([(0, 0, 10, 10), (5, 0, 15, 10), (10, 0, 20, 10)], iou_threshold=0.2)
    assert merged == [(0.0, 0.0, 20.0, 10.0)]


def test_filter_boxes_drops_too_small_and_too_large():
    frame_size = (1000, 1000)  # 1.000.000 px²
    boxes = [
        (0, 0, 20, 20),        # 400 px² -> muy chico
        (0, 0, 900, 900),      # 810.000 px² -> es la pared, no un estante
        (0, 0, 400, 300),      # 120.000 px² (12%) y más ancho que alto -> válido
    ]
    kept = filter_boxes(boxes, frame_size)
    assert kept == [(0, 0, 400, 300)]


def test_filter_boxes_drops_tall_narrow_boxes():
    """Una columna alta y angosta no es un estante."""
    kept = filter_boxes([(0, 0, 60, 400)], (1000, 1000))
    assert kept == []


# ------------------------------------------------------ fuente de bordes --
def test_boxes_from_edges_finds_the_shelf():
    boxes = boxes_from_edges(_shelf_frame())
    assert boxes, "el detector de bordes no encontró ningún candidato"


def test_boxes_from_edges_on_empty_frame_returns_nothing():
    assert boxes_from_edges(np.zeros((100, 100, 3), dtype=np.uint8)) == []


# --------------------------------------------------- fuente de productos --
def test_boxes_from_products_groups_neighbours():
    """Productos contiguos en la misma balda forman un solo candidato."""
    products = [(100, 100, 130, 140), (140, 100, 170, 140), (180, 100, 210, 140)]
    grouped = boxes_from_products(products, frame_size=(640, 480))
    assert len(grouped) == 1


def test_boxes_from_products_separates_distant_groups():
    """Producto en góndolas opuestas del pasillo: dos candidatos distintos."""
    products = [(20, 100, 50, 140), (580, 380, 610, 420)]
    grouped = boxes_from_products(products, frame_size=(640, 480))
    assert len(grouped) == 2


def test_boxes_from_products_with_no_detections():
    assert boxes_from_products([], frame_size=(640, 480)) == []


# ------------------------------------------------------------ integración --
def test_suggest_zones_returns_valid_zones():
    zones = suggest_zones(_shelf_frame(), video_id="mi_video_clean")

    assert zones, "no se propuso ninguna zona sobre un frame con una góndola clara"
    for zone in zones:
        assert zone.zone_id.startswith(SUGGESTED_ID_PREFIX)
        assert zone.video_id == "mi_video_clean"
        assert zone.zone_type == "product"
        assert len(zone.polygon) == 4


def test_suggest_zones_respects_max_zones():
    zones = suggest_zones(_shelf_frame(), video_id="v", max_zones=1)
    assert len(zones) <= 1


def test_suggest_zones_sorted_by_area_descending():
    zones = suggest_zones(_shelf_frame(), video_id="v")
    areas = []
    for zone in zones:
        xs = [p[0] for p in zone.polygon]
        ys = [p[1] for p in zone.polygon]
        areas.append((max(xs) - min(xs)) * (max(ys) - min(ys)))
    assert areas == sorted(areas, reverse=True)


def test_suggest_zones_on_empty_frame_returns_empty_list():
    assert suggest_zones(np.zeros((10, 10, 3), dtype=np.uint8), video_id="v") == []


def test_suggest_zones_survives_a_failing_product_detector():
    """
    Si el detector de producto falla, la sugerencia debe seguir saliendo
    por bordes — no propagar la excepción hasta la UI.
    """
    def _broken(_frame):
        raise RuntimeError("modelo no disponible")

    zones = suggest_zones(_shelf_frame(), video_id="v", product_detector=_broken)
    assert zones, "un detector de producto roto no debe anular la sugerencia por bordes"


def test_suggest_zones_uses_product_detections():
    """Las cajas de producto aportan candidatos además de los bordes."""
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)  # sin estructura de bordes

    def _products(_frame):
        return [(200.0, 200.0, 260.0, 260.0), (270.0, 200.0, 330.0, 260.0)]

    zones = suggest_zones(frame, video_id="v", product_detector=_products)
    assert zones, "las detecciones de producto deberían generar al menos una zona"
