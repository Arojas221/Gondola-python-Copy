"""
Tests unitarios para la máquina de estados de interacción.
"""
import pytest
from app.core.detection.schemas import ZoneSignal
from app.core.detection.state_machine import InteractionStateMachine, InteractionState
from app.utils.config import (
    MIN_FRAMES_REACHING_TO_HOLDING,
    MIN_FRAMES_HOLDING,
    MAX_FRAMES_MISSING_TO_RESET,
    MAX_SECONDS_STUCK_REACHING,
)

def test_complete_interaction_flow():
    """Prueba el flujo completo: IDLE -> REACHING -> HOLDING -> IDLE (emite evento)."""
    sm = InteractionStateMachine()
    track_id = 1
    zone_id = "shelf_1"
    
    # 1. Enviar señal de inicio (wrist_inside=True, arm_extended=True)
    signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=0, wrist_inside=True, arm_extended=True)]
    events = sm.process(signals)
    assert len(events) == 0
    assert sm.states[(track_id, zone_id)][0] == InteractionState.REACHING
    
    # 2. Mantener REACHING hasta transición a HOLDING
    for i in range(1, MIN_FRAMES_REACHING_TO_HOLDING):
        signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=i, wrist_inside=True, arm_extended=True)]
        events = sm.process(signals)
        assert len(events) == 0
        
    assert sm.states[(track_id, zone_id)][0] == InteractionState.HOLDING
    
    # 3. Mantener HOLDING por el mínimo de frames
    for i in range(MIN_FRAMES_REACHING_TO_HOLDING, MIN_FRAMES_REACHING_TO_HOLDING + MIN_FRAMES_HOLDING):
        signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=i, wrist_inside=True, arm_extended=False)]
        events = sm.process(signals)
        assert len(events) == 0
        
    # 4. Salir de la zona (wrist_inside=False), debe emitirse el evento
    signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=100, wrist_inside=False, arm_extended=False)]
    events = sm.process(signals)
    assert len(events) == 1
    assert events[0].track_id == track_id
    assert events[0].zone_id == zone_id
    assert events[0].action == "taken"
    assert sm.states[(track_id, zone_id)][0] == InteractionState.IDLE

def test_interruption_during_reaching():
    """Prueba que si wrist_inside se vuelve False en medio de REACHING, vuelve a IDLE."""
    sm = InteractionStateMachine()
    track_id = 1
    zone_id = "shelf_1"
    
    # Entra en REACHING
    signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=0, wrist_inside=True, arm_extended=True)]
    sm.process(signals)
    assert sm.states[(track_id, zone_id)][0] == InteractionState.REACHING
    
    # Interrupción
    signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=1, wrist_inside=False, arm_extended=False)]
    events = sm.process(signals)
    assert len(events) == 0
    assert sm.states[(track_id, zone_id)][0] == InteractionState.IDLE

def test_tracking_loss_resets_state():
    """Prueba que si se pierde el tracking durante HOLDING por más de MAX_FRAMES_MISSING_TO_RESET, se resetea a IDLE sin evento."""
    sm = InteractionStateMachine()
    track_id = 1
    zone_id = "shelf_1"
    
    # Llegar a HOLDING
    for i in range(MIN_FRAMES_REACHING_TO_HOLDING):
        signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=i, wrist_inside=True, arm_extended=True)]
        sm.process(signals)
        
    assert sm.states[(track_id, zone_id)][0] == InteractionState.HOLDING
    
    # Dejar de reportar señales para este track_id durante MAX_FRAMES_MISSING_TO_RESET
    for i in range(MAX_FRAMES_MISSING_TO_RESET):
        events = sm.process([])  # Ningún track en el frame
        assert len(events) == 0
        
    # Verificar que se reseteó a IDLE
    assert sm.states[(track_id, zone_id)][0] == InteractionState.IDLE

