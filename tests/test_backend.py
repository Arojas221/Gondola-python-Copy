"""
Tests básicos del backend local (Team 3): almacén SQLite + cuadrícula de densidad.
"""
import numpy as np
import pytest

from app.core.backend.event_store import EventStore, connect_store_to_publisher
from app.core.backend.heatmap import build_density_grid
from app.core.detection.event_publisher import InProcessPublisher
from app.core.detection.schemas import InteractionEvent, PositionSample, DwellRecord


def _make_sample(track_id: int, x: float, y: float, ts: float = 0.0) -> PositionSample:
    return PositionSample(
        track_id=track_id,
        frame_index=0,
        original_timestamp_sec=ts,
        foot_position=(x, y),
        camera_id="cam_1",
    )


def test_event_store_roundtrip(tmp_path):
    """Inserta un evento y una muestra, y los recupera por conteo."""
    store = EventStore(db_path=str(tmp_path / "events.db"))
    try:
        store.insert_event(
            InteractionEvent(track_id=1, zone_id="shelf_A1", action="taken", timestamp=12.5)
        )
        store.insert_position_sample(_make_sample(1, 320.0, 240.0))

        assert store.count_events() == 1
        assert store.count_position_samples() == 1
    finally:
        store.close()


def test_dwell_record_roundtrip(tmp_path):
    """Inserta un DwellRecord directo y se puede contar/recuperar."""
    store = EventStore(db_path=str(tmp_path / "events.db"))
    try:
        store.insert_dwell_record(
            DwellRecord(
                track_id=1, zone_id="shelf_A1",
                entry_timestamp=10.0, exit_timestamp=15.5, duration_sec=5.5,
                is_employee=False,
            )
        )
        assert store.count_dwell_records() == 1
    finally:
        store.close()


def test_bus_subscription_persists_all_types(tmp_path):
    """El bus in-process (publish -> Signal Qt -> sink) persiste los 3 tipos de payload."""
    store = EventStore(db_path=str(tmp_path / "events.db"))
    publisher = InProcessPublisher()
    connect_store_to_publisher(store, publisher)
    try:
        publisher.publish(
            InteractionEvent(track_id=2, zone_id="shelf_B2", action="taken", timestamp=3.0)
        )
        publisher.publish(_make_sample(2, 100.0, 500.0))
        publisher.publish(
            DwellRecord(track_id=2, zone_id="shelf_B2", entry_timestamp=1.0, exit_timestamp=4.0, duration_sec=3.0)
        )

        assert store.count_events() == 1
        assert store.count_position_samples() == 1
        assert store.count_dwell_records() == 1
    finally:
        store.close()


def test_density_grid_shape_and_blur():
    """La cuadrícula respeta el tamaño pedido y el blur conserva la masa."""
    frame_size = (1280, 720)
    # 200 muestras concentradas en el centro del frame
    samples = [_make_sample(i, 640.0, 360.0) for i in range(200)]

    raw = build_density_grid(samples, frame_size, grid_size=(64, 48), sigma=None)
    blurred = build_density_grid(samples, frame_size, grid_size=(64, 48), sigma=1.0)

    assert raw.shape == (48, 64)
    assert blurred.shape == (48, 64)

    # La masa total se conserva con el blur (la suma es la misma)
    assert abs(float(raw.sum()) - float(blurred.sum())) < 1e-3
    # El blur reparte la densidad: el pico baja y aparecen vecinos > 0
    assert raw.max() >= blurred.max()
    assert (blurred > 0).sum() > (raw > 0).sum()
    assert float(blurred.max()) > 0