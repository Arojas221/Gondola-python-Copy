"""
Máquina de estados para detectar eventos de interacción a partir de señales de zona.
"""
from enum import Enum
from typing import List, Dict, Tuple, Set

from app.core.detection.schemas import ZoneSignal, InteractionEvent
from app.utils.config import (
    MIN_FRAMES_REACHING_TO_HOLDING,
    MIN_FRAMES_HOLDING,
    MAX_FRAMES_MISSING_TO_RESET,
    MAX_SECONDS_STUCK_REACHING,
)

class InteractionState(Enum):
    IDLE = "idle"
    REACHING = "reaching"
    HOLDING = "holding"

class InteractionStateMachine:
    """Mantiene y actualiza el estado de interacción para cada (track_id, zone_id)."""

    def __init__(self, fps: float = 30.0):
        # Key: (track_id, zone_id) -> Value: (state, frame_count)
        self.states: Dict[Tuple[int, str], Tuple[InteractionState, int]] = {}
        # Key: track_id -> Value: frames consecuentes sin detección
        self.missing_counters: Dict[int, int] = {}
        # Key: (track_id, zone_id) -> Value: frames consecutivos atascado en REACHING
        self.stuck_counters: Dict[Tuple[int, str], int] = {}
        # Key: (track_id, zone_id) -> Value: cuántas interacciones completas (taken/returned)
        # ya se emitieron para esta pareja persona+zona en esta sesión de video.
        # Heurístico de negocio (sin detección de producto no se puede saber con certeza
        # si la mano sale con o sin el producto): la primera interacción se cuenta como
        # "taken"; toda repetición sobre la MISMA zona se cuenta como "returned",
        # alternando. Aproximado, pero es lo que Joshua (Scapder) confirmó que basta
        # para el alcance del reto (ver docs/event_schema.md).
        self.interaction_counts: Dict[Tuple[int, str], int] = {}
        # Calcular el máximo de frames permitidos en estado REACHING con brazo no extendido
        self.max_frames_stuck_reaching = round(fps * MAX_SECONDS_STUCK_REACHING)

    def process(self, zone_signals: List[ZoneSignal]) -> List[InteractionEvent]:
        """
        Procesa las señales de zona de un frame y devuelve los eventos generados.
        
        Llamado una vez por frame.
        """
        events = []
        present_tracks: Set[int] = {sig.track_id for sig in zone_signals}

        # Actualizar contadores de pérdida de tracking
        # Identificamos todos los track_ids que actualmente tienen un estado activo (distinto de IDLE)
        active_tracks = {
            tid for (tid, _) in self.states.keys()
            if self.states.get((tid, _), (InteractionState.IDLE, 0))[0] != InteractionState.IDLE
        }

        for tid in active_tracks:
            if tid in present_tracks:
                self.missing_counters[tid] = 0
            else:
                self.missing_counters[tid] = self.missing_counters.get(tid, 0) + 1
                if self.missing_counters[tid] >= MAX_FRAMES_MISSING_TO_RESET:
                    # Resetear todos los estados de esta persona a IDLE sin emitir eventos
                    for (t_id, z_id) in list(self.states.keys()):
                        if t_id == tid:
                            self.states[(t_id, z_id)] = (InteractionState.IDLE, 0)
                    self.missing_counters[tid] = 0

        # Procesar señales del frame actual
        for sig in zone_signals:
            tid = sig.track_id
            zid = sig.zone_id
            
            # Inicializar estado si no existe
            state, count = self.states.get((tid, zid), (InteractionState.IDLE, 0))
            
            if state == InteractionState.IDLE:
                if sig.wrist_inside and sig.arm_extended:
                    state = InteractionState.REACHING
                    count = 1
                else:
                    count = 0

            elif state == InteractionState.REACHING:
                if not sig.wrist_inside:
                    # Transición a IDLE: resetear contador de atasco
                    self.stuck_counters.pop((tid, zid), None)
                    state = InteractionState.IDLE
                    count = 0
                elif sig.arm_extended:
                    # Brazo extendido dentro de la zona: incrementar contador hacia HOLDING
                    # Resetear contador de atasco si existe
                    self.stuck_counters.pop((tid, zid), None)
                    count += 1
                    if count >= MIN_FRAMES_REACHING_TO_HOLDING:
                        state = InteractionState.HOLDING
                        count = 1
                else:
                    # Si sigue adentro pero el brazo no está extendido, detectar atasco
                    count = 0
                    # Incrementar contador de atasco para esta pareja (tid, zid)
                    self.stuck_counters[(tid, zid)] = self.stuck_counters.get((tid, zid), 0) + 1
                    
                    # Si alcanzó o superó el máximo permitido, transicionar a IDLE sin evento
                    if self.stuck_counters[(tid, zid)] >= self.max_frames_stuck_reaching:
                        state = InteractionState.IDLE
                        count = 0
                        self.stuck_counters.pop((tid, zid), None)

            elif state == InteractionState.HOLDING:
                if not sig.wrist_inside:
                    # Transición a IDLE: resetear contador de atasco
                    self.stuck_counters.pop((tid, zid), None)
                    if count >= MIN_FRAMES_HOLDING:
                        # Heurístico taken/returned (ver nota en __init__): la primera
                        # interacción completa persona+zona en la sesión es "taken",
                        # las siguientes alternan a "returned"/"taken".
                        n = self.interaction_counts.get((tid, zid), 0)
                        action = "taken" if n % 2 == 0 else "returned"
                        self.interaction_counts[(tid, zid)] = n + 1

                        events.append(
                            InteractionEvent(
                                track_id=tid,
                                zone_id=zid,
                                action=action,
                                timestamp=0.0,  # Se traduce luego en el pipeline
                            )
                        )
                    state = InteractionState.IDLE
                    count = 0
                else:
                    # Sigue adentro interactuando (holding)
                    count += 1

            self.states[(tid, zid)] = (state, count)

        return events
