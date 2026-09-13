"""
Evaluación del pipeline de detección a nivel de eventos (P/R/F1).

Corre el pipeline completo sobre un video limpio, captura los
`InteractionEvent` emitidos en memoria y los compara contra un
ground-truth manual para calcular precision / recall / F1.

Ground truth (JSON, lista de eventos esperados):

    [
      {"zone_id": "zone_1", "action": "taken", "timestamp": 12.5},
      {"zone_id": "zone_1", "action": "taken", "timestamp": 18.2}
    ]

    - `timestamp`: segundo del video ORIGINAL (el pipeline traduce los
      timestamps con el frame_mapping del sidecar, no con el video limpio).

Uso:

    python -m scripts.evaluate_pipeline --video data/processed/mi_video_clean.mp4 \
        --gt data/ground_truth_events.json [--tolerance 1.0] [--out reports/eval.json]
"""
import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from app.core.backend.evaluation import (
    GroundTruthEvent,
    compute_metrics,
    load_ground_truth,
    match_events,
)
from app.core.detection.event_publisher import EventPublisher
from app.core.detection.pipeline import DetectionPipeline
from app.core.detection.pose import PoseEstimator
from app.core.detection.state_machine import InteractionStateMachine
from app.core.detection.tracker import PersonTracker
from app.core.detection.zone import ZoneManager
from app.core.ingestion.frame_source import VideoFileFrameSource


class _CollectingPublisher(EventPublisher):
    """Recolecta los InteractionEvent emitidos en memoria (sin tocar disco ni red)."""

    def __init__(self):
        self.events = []

    def publish(self, event: BaseModel) -> None:
        # El bus transporta InteractionEvent y PositionSample; aquí solo
        # interesan los eventos de interacción (despacho por campos distintivos).
        if hasattr(event, "action") and hasattr(event, "event_id"):
            self.events.append(event)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluación de eventos del pipeline (precision/recall/F1)."
    )
    parser.add_argument("--video", type=str, required=True,
                        help="Video limpio (.mp4) a evaluar.")
    parser.add_argument("--gt", type=str, required=True,
                        help="JSON con los eventos esperados (ground truth).")
    parser.add_argument("--tolerance", type=float, default=1.0,
                        help="Ventana temporal ±segundos (video original) para emparejar.")
    parser.add_argument("--out", type=str, default=None,
                        help="(opcional) Ruta para guardar el reporte JSON.")
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"Error: No se encontró el video {args.video}")
        return
    if not Path(args.gt).exists():
        print(f"Error: No se encontró el ground truth {args.gt}")
        return

    gt_events = load_ground_truth(args.gt)
    print(f"Ground truth cargado: {len(gt_events)} evento(s) esperado(s).")

    # Pipeline completo (la FrameSource fija el fps real y traduce timestamps)
    source = VideoFileFrameSource(args.video)
    publisher = _CollectingPublisher()
    pipeline = DetectionPipeline(
        tracker=PersonTracker(),
        pose_estimator=PoseEstimator(),
        zone_manager=ZoneManager(),
        state_machine=InteractionStateMachine(fps=source.fps),
        event_publisher=publisher,
    )
    pipeline.run(source)  # cierra la fuente al terminar

    predicted = publisher.events
    print(f"Pipeline terminado: {len(predicted)} evento(s) emitido(s).")

    counts = match_events(gt_events, predicted, tolerance_sec=args.tolerance)
    metrics = compute_metrics(counts["tp"], counts["fp"], counts["fn"])

    report = {
        "video": args.video,
        "ground_truth": args.gt,
        "tolerance_sec": args.tolerance,
        "counts": counts,
        "metrics": metrics,
        "predicted_events": [e.model_dump() for e in predicted],
    }

    print("\n=== Reporte de evaluación (eventos) ===")
    print(f"GT: {len(gt_events)} | Emitidos: {len(predicted)} "
          f"| TP: {counts['tp']} | FP: {counts['fp']} | FN: {counts['fn']}")
    print(f"Precision: {metrics['precision']:.4f}  "
          f"Recall: {metrics['recall']:.4f}  "
          f"F1: {metrics['f1']:.4f}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Reporte guardado en: {out_path}")


if __name__ == "__main__":
    main()