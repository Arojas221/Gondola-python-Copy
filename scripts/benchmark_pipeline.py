"""
Benchmark de velocidad del pipeline de detección sobre un video real.

Mide por separado el costo de: tracker.track() (detección+tracking) y
pose_estimator.estimate() (pose), además del pipeline completo, para
poder reportarle a Scapder un número real medido en el hardware objetivo
(no una estimación de benchmarks públicos).

Uso:
    python -m scripts.benchmark_pipeline data/processed/<video>_clean.mp4 --max-frames 150
"""
import argparse
import time
from pathlib import Path

from app.core.ingestion.frame_source import VideoFileFrameSource
from app.core.detection.tracker import PersonTracker
from app.core.detection.pose import PoseEstimator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_path", type=str, help="Video limpio a procesar (data/processed/*_clean.mp4)")
    parser.add_argument("--max-frames", type=int, default=150, help="Cuántos frames medir (default: 150)")
    args = parser.parse_args()

    source = VideoFileFrameSource(args.video_path)
    tracker = PersonTracker()
    pose_estimator = PoseEstimator()

    tracker_times = []
    pose_times = []
    total_times = []

    n = 0
    while n < args.max_frames:
        sample = source.next_frame()
        if sample is None:
            break

        t0 = time.perf_counter()
        tracked_people = tracker.track(sample.frame, sample.frame_index)
        t1 = time.perf_counter()
        pose_estimator.estimate(sample.frame, sample.frame_index, tracked_people)
        t2 = time.perf_counter()

        tracker_times.append(t1 - t0)
        pose_times.append(t2 - t1)
        total_times.append(t2 - t0)
        n += 1

    source.close()

    def _stats(label: str, times: list[float]) -> None:
        avg_ms = (sum(times) / len(times)) * 1000
        fps = 1000 / avg_ms
        print(f"{label:20s}  avg={avg_ms:7.1f} ms/frame   ~{fps:5.1f} FPS")

    print(f"\n=== Benchmark: {n} frames de '{args.video_path}' ===")
    _stats("Detección+tracking", tracker_times)
    _stats("Pose", pose_times)
    _stats("Pipeline (ambos)", total_times)
    print(f"\nProyección: un video de 60s a 30fps (1800 frames) tardaría "
          f"~{(sum(total_times) / len(total_times)) * 1800:.0f} s en procesarse.")


if __name__ == "__main__":
    main()