def test_independent_multiple_tracks():
    """Prueba que dos tracks mantengan estados e interacciones independientes."""
    sm = InteractionStateMachine()
    t1 = 1
    t2 = 2
    zone = "shelf_1"
    
    # t1 inicia reaching
    sm.process([
        ZoneSignal(track_id=t1, zone_id=zone, frame_index=0, wrist_inside=True, arm_extended=True),
        ZoneSignal(track_id=t2, zone_id=zone, frame_index=0, wrist_inside=False, arm_extended=False)
    ])
    assert sm.states[(t1, zone)][0] == InteractionState.REACHING
    assert sm.states.get((t2, zone), (InteractionState.IDLE, 0))[0] == InteractionState.IDLE

def _drive_full_interaction(sm, track_id, zone_id, start_frame):
    """Helper: corre un ciclo completo REACHING -> HOLDING -> salida y devuelve los eventos de la salida."""
    frame = start_frame
    sm.process([ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=frame, wrist_inside=True, arm_extended=True)])
    for _ in range(MIN_FRAMES_REACHING_TO_HOLDING - 1):
        frame += 1
        sm.process([ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=frame, wrist_inside=True, arm_extended=True)])
    for _ in range(MIN_FRAMES_HOLDING):
        frame += 1
        sm.process([ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=frame, wrist_inside=True, arm_extended=False)])
    frame += 1
    events = sm.process([ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=frame, wrist_inside=False, arm_extended=False)])
    return events, frame


def test_second_interaction_same_zone_is_returned():
    """La primera interacción completa con una zona es 'taken'; la segunda, 'returned' (heurístico)."""
    sm = InteractionStateMachine()
    track_id, zone_id = 1, "shelf_1"

    events1, next_frame = _drive_full_interaction(sm, track_id, zone_id, start_frame=0)
    assert len(events1) == 1
    assert events1[0].action == "taken"

    events2, next_frame = _drive_full_interaction(sm, track_id, zone_id, start_frame=next_frame + 1)
    assert len(events2) == 1
    assert events2[0].action == "returned"

    events3, _ = _drive_full_interaction(sm, track_id, zone_id, start_frame=next_frame + 1)
    assert len(events3) == 1
    assert events3[0].action == "taken"


def test_interactions_independent_per_zone():
    """El conteo taken/returned es independiente por (track_id, zone_id): otra zona empieza en 'taken'."""
    sm = InteractionStateMachine()
    track_id = 1

    events_a, next_frame = _drive_full_interaction(sm, track_id, "shelf_A", start_frame=0)
    assert events_a[0].action == "taken"

    # Primera interacción en una zona DISTINTA: también debe ser "taken", no "returned"
    events_b, _ = _drive_full_interaction(sm, track_id, "shelf_B", start_frame=next_frame + 1)
    assert events_b[0].action == "taken"
    """Prueba que si una interacción se atasca en REACHING (brazo no extendido pero muñeca dentro)
    durante más de MAX_SECONDS_STUCK_REACHING, se resetea a IDLE sin emitir evento."""
    fps = 30.0
    sm = InteractionStateMachine(fps=fps)
    track_id = 1
    zone_id = "shelf_1"
    
    # 1. Entra en REACHING (brazo extendido dentro de zona)
    signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=0, wrist_inside=True, arm_extended=True)]
    events = sm.process(signals)
    assert len(events) == 0
    assert sm.states[(track_id, zone_id)][0] == InteractionState.REACHING
    
    # 2. Enviar señales con brazo no extendido pero muñeca dentro durante más frames que el máximo permitido
    # max_frames_stuck_reaching = round(30.0 * 1.0) = 30 frames
    max_frames = sm.max_frames_stuck_reaching
    
    for i in range(1, max_frames + 2):  # Ir 2 frames más allá del máximo
        signals = [ZoneSignal(track_id=track_id, zone_id=zone_id, frame_index=i, wrist_inside=True, arm_extended=False)]
        events = sm.process(signals)
        assert len(events) == 0  # No debe haber eventos durante el atasco
    
    # 3. Después de alcanzar el máximo, debe estar en IDLE sin haber emitido evento
    assert sm.states[(track_id, zone_id)][0] == InteractionState.IDLE
    # El contador de atasco debe haberse limpiado
    assert (track_id, zone_id) not in sm.stuck_counters or sm.stuck_counters[(track_id, zone_id)] == 0

