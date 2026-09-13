<!-- AUTO-GENERADO por scripts/generate_schema_docs.py — no editar a mano.
     Si el esquema cambia, regenerar con: python -m scripts.generate_schema_docs -->

# Esquema de Eventos


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

### `InteractionEvent`

Evento final de interacción enviado al bus de eventos y guardado localmente.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `track_id` | `int` | requerido | Identificador efímero de la persona en esta sesión de video |
| `zone_id` | `str` | requerido | Zona de góndola donde ocurrió la interacción |
| `action` | `Literal['reaching', 'holding', 'taken', 'returned']` | requerido | Tipo de interacción detectada. La máquina de estados solo distingue 'taken'/'returned' (no hay detección de producto): la primera interacción de una persona con una zona en la sesión es 'taken', las siguientes alternan a 'returned'/'taken' (heurístico, ver state_machine.py). 'reaching'/'holding' quedan reservados para una futura granularidad. |
| `timestamp` | `float` | requerido | Segundos traducidos al video original (o wall-clock en vivo) |
| `event_id` | `str` | auto: _new_event_id() | UUID para auditoría y deduplicación |
| `is_employee` | `bool` | `False` | True si el track fue marcado como empleado (StaffZoneTracker) antes o durante este evento |

### `PositionSample`

Muestra de posición continua de una persona en un frame.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `track_id` | `int` | requerido | Identificador efímero de la persona en esta sesión |
| `frame_index` | `int` | requerido | Índice en el stream de frames procesado |
| `original_timestamp_sec` | `float` | requerido | Segundos traducidos al video original (o wall-clock en vivo) |
| `foot_position` | `Tuple[float, float]` | requerido | Bottom-center del bbox como proxy del pie (x, y) |
| `camera_id` | `str` | `'cam_1'` | Escalable a multi-cámara en el futuro |
| `is_employee` | `bool` | `False` | True si el track fue marcado como empleado (StaffZoneTracker) al momento de esta muestra |

### `DwellRecord`

Registro de tiempo de permanencia de una persona dentro de una zona de producto.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `event_type` | `Literal['dwell']` | `'dwell'` | — |
| `track_id` | `int` | requerido | Identificador efímero de la persona en esta sesión |
| `zone_id` | `str` | requerido | Zona de producto donde se registró la permanencia |
| `entry_timestamp` | `float` | requerido | Segundos (video original) en que la persona entró a la zona |
| `exit_timestamp` | `float` | requerido | Segundos (video original) en que la persona salió de la zona |
| `duration_sec` | `float` | requerido | Duración de la permanencia, en segundos |
| `is_employee` | `bool` | `False` | True si el track estaba marcado como empleado al salir de la zona |
| `event_id` | `str` | auto: _new_event_id() | UUID para auditoría y deduplicación |



---

*Este documento se genera automáticamente desde el código (`scripts/generate_schema_docs.py`). Regeneración: `python -m scripts.generate_schema_docs`.*
