"""
Preferencias del usuario, persistidas entre sesiones.

Usa `QSettings`, que en Windows escribe en el registro y en Linux/macOS en
un archivo de configuración del sistema. No inventamos un JSON propio en
`data/`: las preferencias son del usuario y de su equipo, no del proyecto,
y no deberían viajar en el repositorio ni borrarse al limpiar `data/`.

Todo lo que se guarda aquí es una preferencia de presentación (tema,
tamaño de letra) o de estado de la interfaz (si ya se vio el tour). Ningún
dato de análisis pasa por aquí.
"""
from PySide6.QtCore import QSettings

from app.ui.theme import DEFAULT_FONT_SCALE, DEFAULT_THEME, FONT_SCALES, THEMES

ORGANIZATION = "Scapder"
APPLICATION = "ScapderVision"

_KEY_THEME = "ui/theme"
_KEY_FONT_SCALE = "ui/font_scale"
_KEY_TOUR_SEEN = "ui/tour_seen"


def _settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


class AppSettings:
    """Lectura y escritura de las preferencias, con valores por defecto seguros."""

    @staticmethod
    def theme() -> str:
        """Clave del tema activo. Cae al oscuro si el valor guardado ya no existe."""
        value = _settings().value(_KEY_THEME, DEFAULT_THEME)
        return value if value in THEMES else DEFAULT_THEME

    @staticmethod
    def set_theme(theme: str) -> None:
        if theme in THEMES:
            _settings().setValue(_KEY_THEME, theme)

    @staticmethod
    def font_scale_key() -> str:
        value = _settings().value(_KEY_FONT_SCALE, DEFAULT_FONT_SCALE)
        return value if value in FONT_SCALES else DEFAULT_FONT_SCALE

    @staticmethod
    def font_scale() -> float:
        """Multiplicador de tamaño de fuente (0.9 a 1.5)."""
        return FONT_SCALES[AppSettings.font_scale_key()][0]

    @staticmethod
    def set_font_scale_key(key: str) -> None:
        if key in FONT_SCALES:
            _settings().setValue(_KEY_FONT_SCALE, key)

    @staticmethod
    def tour_seen() -> bool:
        """
        True si el usuario ya vio (o saltó) el tour de bienvenida.

        `QSettings` devuelve cadenas en algunas plataformas, de ahí la
        comparación explícita en vez de un `bool()` directo — `bool("false")`
        es True y el tour no volvería a mostrarse nunca.
        """
        value = _settings().value(_KEY_TOUR_SEEN, False)
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    @staticmethod
    def set_tour_seen(seen: bool = True) -> None:
        _settings().setValue(_KEY_TOUR_SEEN, bool(seen))

    @staticmethod
    def reset() -> None:
        """Borra todas las preferencias (útil para probar el primer arranque)."""
        _settings().clear()
