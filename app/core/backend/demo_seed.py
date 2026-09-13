"""
Sembrado de datos de demostración para el dashboard (Team 3/4).

El pipeline de detección (tabs 3/4, aún no integradas a la UI) es la fuente
real de eventos: mientras no corre, `EventStore` está vacío y el dashboard
no tiene nada que graficar. Esta función llena esa sesión vacía con
telemetría sintética pero *estructuralmente idéntica* a la real (mismos
modelos Pydantic, mismas reglas del `state_machine`: taken/returned
alternan por track dentro de cada zona) para que el dashboard sea
demostrable de inmediato — y deje de usarse en cuanto haya eventos reales.
"""
import random

from app.core.backend.event_store import EventStore
from app.core.detection.schemas import DwellRecord, InteractionEvent, PositionSample, Zone

# Resolución del frame de referencia (la misma que el video ya limpiado en
# data/processed/USA CCTV Market Camera_clean.json) — los polígonos de zona
# están expresados en estos ejes, así que las trayectorias sintéticas deben
# moverse en el mismo espacio de píxeles para que el heatmap calce con el ROI.
FRAME_SIZE = (1280, 720)


def has_data(store: EventStore, video_id: str | None = None) -> bool:
    """
    True si la sesión ya tiene al menos un evento **real** (no sembrado).

    Antes esto contaba todos los eventos, así que sembrar la demo lo volvía
    True y el dashboard dejaba de avisar que estaba mostrando datos
    sintéticos. Ahora las filas de demo no cuentan: el aviso se mantiene
    hasta que haya un análisis de verdad.
    """
    return store.count_real_events(video_id) > 0


def _polygon_centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _seed_walk_to_zone(store: EventStore, rng: random.Random, track_id: int,
                        centroid: tuple[float, float], entry_ts: float, exit_ts: float,
                        is_employee: bool) -> None:
    """
    Publica los `PositionSample` (pie de la persona, por frame) de una
    caminata desde un punto de entrada al borde del frame hasta el
    centroide de la zona, y una permanencia con jitter mientras dura el
    dwell — es el mismo dato continuo que en producción publica el pipeline
    en cada frame (`app/core/detection/trajectory.py`), aquí sintetizado
    para que el heatmap tenga algo que dibujar sin correr el pipeline.
    """
    w, h = FRAME_SIZE
    edge = rng.choice(["left", "right", "top", "bottom"])
    if edge == "left":
        start = (0.0, rng.uniform(0, h))
    elif edge == "right":
        start = (w, rng.uniform(0, h))
    elif edge == "top":
        start = (rng.uniform(0, w), 0.0)
    else:
        start = (rng.uniform(0, w), h)

    walk_steps = rng.randint(8, 14)
    frame = 0
    for i in range(walk_steps):
        frac = (i + 1) / walk_steps
        x = start[0] + (centroid[0] - start[0]) * frac + rng.uniform(-12, 12)
        y = start[1] + (centroid[1] - start[1]) * frac + rng.uniform(-12, 12)
        ts = entry_ts - (walk_steps - i) * ((entry_ts - (entry_ts - 2.5)) / walk_steps)
        store.insert_position_sample(PositionSample(
            track_id=track_id, frame_index=frame, original_timestamp_sec=round(max(ts, 0.0), 2),
            foot_position=(round(x, 1), round(y, 1)), is_employee=is_employee,
        ))
        frame += 1

    # Permanencia frente a la zona: el pie se queda cerca del centroide con
    # jitter pequeño (la persona no está perfectamente inmóvil).
    dwell_steps = max(3, int((exit_ts - entry_ts)))
    for i in range(dwell_steps):
        ts = entry_ts + (exit_ts - entry_ts) * (i / max(dwell_steps - 1, 1))
        x = centroid[0] + rng.uniform(-20, 20)
        y = centroid[1] + rng.uniform(-20, 20)
        store.insert_position_sample(PositionSample(
            track_id=track_id, frame_index=frame, original_timestamp_sec=round(ts, 2),
            foot_position=(round(x, 1), round(y, 1)), is_employee=is_employee,
        ))
        frame += 1


def seed_demo_session(
    store: EventStore,
    zones: list[Zone],
    seed: int = 7,
    video_id: str | None = None,
) -> int:
    """
    Genera eventos `taken`/`returned` + `DwellRecord` + `PositionSample`
    (trayectorias de pie) para las zonas de tipo 'product' de `zones`,
    respetando la alternancia taken->returned->taken por track (la misma
    regla que aplica `state_machine.py`).

    Todo lo que se inserta queda marcado `is_demo=1` en la base, y bajo el
    `video_id` de la sesión: son datos sintéticos, tienen que poder
    distinguirse y borrarse sin tocar los reales. Al terminar se restaura
    la sesión que el almacén tuviera antes.

    Devuelve la cantidad de InteractionEvent insertados.
    """
    rng = random.Random(seed)
    product_zones = [z for z in zones if z.zone_type == "product"]
    if not product_zones:
        return 0

    previous_session = store.session_video_id
    store.set_session(video_id or (product_zones[0].video_id if product_zones else ""), is_demo=True)

    next_track_id = 100
    inserted = 0
    t = 4.0

    for zone in product_zones:
        centroid = _polygon_centroid(zone.polygon)
        visits = rng.randint(6, 11)
        for _ in range(visits):
            track_id = next_track_id
            next_track_id += 1
            is_employee = rng.random() < 0.08

            entry = t
            dwell = round(rng.uniform(2.0, 9.0), 1)
            exit_ts = entry + dwell

            _seed_walk_to_zone(store, rng, track_id, centroid, entry, exit_ts, is_employee)

            store.insert_event(InteractionEvent(
                track_id=track_id, zone_id=zone.zone_id, action="taken",
                timestamp=round(exit_ts, 2), is_employee=is_employee,
            ))
            store.insert_dwell_record(DwellRecord(
                track_id=track_id, zone_id=zone.zone_id,
                entry_timestamp=round(entry, 2), exit_timestamp=round(exit_ts, 2),
                duration_sec=dwell, is_employee=is_employee,
            ))
            inserted += 1

            # ~30% de las visitas devuelven el producto poco después (misma
            # persona, mismo track, alternando la acción).
            if rng.random() < 0.3:
                return_ts = exit_ts + round(rng.uniform(1.0, 4.0), 1)
                store.insert_event(InteractionEvent(
                    track_id=track_id, zone_id=zone.zone_id, action="returned",
                    timestamp=round(return_ts, 2), is_employee=is_employee,
                ))
                inserted += 1
                t = return_ts
            else:
                t = exit_ts

            t += rng.uniform(1.5, 6.0)

    store.flush()
    store.set_session(previous_session, is_demo=False)
    return inserted
