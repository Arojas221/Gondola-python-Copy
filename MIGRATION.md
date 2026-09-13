# Migración de Estructura de Carpetas — Scapder Vision

Fecha: 2026-08-30

## Resumen

Reorganización de `app/core/` en subpaquetes que reflejan la propiedad por equipo:

- **Team 1 (Ingestion)** → `app/core/ingestion/`
- **Team 2 (Detection)** → `app/core/detection/`
- **Team 3 (Backend)** → `app/core/backend/` (nuevo, stubs)
- **Team 4 (UI/Dashboard)** → `app/ui/` (pestañas en `main_window.py`)

Los movimientos se realizaron con `git mv` para preservar historial.

## Movimientos de Archivos

| Archivo anterior | Archivo nuevo | Equipo | Motivo |
|------------------|---------------|--------|--------|
| `app/core/video_loader.py` | `app/core/ingestion/video_loader.py` | Team 1 | Carga/validación de video |
| `app/core/video_cleaner.py` | `app/core/ingestion/video_cleaner.py` | Team 1 | Limpieza y reencode |
| `app/core/workers.py` | `app/core/ingestion/workers.py` | Team 1 | QThread workers para UI |
| `app/core/detector.py` | `app/core/detection/detector.py` | Team 2 | Detección YOLO pura |
| `app/core/tracker.py` | `app/core/detection/tracker.py` | Team 2 | ByteTrack tracking |
| `app/core/pose.py` | `app/core/detection/pose.py` | Team 2 | Estimación de pose YOLO-Pose |
| `app/core/zone.py` | `app/core/detection/zone.py` | Team 2 | Zonas + geometría |
| `app/core/state_machine.py` | `app/core/detection/state_machine.py` | Team 2 | Máquina de estados IDLE→REACHING→HOLDING |
| `app/core/frame_mapping.py` | `app/core/detection/frame_mapping.py` | Team 2 | Traducción timestamps limpio→original |
| `app/core/schemas.py` | `app/core/detection/schemas.py` | Team 2 | Contratos Pydantic (fuente de verdad) |
| `app/core/event_publisher.py` | `app/core/detection/event_publisher.py` | Team 2 | Bus de eventos (productor) |
| `app/core/pipeline.py` | `app/core/detection/pipeline.py` | Team 2 | Orquestador del pipeline |

## Cambios en Imports

Todos los imports internos se actualizaron al nuevo layout:

- `from app.core.module import X` → `from app.core.ingestion.module import X`
  o `from app.core.detection.module import X`

Archivos externos actualizados:
- `app/ui/main_window.py` → imports de `app.core.ingestion` (+ pestaña nueva
  `app/ui/zone_editor_tab.py`)
- `scripts/run_pipeline_debug.py` → imports de `app.core.detection` y usa
  `VideoFileFrameSource` de `app.core.ingestion.frame_source`
- `tests/` → imports de `app.core.detection`

## Nuevos Archivos (Post-Reorg)

| Archivo | Equipo | Propósito |
|---------|--------|-----------|
| `app/core/ingestion/__init__.py` | Team 1 | Paquete ingestion |
| `app/core/ingestion/frame_source.py` | Team 1 | `FrameSource` + `VideoFileFrameSource` + `LiveFrameSource` (stub) |
| `app/core/detection/__init__.py` | Team 2 | Paquete detection |
| `app/core/detection/trajectory.py` | Team 2 | Captura continua de posición (`PositionSample`) |
| `app/core/detection/pipeline_worker.py` | Team 2 | QThread del pipeline (patrón de workers.py) |
| `app/core/backend/__init__.py` | Team 3 | Paquete backend |
| `app/core/backend/event_store.py` | Team 3 | SQLite local + suscripción al bus (stub con TODOs) |
| `app/core/backend/heatmap.py` | Team 3 | Cuadrícula de densidad + blur gaussiano (stub con TODOs) |
| `app/ui/zone_editor_tab.py` | Team 4 | Pestaña de dibujo de zonas (ROI) |
| `tests/test_trajectory.py` | Team 2 | PositionSample / muestreo de trayectoria |
| `tests/test_frame_source.py` | Team 1 | Fuentes de frames (video + stub en vivo) |
| `tests/test_backend.py` | Team 3 | SQLite + bus in-process + densidad |
| `docs/event_schema.md` | — | Contrato del bus (auto-generado) |
| `docs/zone_schema.md` | — | Contrato de zonas (auto-generado) |
| `scripts/generate_schema_docs.py` | — | Genera docs/event_schema.md y docs/zone_schema.md |

## Decisiones de Diseño (Tasks 2–7)

1. **Trayectoria continua (Task 2)**: nuevo esquema `PositionSample` en
   `schemas.py`; se publica por el mismo `EventPublisher`. El timestamp lo
   provee la `FrameSource` (no se duplica `frame_mapping.py`).
2. **Entrada generalizada (Task 3)**: `pipeline.run(source: FrameSource)`;
   `run_video(path)` mantiene el comportamiento original. `LiveFrameSource`
   queda como stub de Team 1.
3. **Transporte (Task 5)**: se reemplazó el placeholder de WebSocket por
   `InProcessPublisher` (señal Qt `Signal(dict)`). **No** se implementó
   WebSocket: transporte de red queda fuera de alcance del MVP (documentado
   en `docs/event_schema.md`).
4. **Backend (Task 6)**: stubs con TODOs para Team 3 (SQLite + heatmap).
5. **Docs (Task 7)**: auto-generadas desde los modelos Pydantic.

## Verificación

```bash
pytest tests/ -v
# 15 passed in ~1s (state machine, trayectoria, frame sources, backend)
```

Nota: tras mover los archivos, la verificación anterior de este documento
registraba 5 tests pasando **sin que se hubieran actualizado los imports**;
la suite fallaba (ModuleNotFoundError). Los imports quedaron corregidos y la
suite completa (15 tests) pasa de punta a punta.