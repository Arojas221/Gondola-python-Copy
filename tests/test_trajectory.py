"""
Tests de la captura de trayectoria continua (PositionSample).
"""
from app.core.detection.schemas import TrackedPerson
from app.core.detection.trajectory import TrajectoryCapture


def _make_person(track_id: int, x1: float, y1: float, x2: float, y2: float) -> TrackedPerson:
    return TrackedPerson(
        bbox=(x1, y1, x2, y2),
        confidence=0.9,
        frame_index=0,
        track_id=track_id,
    )


def test_samples_per_track_with_foot_position():
    """Una PositionSample por persona, con foot = bottom-center del bbox."""
    capture = TrajectoryCapture(sample_every_n_frames=1, camera_id="cam_test")
    people = [
        _make_person(1, 100.0, 200.0, 300.0, 600.0),
        _make_person(2, 400.0, 300.0, 500.0, 700.0),
    ]

    samples = capture.process(frame_index=10, tracked_people=people, timestamp_sec=5.0)

    assert len(samples) == 2
    assert [s.track_id for s in samples] == [1, 2]
    # bottom-center: x = (x1+x2)/2, y = y2
    assert samples[0].foot_position == (200.0, 600.0)
    assert samples[1].foot_position == (450.0, 700.0)
    # timestamp y frame pasan tal cual (los provee la FrameSource)
    assert samples[0].original_timestamp_sec == 5.0
    assert samples[0].frame_index == 10
    assert samples[0].camera_id == "cam_test"


def test_sampling_interval_skips_frames():
    """Con sample_every_n_frames=3 solo se emiten muestras en frames múltiplos."""
    capture = TrajectoryCapture(sample_every_n_frames=3, camera_id="cam_test")
    people = [_make_person(1, 0.0, 0.0, 10.0, 10.0)]

    assert capture.process(frame_index=1, tracked_people=people, timestamp_sec=1.0) == []
    assert len(capture.process(frame_index=2, tracked_people=people, timestamp_sec=2.0)) == 0
    assert len(capture.process(frame_index=3, tracked_people=people, timestamp_sec=3.0)) == 1
    assert len(capture.process(frame_index=6, tracked_people=people, timestamp_sec=6.0)) == 1


def test_no_people_no_samples():
    """Sin personas trackeadas no se emite nada."""
    capture = TrajectoryCapture(sample_every_n_frames=1)
    assert capture.process(frame_index=0, tracked_people=[], timestamp_sec=0.0) == []