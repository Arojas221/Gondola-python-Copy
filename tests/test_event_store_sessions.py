"""
Tests del almacén por sesión (`video_id`) y del marcado de datos de demo.

Son las dos garantías de las que depende que el Dashboard diga la verdad:
que el selector de sesión filtre de verdad, y que los datos sembrados no
puedan pasar por reales.
"""
import sqlite3

import pytest

from app.core.backend.event_store import EventStore
from app.core.detection.schemas import DwellRecord, InteractionEvent, PositionSample


def _event(zone_id: str = "zone_1", action: str = "taken", ts: float = 1.0) -> InteractionEvent:
    return InteractionEvent(track_id=1, zone_id=zone_id, action=action, timestamp=ts)


def _sample(x: float = 10.0, y: float = 20.0, ts: float = 1.0) -> PositionSample:
    return PositionSample(
        track_id=1, frame_index=0, original_timestamp_sec=ts,
        foot_position=(x, y), camera_id="cam_1",
    )


def _dwell(zone_id: str = "zone_1", duration: float = 5.0) -> DwellRecord:
    return DwellRecord(
        track_id=1, zone_id=zone_id, entry_timestamp=0.0,
        exit_timestamp=duration, duration_sec=duration,
    )


@pytest.fixture()
def store(tmp_path):
    s = EventStore(db_path=str(tmp_path / "events.db"))
    yield s
    s.close()


# ---------------------------------------------------------- por sesión --
def test_events_are_tagged_with_the_active_session(store):
    store.set_session("video_a_clean")
    store.insert_event(_event())
    store.flush()

    assert store.count_events("video_a_clean") == 1
    assert store.count_events("video_b_clean") == 0


def test_counts_are_isolated_between_sessions(store):
    store.set_session("video_a_clean")
    store.insert_event(_event(ts=1.0))
    store.insert_event(_event(ts=2.0))
    store.set_session("video_b_clean")
    store.insert_event(_event(ts=3.0))
    store.flush()

    assert store.count_events("video_a_clean") == 2
    assert store.count_events("video_b_clean") == 1
    assert store.count_events() == 3  # sin filtro: el acumulado


def test_summary_only_counts_the_requested_session(store):
    store.set_session("video_a_clean")
    store.insert_event(_event(action="taken", ts=1.0))
    store.insert_dwell_record(_dwell(duration=10.0))
    store.set_session("video_b_clean")
    store.insert_event(_event(action="returned", ts=2.0))
    store.insert_dwell_record(_dwell(duration=2.0))
    store.flush()

    summary_a = store.get_summary("video_a_clean")
    assert summary_a["total_events"] == 1
    assert summary_a["taken"] == 1
    assert summary_a["returned"] == 0
    assert summary_a["avg_dwell_sec"] == pytest.approx(10.0)


def test_zone_breakdown_is_scoped_to_the_session(store):
    store.set_session("video_a_clean")
    store.insert_event(_event(zone_id="zone_1", ts=1.0))
    store.set_session("video_b_clean")
    store.insert_event(_event(zone_id="zone_9", ts=2.0))
    store.flush()

    zones_a = {row["zone_id"] for row in store.get_zone_breakdown("video_a_clean")}
    assert zones_a == {"zone_1"}


def test_position_samples_are_scoped_to_the_session(store):
    store.set_session("video_a_clean")
    store.insert_position_samples([_sample(), _sample(30.0, 40.0)])
    store.set_session("video_b_clean")
    store.insert_position_sample(_sample(50.0, 60.0))
    store.flush()

    assert len(store.get_position_samples(video_id="video_a_clean")) == 2
    assert len(store.get_position_samples(video_id="video_b_clean")) == 1


def test_list_sessions_returns_sessions_with_data(store):
    store.set_session("video_a_clean")
    store.insert_event(_event(ts=1.0))
    store.set_session("video_b_clean")
    store.insert_event(_event(ts=2.0))
    store.flush()

    assert set(store.list_sessions()) == {"video_a_clean", "video_b_clean"}


