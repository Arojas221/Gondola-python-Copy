"""
Tests de las fuentes de frames: video limpio con frame_mapping y cámara en vivo.
"""
import json

import cv2
import numpy as np
import pytest

from app.core.ingestion.frame_source import (
    FrameSample,
    LiveFrameSource,
    VideoFileFrameSource,
    grab_reference_frame,
)


@pytest.fixture()
def tiny_video(tmp_path):
    """Genera un mini video (20 frames, 64x48, 5 fps) para pruebas."""
    path = tmp_path / "tiny_clean.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48))
    rng = np.random.default_rng(42)
    for _ in range(20):
        frame = (rng.random((48, 64, 3)) * 255).astype(np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_video_file_source_iterates_with_translated_timestamps(tiny_video, tmp_path):
    """Itera el video y traduce el timestamp con el frame_mapping del sidecar."""
    mapping = [
        {"clean_frame": 0, "original_frame": 0, "original_timestamp_sec": 0.0},
        {"clean_frame": 1, "original_frame": 3, "original_timestamp_sec": 0.6},
        {"clean_frame": 2, "original_frame": 5, "original_timestamp_sec": 1.0},
    ]
    sidecar = tiny_video.with_suffix(".json")
    sidecar.write_text(json.dumps({"frame_mapping": mapping}), encoding="utf-8")

    source = VideoFileFrameSource(tiny_video)
    try:
        assert source.fps == 5.0

        first = source.next_frame()
        assert isinstance(first, FrameSample)
        assert first.frame_index == 0
        assert first.timestamp_sec == 0.0
        assert first.frame.shape == (48, 64, 3)

        second = source.next_frame()
        assert second.frame_index == 1
        assert second.timestamp_sec == 0.6  # traducido vía mapping, no frame_index/fps

        third = source.next_frame()
        assert third.timestamp_sec == 1.0
    finally:
        source.close()


def test_video_file_source_fallback_to_fps(tiny_video):
    """Sin sidecar ni mapping, el timestamp cae al fallback frame_index/fps."""
    source = VideoFileFrameSource(tiny_video, frame_mapping=[], fps=5.0)
    try:
        sample = source.next_frame()
        assert sample.timestamp_sec == 0.0  # frame 0 / 5.0
        sample = source.next_frame()
        assert sample.timestamp_sec == 0.2  # frame 1 / 5.0
    finally:
        source.close()


def test_missing_video_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        VideoFileFrameSource(tmp_path / "no_existe.mp4")


def _write_video(path, frames, fps=10.0):
    """Escribe un .mp4 sintético que hace las veces de cámara en los tests."""
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for frame in frames:
        writer.write(frame)
    writer.release()


def _frames(count=12, width=64, height=48):
    return [
        np.full((height, width, 3), (i * 17) % 255, dtype=np.uint8)
        for i in range(count)
    ]


# ------------------------------------------------------- cámara en vivo --
def test_live_source_reads_frames(tmp_path):
    """
    La fuente en vivo entrega frames.

    Se apunta a un archivo porque en un test no hay cámara: `LiveFrameSource`
    acepta una ruta además de un índice de webcam o una URL, justamente para
    poder ensayar el modo directo sin hardware.
    """
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames())

    source = LiveFrameSource(str(video), source_id="camara_prueba")
    try:
        sample = source.next_frame()
        assert sample is not None
        assert sample.frame_index == 0
        assert sample.frame.shape[:2] == (48, 64)
    finally:
        source.close()


def test_live_source_declares_itself_live(tmp_path):
    """Quien la consume necesita saber que no va a terminar sola."""
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames())
    source = LiveFrameSource(str(video), source_id="cam")
    try:
        assert source.is_live is True
    finally:
        source.close()


def test_video_file_source_is_not_live(tmp_path):
    video = tmp_path / "clip.mp4"
    _write_video(video, _frames())
    source = VideoFileFrameSource(video)
    try:
        assert source.is_live is False
    finally:
        source.close()


def test_live_source_timestamps_are_session_clock(tmp_path):
    """
    En directo el timestamp son segundos desde que se conectó, y avanzan
    de forma monótona — no hay video original al que mapear.
    """
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames(count=6))

    source = LiveFrameSource(str(video), source_id="cam")
    try:
        stamps = []
        while True:
            sample = source.next_frame()
            if sample is None:
                break
            stamps.append(sample.timestamp_sec)
    finally:
        source.close()

    assert len(stamps) >= 3
    assert stamps[0] >= 0.0
    assert stamps == sorted(stamps), "los timestamps en vivo deben ser monótonos"


def test_live_source_indexes_frames_consecutively(tmp_path):
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames(count=5))
    source = LiveFrameSource(str(video), source_id="cam")
    try:
        indexes = []
        while True:
            sample = source.next_frame()
            if sample is None:
                break
            indexes.append(sample.frame_index)
    finally:
        source.close()
    assert indexes == list(range(len(indexes)))


def test_live_source_uses_its_id_as_video_id(tmp_path):
    """El id de la sesión decide dónde se guardan y se buscan las zonas."""
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames())
    source = LiveFrameSource(str(video), source_id="camara_movil")
    try:
        assert source.video_id == "camara_movil"
    finally:
        source.close()


def test_live_source_falls_back_to_sane_fps(tmp_path):
    """
    Muchas cámaras RTSP reportan 0 fps. Propagar ese valor rompería la
    máquina de estados, cuyos umbrales están expresados en frames.
    """
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames())
    source = LiveFrameSource(str(video), source_id="cam", fps=0)
    try:
        assert 1.0 <= source.fps <= 120.0
    finally:
        source.close()


def test_live_source_raises_on_unreachable_source():
    with pytest.raises(IOError):
        LiveFrameSource("/no/existe/camara.mp4", source_id="cam")


def test_live_source_returns_none_after_close(tmp_path):
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames())
    source = LiveFrameSource(str(video), source_id="cam")
    source.close()
    assert source.next_frame() is None


def test_grab_reference_frame_returns_a_frame(tmp_path):
    video = tmp_path / "camara.mp4"
    _write_video(video, _frames(count=20))
    frame, fps = grab_reference_frame(str(video), warmup_frames=5)
    assert frame is not None
    assert frame.shape[:2] == (48, 64)
    assert fps > 0


def test_grab_reference_frame_on_unreachable_source_returns_none():
    frame, fps = grab_reference_frame("/no/existe/camara.mp4")
    assert frame is None
    assert fps == 0.0
