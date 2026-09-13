"""
Tests de la evaluación a nivel de eventos (P/R/F1).
"""
import json

import pytest

from app.core.backend.evaluation import (
    GroundTruthEvent,
    compute_metrics,
    load_ground_truth,
    match_events,
)
from app.core.detection.schemas import InteractionEvent


def _gt(zone_id: str, timestamp: float, action: str = "taken") -> GroundTruthEvent:
    return GroundTruthEvent(zone_id=zone_id, action=action, timestamp=timestamp)


def _pred(zone_id: str, timestamp: float, action: str = "taken") -> InteractionEvent:
    return InteractionEvent(
        track_id=1, zone_id=zone_id, action=action, timestamp=timestamp
    )


def test_perfect_match():
    """GT y predicciones idénticas -> todo TP, nada de FP/FN."""
    gt = [_gt("zone_1", 10.0), _gt("zone_1", 20.0)]
    pred = [_pred("zone_1", 10.0), _pred("zone_1", 20.0)]

    counts = match_events(gt, pred, tolerance_sec=1.0)
    assert counts == {"tp": 2, "fp": 0, "fn": 0}
    assert compute_metrics(2, 0, 0) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_tolerance_window():
    """Dentro de ±tolerance es TP; fuera de la ventana no hay match."""
    gt = [_gt("zone_1", 10.0)]

    inside = match_events(gt, [_pred("zone_1", 10.5)], tolerance_sec=1.0)
    assert inside["tp"] == 1

    outside = match_events(gt, [_pred("zone_1", 12.0)], tolerance_sec=1.0)
    assert outside == {"tp": 0, "fp": 1, "fn": 1}


def test_extra_prediction_is_fp():
    """Predicción sin GT correspondiente -> FP."""
    gt = [_gt("zone_1", 10.0)]
    pred = [_pred("zone_1", 10.0), _pred("zone_1", 30.0)]

    counts = match_events(gt, pred, tolerance_sec=1.0)
    assert counts == {"tp": 1, "fp": 1, "fn": 0}
    metrics = compute_metrics(1, 1, 0)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == pytest.approx(2.0 / 3.0, abs=1e-4)


def test_missing_gt_events_are_fn():
    """GT sin predicción correspondiente -> FN."""
    gt = [_gt("zone_1", 10.0), _gt("zone_1", 40.0)]
    pred = [_pred("zone_1", 10.0)]

    counts = match_events(gt, pred, tolerance_sec=1.0)
    assert counts == {"tp": 1, "fp": 0, "fn": 1}


def test_zone_mismatch_not_matched():
    """Misma zona requerida: zona distinta nunca se empareja."""
    gt = [_gt("zone_1", 10.0)]
    pred = [_pred("zone_2", 10.0)]

    counts = match_events(gt, pred, tolerance_sec=1.0)
    assert counts == {"tp": 0, "fp": 1, "fn": 1}


def test_each_event_used_once():
    """Un GT y una predicción no pueden emparejarse dos veces (greedy por delta)."""
    gt = [_gt("zone_1", 10.0), _gt("zone_1", 10.1)]
    pred = [_pred("zone_1", 10.15)]

    # La predicción cubre solo a una de las dos GTs (la de menor delta)
    counts = match_events(gt, pred, tolerance_sec=1.0)
    assert counts == {"tp": 1, "fp": 0, "fn": 1}


def test_empty_inputs():
    """Sin GT ni predicciones: métricas indefinidas = 0."""
    counts = match_events([], [], tolerance_sec=1.0)
    assert counts == {"tp": 0, "fp": 0, "fn": 0}
    assert compute_metrics(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_load_ground_truth(tmp_path):
    """Carga el GT desde el JSON documentado en el script."""
    path = tmp_path / "gt.json"
    path.write_text(
        json.dumps([
            {"zone_id": "zone_1", "action": "taken", "timestamp": 12.5},
            {"zone_id": "zone_2", "action": "taken", "timestamp": 18.2},
        ]),
        encoding="utf-8",
    )

    events = load_ground_truth(path)
    assert len(events) == 2
    assert events[0].zone_id == "zone_1"
    assert events[0].timestamp == 12.5