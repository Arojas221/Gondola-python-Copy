"""
Tests unitarios para el módulo de dwell time (presence.py).
"""
import pytest
from app.core.detection.schemas import PositionSample, Zone, DwellRecord
from app.core.detection.presence import DwellTracker


def _make_zone(zone_id: str = "zone_1", zone_type: str = "product") -> Zone:
    """Zona rectangular sintética para tests (cuadrante 0-100 x 0-100)."""
    return Zone(
        zone_id=zone_id,
        video_id="test_video",
        name=f"Zona {zone_id}",
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        zone_type=zone_type,
    )


def _make_position(track_id: int, x: float, y: float, timestamp: float) -> PositionSample:
    return PositionSample(
        track_id=track_id, frame_index=0, original_timestamp_sec=timestamp,
        foot_position=(x, y),
    )


def test_entry_recorded_no_emit():
    """Al entrar a una zona, se registra la entrada pero no se emite nada."""
    dt = DwellTracker()
    zone = _make_zone()
    pos = _make_position(1, 50.0, 50.0, 1.0)
    records = dt.update(pos, [zone], 1.0)
    assert records == []
    assert (1, "zone_1") in dt.active_entries


def test_still_inside_no_emit():
    """Si la persona sigue dentro, no se emite nada."""
    dt = DwellTracker()
    zone = _make_zone()
    dt.update(_make_position(1, 50.0, 50.0, 1.0), [zone], 1.0)
    records = dt.update(_make_position(1, 60.0, 60.0, 2.0), [zone], 2.0)
    assert records == []


def test_exit_emits_dwell_record():
    """Al salir de la zona, se emite exactamente un DwellRecord con la duración correcta."""
    dt = DwellTracker()
    zone = _make_zone()
    dt.update(_make_position(1, 50.0, 50.0, 1.0), [zone], 1.0)
    records = dt.update(_make_position(1, 150.0, 150.0, 4.0), [zone], 4.0)
    assert len(records) == 1
    rec = records[0]
    assert rec.track_id == 1
    assert rec.zone_id == "zone_1"
    assert rec.entry_timestamp == 1.0
    assert rec.exit_timestamp == 4.0
    assert rec.duration_sec == pytest.approx(3.0)
    assert (1, "zone_1") not in dt.active_entries


def test_multiple_people_independent():
    """Dos personas en la misma zona generan dwell records independientes."""
    dt = DwellTracker()
    zone = _make_zone()
    dt.update(_make_position(1, 50.0, 50.0, 0.0), [zone], 0.0)
    dt.update(_make_position(2, 20.0, 20.0, 0.5), [zone], 0.5)

    # Persona 1 sale
    recs1 = dt.update(_make_position(1, 150.0, 150.0, 3.0), [zone], 3.0)
    assert len(recs1) == 1
    assert recs1[0].duration_sec == pytest.approx(3.0)

    # Persona 2 sigue dentro
    recs2 = dt.update(_make_position(2, 25.0, 25.0, 3.5), [zone], 3.5)
    assert recs2 == []

    # Persona 2 sale
    recs2b = dt.update(_make_position(2, 150.0, 150.0, 5.0), [zone], 5.0)
    assert len(recs2b) == 1
    assert recs2b[0].duration_sec == pytest.approx(4.5)


def test_staff_zones_ignored():
    """Las zonas staff no generan dwell records."""
    dt = DwellTracker()
    zone = _make_zone(zone_type="staff")
    dt.update(_make_position(1, 50.0, 50.0, 1.0), [zone], 1.0)
    records = dt.update(_make_position(1, 150.0, 150.0, 4.0), [zone], 4.0)
    assert records == []
    assert len(dt.active_entries) == 0


def test_reentry_generates_separate_records():
    """Si una persona sale y vuelve a entrar, se generan registros separados."""
    dt = DwellTracker()
    zone = _make_zone()
    dt.update(_make_position(1, 50.0, 50.0, 1.0), [zone], 1.0)
    rec1 = dt.update(_make_position(1, 150.0, 150.0, 3.0), [zone], 3.0)
    assert len(rec1) == 1
    assert rec1[0].duration_sec == pytest.approx(2.0)

    dt.update(_make_position(1, 50.0, 50.0, 5.0), [zone], 5.0)
    rec2 = dt.update(_make_position(1, 150.0, 150.0, 8.0), [zone], 8.0)
    assert len(rec2) == 1
    assert rec2[0].duration_sec == pytest.approx(3.0)


def test_is_employee_propagated_to_record():
    """El flag is_employee de la posición se propaga al DwellRecord emitido."""
    dt = DwellTracker()
    zone = _make_zone()
    entry = _make_position(1, 50.0, 50.0, 1.0)
    dt.update(entry, [zone], 1.0)

    exit_pos = _make_position(1, 150.0, 150.0, 4.0)
    exit_pos.is_employee = True
    records = dt.update(exit_pos, [zone], 4.0)
    assert len(records) == 1
    assert records[0].is_employee is True
