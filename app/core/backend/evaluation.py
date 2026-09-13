"""
Evaluación del pipeline de detección a nivel de eventos (Team 3 / QA).

Métricas de clasificación (precision / recall / F1) comparando los
`InteractionEvent` emitidos por el pipeline contra un ground-truth
de anotación manual (GT).

Regla de emparejamiento: un evento predicho coincide con uno de GT si
tienen la misma `zone_id` y `action`, y sus timestamps caen dentro de
una ventana temporal (± `tolerance_sec`). Cada evento de GT y cada
predicción solo pueden emparejarse una vez (greedy por menor delta).
"""
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.detection.schemas import InteractionEvent


@dataclass
class GroundTruthEvent:
    """
    Evento esperado (anotación manual).

    No incluye `track_id`: en el GT no se conoce a priori qué identidad
    fija el tracker para esa persona.
    """
    zone_id: str
    action: str
    timestamp: float


def load_ground_truth(path: str | Path) -> list[GroundTruthEvent]:
    """
    Carga el ground truth desde un archivo JSON (lista de eventos):

        [
          {"zone_id": "zone_1", "action": "taken", "timestamp": 12.5},
          ...
        ]
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = []
    for item in data:
        events.append(GroundTruthEvent(
            zone_id=item["zone_id"],
            action=item["action"],
            timestamp=float(item["timestamp"]),
        ))
    return events


def match_events(
    gt_events: list[GroundTruthEvent],
    predicted_events: list[InteractionEvent],
    tolerance_sec: float = 1.0,
) -> dict[str, int]:
    """
    Empareja eventos predichos contra GT con ventana temporal ±tolerance_sec.

    Returns:
        {"tp": int, "fp": int, "fn": int}
        - tp: predicciones que coincidieron con un GT.
        - fp: predicciones sin GT (falsos positivos).
        - fn: GT sin predicción (falsos negativos).
    """
    gt_available = [True] * len(gt_events)
    pred_used = [False] * len(predicted_events)

    # Candidatos (delta, índice_gt, índice_pred) ordenados por delta temporal
    candidates = []
    for g_idx, gt in enumerate(gt_events):
        for p_idx, pred in enumerate(predicted_events):
            if gt.zone_id != pred.zone_id or gt.action != pred.action:
                continue
            delta = abs(pred.timestamp - gt.timestamp)
            if delta <= tolerance_sec:
                candidates.append((delta, g_idx, p_idx))
    candidates.sort(key=lambda c: c[0])

    tp = 0
    for _, g_idx, p_idx in candidates:
        if gt_available[g_idx] and not pred_used[p_idx]:
            gt_available[g_idx] = False
            pred_used[p_idx] = True
            tp += 1

    fn = len(gt_events) - tp          # GT sin emparejar
    fp = len(predicted_events) - tp   # predicciones sin emparejar
    return {"tp": tp, "fp": fp, "fn": fn}


def compute_metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision, recall y F1 a partir de los conteos de emparejamiento."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
