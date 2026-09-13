"""
Dwell time por zona: mide el tiempo de permanencia de personas dentro de zonas de producto.

Portado desde la rama `corredor` (app/core/presence.py) y adaptado a los
nombres de campo de PositionSample en esta rama (`foot_position`,
`original_timestamp_sec` en vez de `x`/`y`/`timestamp`).
"""
from typing import Dict, List, Tuple

from app.core.detection.schemas import PositionSample, Zone, DwellRecord
from app.core.detection.zone import is_point_in_polygon


class DwellTracker:
    """
    Registra entradas y salidas de personas en zonas de producto,
    emitiendo un DwellRecord por cada salida.
    """

    def __init__(self) -> None:
        # clave (track_id, zone_id) -> timestamp de entrada
        self.active_entries: Dict[Tuple[int, str], float] = {}

    def update(
        self,
        position: PositionSample,
        zones: List[Zone],
        current_timestamp: float,
    ) -> List[DwellRecord]:
        """
        Procesa la posición de una persona contra todas las zonas de producto.
        Devuelve una lista de DwellRecords para las salidas detectadas en este frame.
        """
        records: List[DwellRecord] = []
        foot_x, foot_y = position.foot_position

        for zone in zones:
            if zone.zone_type != "product":
                continue
            if len(zone.polygon) < 3:
                continue

            key = (position.track_id, zone.zone_id)
            inside = is_point_in_polygon(foot_x, foot_y, zone)

            if inside and key not in self.active_entries:
                self.active_entries[key] = current_timestamp
            elif not inside and key in self.active_entries:
                entry_ts = self.active_entries.pop(key)
                duration = current_timestamp - entry_ts
                records.append(
                    DwellRecord(
                        track_id=position.track_id,
                        zone_id=zone.zone_id,
                        entry_timestamp=entry_ts,
                        exit_timestamp=current_timestamp,
                        duration_sec=duration,
                        is_employee=position.is_employee,
                    )
                )

        return records

    # Nota de diseño (heredada de `corredor`): si un track_id desaparece del
    # video (se pierde el tracking) mientras estaba dentro de una zona, su
    # entrada queda "colgada" en active_entries indefinidamente y nunca se
    # cierra el dwell. No implementamos lógica de expiración por ahora — no
    # es crítico para la demo.
