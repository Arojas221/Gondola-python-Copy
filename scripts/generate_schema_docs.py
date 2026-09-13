"""
Generador de documentación de contratos de datos (Team 2 <-> Team 3 / Team 4).

Genera `docs/event_schema.md` y `docs/zone_schema.md` a partir de los modelos
Pydantic reales (`app/core/detection/schemas.py` y `app/core/detection/zone.py`).
Nunca editar los .md a mano: si el esquema cambia, cambiar el código y regenerar.

Uso:
    python -m scripts.generate_schema_docs
"""
import inspect
from pathlib import Path
from typing import get_type_hints

from app.core.detection import schemas as schemas_module
from app.core.detection import zone as zone_module

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

GENERATED_BANNER = (
    "<!-- AUTO-GENERADO por scripts/generate_schema_docs.py — no editar a mano.\n"
    "     Si el esquema cambia, regenerar con: python -m scripts.generate_schema_docs -->\n"
)

REGENERATE_FOOTER = (
    "\n---\n\n"
    "*Este documento se genera automáticamente desde el código "
    "(`scripts/generate_schema_docs.py`). Regeneración: "
    "`python -m scripts.generate_schema_docs`.*\n"
)


def _fmt_type(annotation) -> str:
    """Convierte una anotación de tipo (typing) a texto legible."""
    name = getattr(annotation, "__name__", None)
    # Tipos simples del lenguaje: usamos su nombre corto
    if name and getattr(annotation, "__module__", "") == "builtins":
        return name
    # Tipos genéricos (Literal, Tuple, List, Optional, ...): repr legible
    return str(annotation).replace("typing.", "")


def _fmt_default(field) -> str:
    if field.is_required():
        return "requerido"
    if field.default_factory is not None:
        fn = getattr(field.default_factory, "__name__", str(field.default_factory))
        return f"auto: {fn}()"
    return f"`{field.default!r}`"


def _model_doc(model) -> str:
    """Renderiza una sección markdown para un modelo Pydantic."""
    lines = [f"### `{model.__name__}`\n"]

    docstring = inspect.getdoc(model)
    if docstring:
        # Solo el primer párrafo como descripción compacta
        paragraph = docstring.split("\n\n")[0].replace("\n", " ")
        lines.append(paragraph + "\n")

    lines.append("| Campo | Tipo | Default | Descripción |")
    lines.append("|-------|------|---------|-------------|")

    hints = get_type_hints(model, include_extras=True)
    for name, field in model.model_fields.items():
        ftype = _fmt_type(hints.get(name, field.annotation))
        default = _fmt_default(field)
        description = (field.description or "—").replace("|", "\\|")
        lines.append(f"| `{name}` | `{ftype}` | {default} | {description} |")

    return "\n".join(lines)


def _load_zone_example() -> str:
    """Lee un archivo real de data/zones/<video_id>/ para usarlo como ejemplo (sin drift)."""
    zones_dir = Path(__file__).resolve().parent.parent / "data" / "zones"
    for f in sorted(zones_dir.glob("**/*.json")):
        return f.read_text(encoding="utf-8").strip()
    return ""

# --------------------------------------------------------------------------
# docs/event_schema.md
# --------------------------------------------------------------------------
EVENT_SCHEMA_INTRO = """
Contrato de datos entre el **pipeline de detección (Team 2)**, el
**backend/almacenamiento (Team 3)** y el **dashboard (Team 4)**.

## Transporte (MVP: in-process)

Todo corre en el mismo proceso (pipeline, backend y dashboard, en hilos
distintos), así que el transporte del MVP es **in-process, vía señales Qt**:

1. El pipeline publica cualquier modelo Pydantic a través de `EventPublisher`
   (`app/core/detection/event_publisher.py`).
2. `InProcessPublisher` convierte el modelo a `dict` (`model_dump()`) y lo
   emite por su señal `event_emitted = Signal(dict)`.
3. Cualquier widget/worker se conecta a esa señal; las conexiones entre
   hilos se ponen en cola automáticamente (sin bloquear la UI).

Los modos `file` y `stdout` de `LocalEventPublisher` siguen disponibles para
debug/logging y no cambian de contrato.

> **Fuera de alcance del MVP:** si en el futuro esté sistema corriera en
> varias máquinas/dispositivos edge, un transporte de red (WebSocket o MQTT)
> sería el siguiente paso razonable — el contrato de datos (modelos Pydantic)
> es agnóstico del medio de transporte, así que solo habría que añadir un
> `EventPublisher` nuevo.

## Flujo de datos

```
DetectionPipeline ──publish(BaseModel)──► EventPublisher
                                              │
                         ┌────────────────────┴───────────────┐
                         │ InProcessPublisher (Signal(dict)) │
                         └──────────────┬────────────────────┘
                                        ▼
                 EventStore (SQLite)  /  Dashboard (Qt widgets)
```

El despacho por tipo en el receptor (p.ej. `EventStore.on_bus_message`) se
hace por campos distintivos del payload: `foot_position` => `PositionSample`,
`duration_sec` => `DwellRecord`, `event_id` + `action` => `InteractionEvent`.

## Modelos del bus
"""

# --------------------------------------------------------------------------
# docs/zone_schema.md
# --------------------------------------------------------------------------
ZONE_SCHEMA_INTRO = f"""
Una **zona** es un polígono sobre el frame de referencia que marca una región
de la góndola (estante, pasillo, producto sensible, etc.). La definen usuarios
con la pestaña de edición (`app/ui/zone_editor_tab.py`, Team 4) y la consumen
las señales geométricas del pipeline (`app/core/detection/zone.py`, Team 2) y,
en el futuro, los cálculos de dwell time del dashboard.

## Persistencia

`ZoneManager` (`app/core/detection/zone.py`) guarda **un archivo JSON por
zona**, agrupados en una subcarpeta por video/cámara:
`data/zones/<video_id>/<zone_id>.json`. Esto evita que las zonas de un video
se mezclen con las de otro al cargar. El formato del archivo es exactamente
`Zone.model_dump()` — no hay un formato de datos aparte.

Ejemplo de un archivo real en este repositorio (`data/zones/`):

```json
{_load_zone_example()}
```

## Modelos del contrato
"""


def _write_doc(filename: str, title: str, intro: str, models, extra: str = "") -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    parts = [
        GENERATED_BANNER,
        f"# {title}\n",
        intro,
        *[f"{_model_doc(model)}\n" for model in models],
        extra,
        REGENERATE_FOOTER,
    ]
    (DOCS_DIR / filename).write_text("\n".join(parts), encoding="utf-8")
    print(f"Generado: {DOCS_DIR / filename}")


def main() -> None:
    _write_doc(
        "event_schema.md",
        "Esquema de Eventos",
        EVENT_SCHEMA_INTRO,
        models=[schemas_module.InteractionEvent, schemas_module.PositionSample, schemas_module.DwellRecord],
    )
    _write_doc(
        "zone_schema.md",
        "Esquema de Zonas (ROI)",
        ZONE_SCHEMA_INTRO,
        models=[schemas_module.Zone, schemas_module.ZoneSignal],
        extra=(
            "> `ZoneSignal` es la señal interna que consume la máquina de "
            "estados (`state_machine.py`) por cada persona y zona en cada "
            "frame; se documenta aquí porque también alimenta cálculos de "
            "dwell time futuros del dashboard.\n"
        ),
    )
    print("Documentación de esquemas regenerada.")


if __name__ == "__main__":
    main()