"""
Detección heurística de empleados mediante zonas staff.

Portado desde la rama `corredor` (app/core/staff.py) y adaptado a los
nombres de campo de PositionSample en esta rama (`foot_position` en vez
de `x`/`y`).
"""
from typing import List, Set

from app.core.detection.schemas import PositionSample, Zone
from app.core.detection.zone import is_point_in_polygon


class StaffZoneTracker:
    """
    Marca como empleado a cualquier persona que haya entrado en una zona staff.
    El marcado es "sticky": una vez empleado en esta sesión, se queda marcado
    el resto del video.
    """

    def __init__(self) -> None:
        self.known_employee_tracks: Set[int] = set()

    def update(self, position: PositionSample, zones: List[Zone]) -> bool:
        """
        Chequea si la posición cae dentro de alguna zona staff.
        Devuelve True si el track_id está marcado como empleado.
        """
        foot_x, foot_y = position.foot_position
        for zone in zones:
            if zone.zone_type != "staff":
                continue
            if len(zone.polygon) < 3:
                continue
            if is_point_in_polygon(foot_x, foot_y, zone):
                self.known_employee_tracks.add(position.track_id)

        return self.is_employee(position.track_id)

    def is_employee(self, track_id: int) -> bool:
        """Consulta si un track_id está marcado como empleado."""
        return track_id in self.known_employee_tracks
