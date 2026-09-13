"""
Selección automática del frame de referencia (Team 1).

Antes, el frame sobre el que se dibujan las zonas era siempre el que
estuviera al 10% de la duración (`extract_thumbnail`). Eso es arbitrario:
ese frame puede estar movido, mal iluminado o con tres personas tapando
justamente la góndola que se quiere marcar.

Este módulo elige un frame *bueno* muestreando el video y puntuando cada
candidato por dos criterios:

- **Nitidez**: varianza del Laplaciano. Un frame movido o desenfocado
  tiene bordes suaves y por lo tanto varianza baja; los bordes son
  exactamente lo que después usa `roi_suggester` para encontrar los
  estantes, así que un frame nítido no es un lujo estético.
- **Ocupación**: cuánta gente hay delante. Un frame con la góndola
  despejada permite marcar el estante completo; uno con clientes encima
  hace que el usuario dibuje alrededor de las personas.

El detector de personas se inyecta (`people_detector`) en vez de
importarse: así este módulo no arrastra a `ultralytics` y se puede probar
sin modelos. Si no se pasa ninguno, la elección se hace solo por nitidez.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Union

import cv2
import numpy as np

from app.utils.config import REFERENCE_FRAME_SAMPLES

# Penalización por persona detectada, en unidades de score normalizado
# [0, 1]. Con 0.15, un frame perfectamente nítido con 3 personas encima
# pierde contra uno un poco menos nítido pero despejado — que es
# justamente el criterio que queremos.
PEOPLE_PENALTY = 0.15


@dataclass
class ReferenceFrame:
    """Frame elegido como referencia, con las métricas que lo eligieron."""
    frame: np.ndarray
    frame_index: int
    sharpness: float
    people: int
    candidates: int


def sharpness_score(frame: np.ndarray) -> float:
    """
    Varianza del Laplaciano: medida clásica de enfoque.

    Un frame nítido tiene muchos bordes marcados (Laplaciano con valores
    altos y dispersos → varianza alta); uno movido o desenfocado los tiene
    suavizados → varianza baja.
    """
    if frame is None or frame.size == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def score_candidates(
    sharpness_values: List[float],
    people_counts: List[int],
    people_penalty: float = PEOPLE_PENALTY,
) -> List[float]:
    """
    Combina nitidez y ocupación en un score comparable.

    La nitidez se normaliza al rango [0, 1] *dentro del propio video* (su
    escala absoluta depende de la cámara, la resolución y la compresión,
    así que un umbral fijo no sirve entre videos distintos). A eso se le
    resta la penalización por personas detectadas.

    Aislado de la lectura del video para poder probarlo sin abrir archivos.
    """
    if not sharpness_values:
        return []

    lo, hi = min(sharpness_values), max(sharpness_values)
    span = hi - lo
    scores = []
    for i, sharp in enumerate(sharpness_values):
        normalized = (sharp - lo) / span if span > 0 else 1.0
        people = people_counts[i] if i < len(people_counts) else 0
        scores.append(normalized - people_penalty * people)
    return scores


def pick_reference_frame(
    video_path: Union[str, Path],
    samples: int = REFERENCE_FRAME_SAMPLES,
    people_detector: Optional[Callable[[np.ndarray], int]] = None,
) -> Optional[ReferenceFrame]:
    """
    Muestrea `samples` frames repartidos por el video y devuelve el mejor.

    Se ignora el primer y el último 5% del video: los extremos suelen traer
    fundidos, ajustes de exposición de la cámara o el corte de la grabación.

    `people_detector(frame) -> int` es opcional; sin él la elección es solo
    por nitidez. Devuelve None si el video no se puede leer.
    """
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        return None

    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            # Algunos contenedores no reportan el conteo de frames: se cae
            # a leer secuencialmente los primeros `samples` frames.
            frames, indices = _read_sequential(cap, samples)
        else:
            frames, indices = _read_sampled(cap, total, samples)
    finally:
        cap.release()

    if not frames:
        return None

    sharpness_values = [sharpness_score(f) for f in frames]
    people_counts = []
    if people_detector is not None:
        for frame in frames:
            try:
                people_counts.append(int(people_detector(frame)))
            except Exception:  # noqa: BLE001 - un fallo del detector no debe tumbar la selección
                people_counts.append(0)
    else:
        people_counts = [0] * len(frames)

    scores = score_candidates(sharpness_values, people_counts)
    best = max(range(len(scores)), key=lambda i: scores[i])

    return ReferenceFrame(
        frame=frames[best],
        frame_index=indices[best],
        sharpness=sharpness_values[best],
        people=people_counts[best],
        candidates=len(frames),
    )


def _read_sampled(cap, total: int, samples: int):
    """Lee `samples` frames repartidos entre el 5% y el 95% del video."""
    start, end = int(total * 0.05), int(total * 0.95)
    if end <= start:
        start, end = 0, max(total - 1, 0)

    step = max(1, (end - start) // max(samples, 1))
    frames, indices = [], []
    for idx in range(start, end + 1, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
            indices.append(idx)
        if len(frames) >= samples:
            break
    return frames, indices


def _read_sequential(cap, samples: int):
    """Fallback cuando el contenedor no reporta cuántos frames tiene."""
    frames, indices = [], []
    idx = 0
    while len(frames) < samples:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        frames.append(frame)
        indices.append(idx)
        idx += 1
    return frames, indices


def build_people_detector(conf: float = 0.4) -> Callable[[np.ndarray], int]:
    """
    Detector de personas para `pick_reference_frame`, construido sobre el
    mismo YOLO que usa el pipeline.

    El import de `ultralytics` es perezoso a propósito: cargar el modelo
    tarda y este módulo se importa también desde tests que no lo necesitan.
    """
    from ultralytics import YOLO  # import local: ver docstring

    from app.utils.config import DETECTION_MODEL_NAME

    model = YOLO(DETECTION_MODEL_NAME)

    def _count(frame: np.ndarray) -> int:
        results = model.predict(frame, classes=[0], conf=conf, verbose=False)
        return sum(len(r.boxes) for r in results if r.boxes is not None)

    return _count
