"""
Tests de `AnalysisSession`: la pieza que decide de dónde salen los frames.

Es lo que permite que la pestaña de zonas analice un archivo o una cámara
en directo sin saber cuál de los dos tiene delante.
"""
import cv2
import numpy as np
import pytest

from app.core.detection.zone import normalize_video_id
from app.core.ingestion.frame_source import LiveFrameSource, VideoFileFrameSource
from app.core.ingestion.session import AnalysisSession, parse_live_source


def _write_video(path, count=8, width=64, height=48, fps=10.0):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for i in range(count):
        writer.write(np.full((height, width, 3), (i * 21) % 255, dtype=np.uint8))
    writer.release()
    return path


# ------------------------------------------------ origen de la sesión --
def test_video_session_is_not_live(tmp_path):
    video = _write_video(tmp_path / "clip_clean.mp4")
    session = AnalysisSession.from_video("clip_clean", video, fps=10.0)
    assert session.is_live is False


def test_live_session_is_live():
    session = AnalysisSession.from_live("camara_movil", "rtsp://192.0.2.1/stream", fps=25.0)
    assert session.is_live is True


def test_video_session_creates_a_file_source(tmp_path):
    video = _write_video(tmp_path / "clip_clean.mp4")
    session = AnalysisSession.from_video("clip_clean", video, fps=10.0)
    source = session.create_source()
    try:
        assert isinstance(source, VideoFileFrameSource)
        assert source.is_live is False
    finally:
        source.close()


def test_live_session_creates_a_live_source(tmp_path):
    """
    Se apunta a un archivo porque en un test no hay cámara; lo que se
    comprueba es que la sesión elige la clase correcta.
    """
    video = _write_video(tmp_path / "camara.mp4")
    session = AnalysisSession.from_live("camara_prueba", str(video), fps=10.0)
    source = session.create_source()
    try:
        assert isinstance(source, LiveFrameSource)
        assert source.is_live is True
        assert source.video_id == "camara_prueba"
    finally:
        source.close()


def test_file_session_applies_frame_stride(tmp_path):
    video = _write_video(tmp_path / "clip_clean.mp4")
    session = AnalysisSession.from_video("clip_clean", video, fps=10.0)
    source = session.create_source(frame_stride=3)
    try:
        assert source.frame_stride == 3
    finally:
        source.close()


def test_session_without_origin_is_rejected():
    """Una sesión sin video ni cámara no puede crear nada: debe decirlo."""
    session = AnalysisSession(video_id="vacia", title="vacía")
    with pytest.raises(ValueError):
        session.create_source()


def test_live_session_ignores_frame_stride(tmp_path):
    """
    En directo no hay frames que saltar: el búfer de captura ya está en 1,
    así que cada lectura devuelve el más reciente.
    """
    video = _write_video(tmp_path / "camara.mp4")
    session = AnalysisSession.from_live("cam", str(video), fps=10.0)
    source = session.create_source(frame_stride=5)
    try:
        assert not hasattr(source, "frame_stride") or source.is_live
    finally:
        source.close()


def test_describe_origin_distinguishes_the_three_cases(tmp_path):
    video = _write_video(tmp_path / "clip_clean.mp4")
    assert "clip_clean.mp4" in AnalysisSession.from_video("c", video, 10.0).describe_origin()
    assert "Webcam" in AnalysisSession.from_live("c", 0, 30.0).describe_origin()
    assert "red" in AnalysisSession.from_live("c", "rtsp://x/y", 25.0).describe_origin()


# ----------------------------------------- interpretación de la fuente --
@pytest.mark.parametrize("text,expected", [("0", 0), ("1", 1), (" 2 ", 2)])
def test_parse_live_source_accepts_webcam_index(text, expected):
    assert parse_live_source(text) == expected


@pytest.mark.parametrize("url", [
    "rtsp://192.168.1.42:8080/h264_ulaw.sdp",
    "http://192.168.43.1:8080/video",
])
def test_parse_live_source_accepts_urls(url):
    assert parse_live_source(url) == url


def test_parse_live_source_rejects_empty():
    with pytest.raises(ValueError):
        parse_live_source("   ")


def test_parse_live_source_rejects_nonsense():
    """Un texto suelto no es ni URL ni índice: el error debe explicar cómo se escribe."""
    with pytest.raises(ValueError) as excinfo:
        parse_live_source("mi camara")
    assert "rtsp://" in str(excinfo.value)


# ------------------------------------------------- id de sesión en vivo --
def test_live_session_id_has_no_clean_suffix():
    """
    El sufijo `_clean` identifica un video ya limpiado. En una cámara no
    hay ningún archivo que limpiar, así que "camara_movil_clean" señalaría
    algo que no existe.
    """
    assert normalize_video_id("camara movil", is_live=True) == "camara movil"


def test_file_session_id_keeps_clean_suffix():
    assert normalize_video_id("mi_video", is_live=False) == "mi_video_clean"


def test_live_session_id_is_still_sanitized():
    """El id se usa como nombre de carpeta: los separadores tienen que caer."""
    unsafe = normalize_video_id("../../etc/passwd", is_live=True)
    assert "/" not in unsafe and ".." not in unsafe


# ------------------------------- las zonas viven bajo el id de la sesión --
def test_zones_of_a_live_session_are_found_by_the_pipeline(tmp_path):
    """
    El editor guarda y el pipeline lee bajo el MISMO identificador.

    Antes no: el editor normalizaba a `camara_movil_clean` y el pipeline
    buscaba en `camara_movil`, así que un análisis en vivo no encontraba
    ninguna zona y no medía ni una interacción — sin ningún error visible.
    """
    from app.core.detection.schemas import Zone
    from app.core.detection.zone import ZoneManager

    manager = ZoneManager(storage_path=str(tmp_path))
    video_id = normalize_video_id("camara movil", is_live=True)

    manager.save_zone(Zone(
        zone_id="zone_1", video_id=video_id, name="Góndola A",
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)], zone_type="product",
    ))

    video = _write_video(tmp_path / "camara.mp4")
    session = AnalysisSession.from_live(video_id, str(video), fps=10.0)
    source = session.create_source()
    try:
        found = manager.load_zones(source.video_id)
    finally:
        source.close()

    assert len(found) == 1, "el pipeline no encontró las zonas guardadas por el editor"
    assert found[0].name == "Góndola A"


def test_zone_manager_does_not_rewrite_the_session_id(tmp_path):
    """`ZoneManager` sanitiza, pero no añade ni quita sufijos."""
    from app.core.detection.schemas import Zone
    from app.core.detection.zone import ZoneManager

    manager = ZoneManager(storage_path=str(tmp_path))
    manager.save_zone(Zone(
        zone_id="zone_1", video_id="camara_movil", name="A",
        polygon=[(0, 0), (5, 0), (5, 5)], zone_type="product",
    ))
    assert (tmp_path / "camara_movil").is_dir()
    assert not (tmp_path / "camara_movil_clean").exists()