def test_timeline_tolerates_empty_buckets(store):
    """
    Dos eventos separados por varios buckets vacíos: la serie debe
    rellenar los huecos con ceros en vez de fallar.
    """
    store.set_session("v")
    store.insert_event(_event(ts=0.0))
    store.insert_event(_event(ts=120.0))
    store.flush()

    timeline = store.get_timeline(bucket_sec=30.0, video_id="v")
    assert len(timeline) == 5
    assert timeline[1]["taken"] == 0


# ----------------------------------------------------- marcado de demo --
def test_demo_rows_are_flagged_and_counted_apart(store):
    store.set_session("v", is_demo=True)
    store.insert_event(_event(ts=1.0))
    store.set_session("v", is_demo=False)
    store.insert_event(_event(ts=2.0))
    store.flush()

    assert store.count_events("v") == 2
    assert store.count_demo_events("v") == 1
    assert store.count_real_events("v") == 1


def test_delete_demo_rows_keeps_real_data(store):
    store.set_session("v", is_demo=True)
    store.insert_event(_event(ts=1.0))
    store.insert_position_sample(_sample())
    store.insert_dwell_record(_dwell())
    store.set_session("v", is_demo=False)
    store.insert_event(_event(ts=2.0))
    store.insert_position_sample(_sample(99.0, 99.0))
    store.flush()

    deleted = store.delete_demo_rows("v")

    assert deleted == 1
    assert store.count_events("v") == 1
    assert store.count_real_events("v") == 1
    assert store.count_demo_events("v") == 0
    assert store.count_position_samples("v") == 1
    assert store.count_dwell_records("v") == 0


def test_delete_demo_rows_does_not_touch_other_sessions(store):
    store.set_session("video_a_clean", is_demo=True)
    store.insert_event(_event(ts=1.0))
    store.set_session("video_b_clean", is_demo=True)
    store.insert_event(_event(ts=2.0))
    store.flush()

    store.delete_demo_rows("video_a_clean")

    assert store.count_events("video_a_clean") == 0
    assert store.count_events("video_b_clean") == 1


# ---------------------------------------------------------- migración --
def test_migrates_a_database_without_the_new_columns(tmp_path):
    """
    Una base creada por la versión anterior (sin `video_id` ni `is_demo`)
    debe migrarse sin perder las filas que ya tenía.
    """
    db_path = tmp_path / "vieja.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        """
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, track_id INTEGER NOT NULL,
            zone_id TEXT NOT NULL, action TEXT NOT NULL,
            timestamp REAL NOT NULL, is_employee INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO events VALUES ('abc', 7, 'zone_1', 'taken', 3.5, 0);
        """
    )
    legacy.commit()
    legacy.close()

    store = EventStore(db_path=str(db_path))
    try:
        columns = {r["name"] for r in store._conn.execute("PRAGMA table_info(events)")}
        assert {"video_id", "is_demo"} <= columns
        # La fila vieja sobrevive, con sesión vacía y marcada como real.
        assert store.count_events() == 1
        assert store.count_real_events() == 1
    finally:
        store.close()


def test_schema_init_is_idempotent(tmp_path):
    """Abrir dos veces la misma base no duplica ni rompe nada."""
    db_path = str(tmp_path / "events.db")
    first = EventStore(db_path=db_path)
    first.set_session("v")
    first.insert_event(_event())
    first.close()

    second = EventStore(db_path=db_path)
    try:
        assert second.count_events("v") == 1
    finally:
        second.close()


# ------------------------------------------------------------- lotes --
def test_flush_commits_pending_writes(tmp_path):
    """
    El almacén hace commit por lotes: sin `flush()`, los últimos eventos
    de un análisis no llegarían al disco y el dashboard (que abre su
    propia conexión) no los vería.
    """
    db_path = str(tmp_path / "events.db")
    writer = EventStore(db_path=db_path)
    writer.set_session("v")
    writer.insert_event(_event())

    reader = EventStore(db_path=db_path)
    try:
        assert reader.count_events("v") == 0  # aún sin confirmar
        writer.flush()
        assert reader.count_events("v") == 1
    finally:
        reader.close()
        writer.close()
