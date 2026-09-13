"""
Tests de la selección automática del frame de referencia.

La puntuación (nitidez + ocupación) se prueba aislada, sin abrir archivos;
la lectura del video se prueba sobre un .mp4 sintético escrito con OpenCV.
"""
import cv2
import numpy as np
import pytest

from app.core.ingestion.frame_picker import (
    pick_reference_frame,
    score_candidates,
    sharpness_score,
)


def _sharp_frame(width: int = 160, height: int = 120) -> np.ndarray:
    """Frame con bordes duros: alta varianza del Laplaciano."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, ::8] = 255      # franjas verticales de 1 px
    frame[::8, :] = 255      # franjas horizontales de 1 px
    return frame


def _blurry_frame(width: int = 160, height: int = 120) -> np.ndarray:
    """El mismo patrón, desenfocado: la varianza cae."""
    return cv2.GaussianBlur(_sharp_frame(width, height), (15, 15), 0)


# ------------------------------------------------------------- nitidez --
def test_sharpness_prefers_sharp_over_blurry():
    assert sharpness_score(_sharp_frame()) > sharpness_score(_blurry_frame())


def test_sharpness_of_flat_frame_is_zero():
    """Un frame de un solo color no tiene ningún borde."""
    assert sharpness_score(np.full((50, 50, 3), 128, dtype=np.uint8)) == pytest.approx(0.0)


def test_sharpness_of_empty_frame_is_zero():
    assert sharpness_score(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0


# ---------------------------------------------------------- puntuación --
def test_score_candidates_normalizes_to_unit_range():
    scores = score_candidates([10.0, 20.0, 30.0], [0, 0, 0])
    assert scores[0] == pytest.approx(0.0)
    assert scores[-1] == pytest.approx(1.0)


def test_score_candidates_penalizes_crowded_frames():
    """
    El frame más nítido pierde si tiene gente tapando la góndola, siempre
    que otro candidato sea casi tan nítido y esté despejado — que es
    justamente el criterio que queremos.
    """
    # Índice 0: el más nítido, pero con 4 personas encima.
    # Índice 1: casi igual de nítido y despejado -> debe ganar.
    scores = score_candidates([100.0, 98.0, 50.0, 40.0], [4, 0, 0, 0], people_penalty=0.15)
    assert scores.index(max(scores)) == 1


def test_score_candidates_without_people_picks_the_sharpest():
    scores = score_candidates([50.0, 100.0, 75.0], [0, 0, 0])
    assert scores.index(max(scores)) == 1


def test_score_candidates_with_identical_sharpness_falls_back_to_people():
    """Sin diferencia de nitidez, decide la ocupación."""
    scores = score_candidates([50.0, 50.0], [2, 0])
    assert scores[1] > scores[0]


def test_score_candidates_empty_input():
    assert score_candidates([], []) == []


# -------------------------------------------------------- lectura real --
def _write_video(path, frames, fps: float = 10.0):
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for frame in frames:
        writer.write(frame)
    writer.release()


def test_pick_reference_frame_prefers_the_sharp_section(tmp_path):
    """
    Video con la primera mitad desenfocada y la segunda nítida: el frame
    elegido debe caer en la segunda.
    """
    video_path = tmp_path / "clip.mp4"
    frames = [_blurry_frame() for _ in range(20)] + [_sharp_frame() for _ in range(20)]
    _write_video(video_path, frames)

    reference = pick_reference_frame(video_path, samples=8)

    assert reference is not None
    assert reference.frame_index >= 20
    assert reference.candidates > 1


def test_pick_reference_frame_applies_the_people_detector(tmp_path):
    """
    Con todos los frames igual de nítidos, decide el detector de personas:
    el único frame que reporta 0 personas es el que debe ganar.
    """
    video_path = tmp_path / "clip.mp4"
    _write_video(video_path, [_sharp_frame() for _ in range(30)])

    calls = {"n": 0}

    def _detector(_frame):
        calls["n"] += 1
        # 8 personas penalizan 1.2, por encima del rango completo de la
        # nitidez normalizada (0..1): el frame despejado gana seguro.
        return 0 if calls["n"] == 3 else 8

    reference = pick_reference_frame(video_path, samples=6, people_detector=_detector)

    assert reference is not None
    assert reference.people == 0


def test_pick_reference_frame_survives_a_failing_detector(tmp_path):
    """Un detector que revienta no debe tumbar la elección del frame."""
    video_path = tmp_path / "clip.mp4"
    _write_video(video_path, [_sharp_frame() for _ in range(10)])

    def _broken(_frame):
        raise RuntimeError("modelo no disponible")

    reference = pick_reference_frame(video_path, samples=4, people_detector=_broken)

    assert reference is not None
    assert reference.people == 0


def test_pick_reference_frame_on_missing_file_returns_none(tmp_path):
    assert pick_reference_frame(tmp_path / "no_existe.mp4") is None
