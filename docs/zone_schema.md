<!-- AUTO-GENERADO por scripts/generate_schema_docs.py — no editar a mano.
     Si el esquema cambia, regenerar con: python -m scripts.generate_schema_docs -->

# Esquema de Zonas (ROI)


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
{
    "zone_id": "zone_1",
    "video_id": "USA CCTV Market Camera_clean",
    "name": "Estante 1 derecha",
    "polygon": [
        [
            824.66,
            465.45
        ],
        [
            994.15,
            247.91
        ],
        [
            978.97,
            447.75
        ],
        [
            819.6,
            695.65
        ]
    ],
    "zone_type": "product"
}
```

## Modelos del contrato

### `Zone`

Geometría de una zona de la góndola.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `zone_id` | `str` | requerido | Identificador único (nombre de archivo en data/zones/<video_id>/) |
| `video_id` | `str` | requerido | Video/cámara al que pertenece esta zona (evita mezclar zonas entre videos distintos) |
| `name` | `str` | requerido | Nombre legible de la zona (ej: Góndola A1) |
| `polygon` | `List[Tuple[float, float]]` | requerido | Puntos (x, y) que cierran la zona |
| `zone_type` | `Literal['product', 'staff']` | `'product'` | 'product' = zona de góndola (dwell time); 'staff' = zona de personal (excluye de métricas de cliente) |

### `ZoneSignal`

Señales de interacción entre una persona trackeada y una zona en un frame.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `track_id` | `int` | requerido | ID de la persona trackeada |
| `zone_id` | `str` | requerido | Zona evaluada en este frame |
| `frame_index` | `int` | requerido | Índice del frame procesado |
| `wrist_inside` | `bool` | requerido | ¿La muñeca está dentro del polígono de la zona? |
| `arm_extended` | `bool` | requerido | ¿El brazo está extendido (ratio distancia hombro-muñeca/codo-hombro)? |

> `ZoneSignal` es la señal interna que consume la máquina de estados (`state_machine.py`) por cada persona y zona en cada frame; se documenta aquí porque también alimenta cálculos de dwell time futuros del dashboard.


---

*Este documento se genera automáticamente desde el código (`scripts/generate_schema_docs.py`). Regeneración: `python -m scripts.generate_schema_docs`.*
