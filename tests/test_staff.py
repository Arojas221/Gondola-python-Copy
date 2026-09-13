"""
Tests unitarios para el módulo de detección heurística de empleados (staff.py).
"""
from app.core.detection.schemas import PositionSample, Zone
from app.core.detection.staff import StaffZoneTracker


def _staff_zone(zone_id: str = "staff_zone") -> Zone:
    """Zona rectangular staff sintética (cuadrante 0-100 x 0-100)."""
    return Zone(
        zone_id=zone_id,
        video_id="test_video",
        name="Área Staff",
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        zone_type="staff",
    )


def _product_zone(zone_id: str = "prod_zone") -> Zone:
    """Zona rectangular de producto sintética."""
    return Zone(
        zone_id=zone_id,
        video_id="test_video",
        name="Estante",
        polygon=[(200.0, 200.0), (300.0, 200.0), (300.0, 300.0), (200.0, 300.0)],
        zone_type="product",
    )


def _pos(track_id: int, x: float, y: float) -> PositionSample:
    return PositionSample(
        track_id=track_id, frame_index=0, original_timestamp_sec=0.0,
        foot_position=(x, y),
    )


def test_marks_employee_on_entry():
    """Al entrar a una zona staff, el track se marca como empleado."""
    tracker = StaffZoneTracker()
    result = tracker.update(_pos(1, 50.0, 50.0), [_staff_zone()])
    assert result is True
    assert tracker.is_employee(1)


def test_sticky_after_leaving_staff_zone():
    """Una vez marcado como empleado, sigue marcado al salir de la zona staff."""
    tracker = StaffZoneTracker()
    tracker.update(_pos(1, 50.0, 50.0), [_staff_zone()])
    assert tracker.is_employee(1)

    # Mover fuera de la zona staff
    result = tracker.update(_pos(1, 200.0, 200.0), [_staff_zone()])
    assert result is True
    assert tracker.is_employee(1)


def test_not_marked_by_product_zone():
    """Entrar a una zona product no marca como empleado."""
    tracker = StaffZoneTracker()
    result = tracker.update(_pos(1, 250.0, 250.0), [_product_zone()])
    assert result is False
    assert not tracker.is_employee(1)


def test_multiple_tracks_independent():
    """El marcado es independiente por track_id."""
    tracker = StaffZoneTracker()
    tracker.update(_pos(1, 50.0, 50.0), [_staff_zone()])
    assert tracker.is_employee(1)
    assert not tracker.is_employee(2)

    tracker.update(_pos(2, 50.0, 50.0), [_staff_zone()])
    assert tracker.is_employee(2)


def test_product_zone_does_not_mark():
    """Zona product no interactúa con la lógica de staff."""
    tracker = StaffZoneTracker()
    result = tracker.update(_pos(1, 250.0, 250.0), [_product_zone()])
    assert result is False
    assert len(tracker.known_employee_tracks) == 0
