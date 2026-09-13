"""
Sistema visual de la aplicación: paletas, tipografía y hoja de estilos Qt.

Tres decisiones que conviene entender antes de tocar este archivo:

1. **Hay tres temas**, no uno. El oscuro es el de siempre (con los
   contrastes corregidos); el claro existe porque una demo se proyecta en
   una sala iluminada, donde un tema oscuro se lava; y el de alto
   contraste lleva todos los pares de texto por encima de 7:1 (AAA) para
   baja visión. Se eligen desde el diálogo de accesibilidad y se aplican
   en vivo, sin reiniciar.

2. **Los colores no se eligen a ojo.** Cada par crítico
   (texto sobre fondo, borde sobre panel, serie sobre panel) está listado
   en `critical_pairs()` con su mínimo WCAG, `scripts/check_theme_contrast.py`
   imprime la tabla y `tests/test_theme.py` falla si alguno se rompe. Si
   cambias un color y el test se pone rojo, el color está mal, no el test.

3. **El amarillo de marca ya no es un color de dato.** Antes el mismo
   `ACCENT` era: botón primario, pestaña activa, etiqueta mono, serie
   "tomado" del dashboard y color de dibujo del ROI — cinco significados
   con un color. Las series viven ahora en `SERIES_TAKEN`/`SERIES_RETURNED`,
   un par validado para daltonismo (ΔE 23+ en protanopia y deuteranopia)
   dentro de la banda de luminosidad del modo oscuro.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

# ---------------------------------------------------------------- utilidades --
def _srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Luminancia relativa WCAG de un color #RRGGBB."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast_ratio(fg: str, bg: str) -> float:
    """Razón de contraste WCAG entre dos colores (1:1 a 21:1)."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _to_oklab(hex_color: str) -> Tuple[float, float, float]:
    """Convierte #RRGGBB a OKLab, el espacio perceptualmente uniforme."""
    value = hex_color.lstrip("#")
    r, g, b = (_srgb_to_linear(int(value[i:i + 2], 16) / 255) for i in (0, 2, 4))

    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)

    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def perceptual_distance(color_a: str, color_b: str) -> float:
    """
    Distancia perceptual entre dos colores (ΔE en OKLab, ×100).

    Es la métrica correcta para comprobar que dos **series de datos** se
    distinguen entre sí. La razón de contraste WCAG mide luminancia y aquí
    no sirve: en una paleta categórica bien hecha las series tienen
    luminancia parecida a propósito (para que ninguna pese más que la
    otra) y se separan por tono. Medirlas con WCAG las declararía
    indistinguibles justo cuando están bien elegidas.

    Referencia: 8 es el piso mínimo, 15+ es cómodo para visión normal.
    """
    la, aa, ba = _to_oklab(color_a)
    lb, ab, bb = _to_oklab(color_b)
    return 100 * ((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2) ** 0.5


# -------------------------------------------------------------------- paletas --
@dataclass(frozen=True)
class Palette:
    """Todos los colores de un tema. Ningún widget debe declarar hex sueltos."""
    name: str
    is_dark: bool

    BG_APP: str          # fondo de la ventana
    BG_PANEL: str        # tarjetas y paneles
    BG_INPUT: str        # campos de texto y lienzos
    BG_HOVER: str        # hover de filas y botones secundarios

    BORDER: str          # límite de componentes — mínimo 3:1 sobre el panel
    BORDER_SOFT: str     # separadores internos, decorativos

    ACCENT: str          # amarillo de marca: relleno de botón primario y pestaña activa
    ACCENT_HOVER: str
    ACCENT_PRESSED: str
    ACCENT_TEXT_ON: str  # texto que va SOBRE el acento
    ACCENT_INK: str      # acento usado COMO texto sobre el fondo del tema

    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_MUTED: str      # el más bajo que sigue cumpliendo AA — no bajar más

    SUCCESS: str
    WARNING: str
    DANGER: str
    INFO_BLUE: str

    FOCUS: str           # anillo de foco de teclado
    OVERLAY: str         # velo del tour, en rgba()

    SERIES_TAKEN: str    # dashboard: producto tomado
    SERIES_RETURNED: str # dashboard: producto devuelto


# Oscuro — el tema original, con BORDER, TEXT_MUTED y DANGER subidos hasta
# cumplir AA (antes estaban en 1.29:1, 2.61:1 y 4.40:1).
DARK = Palette(
    name="Oscuro", is_dark=True,
    BG_APP="#141310", BG_PANEL="#1C1B17", BG_INPUT="#0F0E0A", BG_HOVER="#2B291F",
    BORDER="#726D5A", BORDER_SOFT="#3E3A2C",
    ACCENT="#D8C61A", ACCENT_HOVER="#E8D62A", ACCENT_PRESSED="#B8A815",
    ACCENT_TEXT_ON="#141310", ACCENT_INK="#D8C61A",
    TEXT_PRIMARY="#F2F0E6", TEXT_SECONDARY="#B5B2A6", TEXT_MUTED="#918D80",
    SUCCESS="#3DDC84", WARNING="#E5A63D", DANGER="#F2696D", INFO_BLUE="#5AA9E6",
    FOCUS="#8FD3FF", OVERLAY="rgba(10, 9, 7, 200)",
    SERIES_TAKEN="#D2A93B", SERIES_RETURNED="#57A0DC",
)

# Claro — para sala iluminada y proyector. El amarillo de marca se conserva
# como relleno (con texto oscuro encima), pero como TEXTO sobre blanco es
# ilegible, así que ACCENT_INK baja a un oro oscuro.
LIGHT = Palette(
    name="Claro", is_dark=False,
    BG_APP="#F4F2EA", BG_PANEL="#FFFFFF", BG_INPUT="#FFFFFF", BG_HOVER="#E8E5D9",
    BORDER="#8C8878", BORDER_SOFT="#D5D1C2",
    ACCENT="#D8C61A", ACCENT_HOVER="#C4B317", ACCENT_PRESSED="#A99B14",
    ACCENT_TEXT_ON="#141310", ACCENT_INK="#6B5A00",
    TEXT_PRIMARY="#1A1915", TEXT_SECONDARY="#4A4840", TEXT_MUTED="#5E5C52",
    SUCCESS="#12703F", WARNING="#8A5200", DANGER="#B3261E", INFO_BLUE="#1B5E96",
    FOCUS="#0B57D0", OVERLAY="rgba(20, 19, 16, 175)",
    SERIES_TAKEN="#8A6B12", SERIES_RETURNED="#1B6BB0",
)

# Alto contraste — negro puro, texto blanco puro, todo por encima de 7:1.
# Los bordes son casi blancos: en baja visión, la estructura de la interfaz
# importa tanto como el texto.
HIGH_CONTRAST = Palette(
    name="Alto contraste", is_dark=True,
    BG_APP="#000000", BG_PANEL="#000000", BG_INPUT="#000000", BG_HOVER="#2A2A2A",
    BORDER="#E8E8E8", BORDER_SOFT="#9A9A9A",
    ACCENT="#FFE000", ACCENT_HOVER="#FFF04D", ACCENT_PRESSED="#E5C900",
    ACCENT_TEXT_ON="#000000", ACCENT_INK="#FFE000",
    TEXT_PRIMARY="#FFFFFF", TEXT_SECONDARY="#EDEDED", TEXT_MUTED="#D2D2D2",
    SUCCESS="#5BFF9E", WARNING="#FFC14D", DANGER="#FF8A8E", INFO_BLUE="#7FC4FF",
    FOCUS="#FFFFFF", OVERLAY="rgba(0, 0, 0, 220)",
    SERIES_TAKEN="#FFD24D", SERIES_RETURNED="#79C0FF",
)

THEMES: Dict[str, Palette] = {"dark": DARK, "light": LIGHT, "high_contrast": HIGH_CONTRAST}
DEFAULT_THEME = "dark"


def critical_pairs(palette: Palette) -> List[Tuple[str, str, str, float]]:
    """
    Pares (etiqueta, primer plano, fondo, mínimo WCAG) que deben cumplirse.

    El mínimo sube a 7:1 en el tema de alto contraste para el texto: es su
    razón de existir. Los componentes (bordes, anillo de foco) se quedan en
    3:1, que es lo que pide WCAG 1.4.11 para elementos no textuales.
    """
    text_min = 7.0 if palette is HIGH_CONTRAST else 4.5
    return [
        ("Texto principal sobre fondo", palette.TEXT_PRIMARY, palette.BG_APP, text_min),
        ("Texto principal sobre panel", palette.TEXT_PRIMARY, palette.BG_PANEL, text_min),
        ("Texto secundario sobre panel", palette.TEXT_SECONDARY, palette.BG_PANEL, text_min),
        ("Texto atenuado sobre panel", palette.TEXT_MUTED, palette.BG_PANEL, text_min),
        ("Texto atenuado sobre fondo", palette.TEXT_MUTED, palette.BG_APP, text_min),
        ("Acento como texto sobre fondo", palette.ACCENT_INK, palette.BG_APP, text_min),
        ("Acento como texto sobre panel", palette.ACCENT_INK, palette.BG_PANEL, text_min),
        ("Texto sobre botón primario", palette.ACCENT_TEXT_ON, palette.ACCENT, text_min),
        ("Error sobre panel", palette.DANGER, palette.BG_PANEL, text_min),
        ("Éxito sobre panel", palette.SUCCESS, palette.BG_PANEL, text_min),
        ("Aviso sobre panel", palette.WARNING, palette.BG_PANEL, text_min),
        ("Texto sobre hover", palette.TEXT_PRIMARY, palette.BG_HOVER, text_min),
        ("Texto sobre campo de entrada", palette.TEXT_PRIMARY, palette.BG_INPUT, text_min),
        # No textuales: WCAG 1.4.11 pide 3:1
        ("Borde de panel", palette.BORDER, palette.BG_PANEL, 3.0),
        ("Borde sobre fondo", palette.BORDER, palette.BG_APP, 3.0),
        ("Anillo de foco sobre panel", palette.FOCUS, palette.BG_PANEL, 3.0),
        ("Anillo de foco sobre fondo", palette.FOCUS, palette.BG_APP, 3.0),
        ("Serie 'tomado' sobre panel", palette.SERIES_TAKEN, palette.BG_PANEL, 3.0),
        ("Serie 'devuelto' sobre panel", palette.SERIES_RETURNED, palette.BG_PANEL, 3.0),
        ("Zona de producto sobre panel", palette.INFO_BLUE, palette.BG_PANEL, 3.0),
    ]


# ----------------------------------------------------------------- tipografía --
class Fonts:
    """
    Familias con lista de reserva.

    "Segoe UI" y "Consolas" solo existen en Windows: sin reserva, en Linux
    y macOS Qt caía a una fuente arbitraria y el diseño cambiaba de un
    equipo a otro del propio grupo.
    """
    FAMILY_UI = '"Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Helvetica Neue", Arial, sans-serif'
    FAMILY_MONO = '"Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Menlo", monospace'

    # Tamaños base en puntos. La escala del usuario los multiplica.
    SIZE_SMALL = 9
    SIZE_NORMAL = 10
    SIZE_LARGE = 13
    SIZE_TITLE = 15


# Escalas ofrecidas en el diálogo de accesibilidad. El tope es 150%: por
# encima, los diálogos de Qt dejan de caber en pantallas de portátil.
FONT_SCALES = {
    "small": (0.9, "Pequeño (90%)"),
    "normal": (1.0, "Normal (100%)"),
    "large": (1.2, "Grande (120%)"),
    "xlarge": (1.5, "Muy grande (150%)"),
}
DEFAULT_FONT_SCALE = "normal"


def scaled(size_pt: int, scale: float) -> float:
    """Tamaño de fuente en puntos, redondeado a medio punto."""
    return round(size_pt * scale * 2) / 2


# --------------------------------------------------------------- hoja de estilo --
def build_stylesheet(theme: str = DEFAULT_THEME, font_scale: float = 1.0) -> str:
    """
    Hoja de estilos Qt completa para un tema y una escala de fuente.

    Se aplica con `QApplication.setStyleSheet()`; cambiarla en caliente
    repinta toda la interfaz, así que el tema y el tamaño de letra se
    cambian sin reiniciar la aplicación.
    """
    c = THEMES.get(theme, DARK)
    f = Fonts

    s_small = scaled(f.SIZE_SMALL, font_scale)
    s_normal = scaled(f.SIZE_NORMAL, font_scale)
    s_large = scaled(f.SIZE_LARGE, font_scale)

    # El padding de los controles crece con la fuente: si no, con la letra
    # al 150% el texto toca el borde del botón y el objetivo de click se
    # queda igual de pequeño que al 90%.
    pad_v = max(6, round(6 * font_scale))
    pad_h = max(12, round(14 * font_scale))
    min_control_h = max(28, round(30 * font_scale))

    return f"""
    /* ================= Base ================= */
    QWidget {{
        background-color: {c.BG_APP};
        color: {c.TEXT_PRIMARY};
        font-family: {f.FAMILY_UI};
        font-size: {s_normal}pt;
    }}

    QMainWindow {{ background-color: {c.BG_APP}; }}

    QToolTip {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        padding: 4px 8px;
    }}

    /* ================= Paneles / tarjetas =================
       Uso: contenedor.setObjectName("panel")                  */
    QFrame#panel, QWidget#panel {{
        background-color: {c.BG_PANEL};
        border: 1px solid {c.BORDER};
        border-radius: 6px;
    }}

    /* Qt propaga el borde del panel a sus hijos: sin esta regla, cada
       QLabel dentro de una tarjeta aparecía dentro de su propio recuadro
       (el defecto visible en todas las pantallas antes de este cambio). */
    QFrame#panel QLabel, QWidget#panel QLabel,
    QFrame#panel QCheckBox, QWidget#panel QCheckBox {{
        border: none;
        background: transparent;
    }}

    /* ================= Botones ================= */
    QPushButton {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: {pad_v}px {pad_h}px;
        min-height: {min_control_h}px;
    }}
    QPushButton:hover {{
        background-color: {c.BG_HOVER};
        border-color: {c.TEXT_SECONDARY};
    }}
    QPushButton:disabled {{
        color: {c.TEXT_MUTED};
        border-color: {c.BORDER_SOFT};
    }}

    QPushButton#primary {{
        background-color: {c.ACCENT};
        color: {c.ACCENT_TEXT_ON};
        border: 1px solid {c.ACCENT};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background-color: {c.ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background-color: {c.ACCENT_PRESSED}; }}
    QPushButton#primary:disabled {{
        background-color: {c.BG_HOVER};
        border-color: {c.BORDER_SOFT};
        color: {c.TEXT_MUTED};
    }}

    /* Botón de peligro: además del color lleva su propio texto ("Eliminar"),
       nunca depende solo del rojo para comunicar qué hace. */
    QPushButton#danger {{
        color: {c.DANGER};
        border-color: {c.DANGER};
    }}
    QPushButton#danger:hover {{ background-color: {c.BG_HOVER}; }}

    /* Botón de ícono de la barra superior */
    QPushButton#iconButton {{
        background-color: transparent;
        border: 1px solid transparent;
        padding: 4px;
        min-height: 30px;
    }}
    QPushButton#iconButton:hover {{
        background-color: {c.BG_HOVER};
        border-color: {c.BORDER};
    }}

    /* ================= Toggle de dos opciones ================= */
    QPushButton#toggleActive {{
        background-color: {c.ACCENT};
        color: {c.ACCENT_TEXT_ON};
        border: 1px solid {c.ACCENT};
        font-weight: 600;
    }}
    QPushButton#toggleInactive {{
        background-color: {c.BG_HOVER};
        color: {c.TEXT_SECONDARY};
        border: 1px solid {c.BORDER};
    }}

    /* ================= FOCO DE TECLADO =================
       Antes no había ninguna regla de foco y la hoja de estilos anulaba el
       indicador nativo de Qt: navegar con Tab era imposible de seguir.
       WCAG 2.4.7 lo exige y es el fallo de accesibilidad más grave que
       tenía la aplicación.                                              */
    QPushButton:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus,
    QListWidget:focus, QTableWidget:focus, QSlider:focus, QCheckBox:focus,
    QTabBar::tab:focus, QDialogButtonBox QPushButton:focus {{
        border: 2px solid {c.FOCUS};
        outline: none;
    }}

    /* ================= Campos de texto y listas ================= */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {c.BG_INPUT};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: {pad_v}px 8px;
        color: {c.TEXT_PRIMARY};
        selection-background-color: {c.ACCENT};
        selection-color: {c.ACCENT_TEXT_ON};
    }}

    QComboBox {{
        background-color: {c.BG_INPUT};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: {pad_v}px 8px;
        min-height: {min_control_h}px;
        color: {c.TEXT_PRIMARY};
    }}
    QComboBox QAbstractItemView {{
        background-color: {c.BG_PANEL};
        border: 1px solid {c.BORDER};
        selection-background-color: {c.BG_HOVER};
        selection-color: {c.TEXT_PRIMARY};
        color: {c.TEXT_PRIMARY};
    }}

    QListWidget, QTableWidget {{
        background-color: {c.BG_PANEL};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
    }}
    QListWidget::item {{ padding: 6px; border-radius: 3px; }}
    QListWidget::item:hover {{ background-color: {c.BG_HOVER}; }}
    /* La selección no se marca solo con color: además del fondo cambia el
       borde izquierdo, para que sea perceptible sin distinguir tonos. */
    QListWidget::item:selected {{
        background-color: {c.BG_HOVER};
        color: {c.TEXT_PRIMARY};
        border-left: 3px solid {c.ACCENT};
    }}
    QHeaderView::section {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_SECONDARY};
        border: none;
        border-bottom: 1px solid {c.BORDER};
        padding: 6px;
    }}

    /* ================= Casillas y opciones =================
       Qt dibuja estos indicadores con la QPalette del estilo nativo, no
       con la hoja de estilos: sin una regla explícita quedaban oscuros
       sobre fondo oscuro y no se veía cuál estaba marcada. */
    QCheckBox, QRadioButton {{
        spacing: 10px;
        background: transparent;
        padding: 3px 0;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {c.TEXT_SECONDARY};
        background-color: {c.BG_INPUT};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 10px; }}

    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {c.ACCENT};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {c.ACCENT};
        border-color: {c.ACCENT};
    }}
    /* El foco de teclado se marca en el indicador, que es lo que el
       usuario está a punto de activar. */
    QCheckBox:focus, QRadioButton:focus {{
        border: none;
    }}
    QCheckBox:focus::indicator, QRadioButton:focus::indicator {{
        border-color: {c.FOCUS};
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        border-color: {c.TEXT_MUTED};
    }}

    /* ================= Etiquetas con rol ================= */
    QLabel#monoTag {{
        font-family: {f.FAMILY_MONO};
        color: {c.ACCENT_INK};
        font-size: {s_small}pt;
        letter-spacing: 1px;
    }}
    QLabel#sectionTitle {{
        color: {c.TEXT_PRIMARY};
        font-size: {s_large}pt;
        font-weight: 600;
    }}
    QLabel#mutedText {{
        color: {c.TEXT_SECONDARY};
        font-size: {s_small}pt;
    }}
    QLabel#fieldLabel {{
        font-family: {f.FAMILY_MONO};
        color: {c.TEXT_SECONDARY};
        font-size: {s_small}pt;
        letter-spacing: 1px;
    }}
    /* Cifras de KPI: tabular-nums evita que el número "baile" de ancho en
       cada refresco del dashboard. */
    QLabel#kpiValue {{
        color: {c.TEXT_PRIMARY};
        font-family: {f.FAMILY_MONO};
        font-size: {scaled(20, font_scale)}pt;
        font-weight: 700;
    }}

    /* ================= Barra de progreso ================= */
    QProgressBar {{
        background-color: {c.BG_INPUT};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        text-align: center;
        color: {c.TEXT_PRIMARY};
        min-height: {max(18, round(18 * font_scale))}px;
    }}
    QProgressBar::chunk {{ background-color: {c.ACCENT}; border-radius: 3px; }}

    QSplitter::handle {{ background-color: {c.BORDER}; }}

    /* ================= Scrollbars ================= */
    QScrollBar:vertical {{ background: {c.BG_APP}; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {c.BORDER};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c.TEXT_MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{ background: {c.BG_APP}; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {c.BORDER};
        border-radius: 6px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

    /* ================= Pestañas ================= */
    QTabWidget::pane {{
        border: 1px solid {c.BORDER};
        background-color: {c.BG_APP};
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_SECONDARY};
        padding: {pad_v + 2}px {pad_h}px;
        border: 1px solid {c.BORDER};
        border-bottom: none;
        margin-right: 2px;
    }}
    QTabBar::tab:hover {{ background-color: {c.BG_HOVER}; color: {c.TEXT_PRIMARY}; }}
    /* La pestaña activa no se distingue solo por color: lleva además una
       barra superior de 3px y el texto en negrita. */
    QTabBar::tab:selected {{
        background-color: {c.BG_APP};
        color: {c.ACCENT_INK};
        border-top: 3px solid {c.ACCENT};
        font-weight: 600;
    }}

    /* ================= Diálogos ================= */
    QDialog {{ background-color: {c.BG_APP}; }}
    /* Sin esto, el botón secundario de un QDialogButtonBox se quedaba con
       el gris del estilo nativo y desaparecía sobre el fondo del tema. */
    QDialogButtonBox QPushButton {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        min-width: 96px;
    }}
    QDialogButtonBox QPushButton:hover {{
        background-color: {c.BG_HOVER};
        border-color: {c.TEXT_SECONDARY};
    }}
    QDialogButtonBox QPushButton#primary {{
        background-color: {c.ACCENT};
        color: {c.ACCENT_TEXT_ON};
        border-color: {c.ACCENT};
    }}
    QDialogButtonBox QPushButton#primary:hover {{ background-color: {c.ACCENT_HOVER}; }}
    QGroupBox {{
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {c.TEXT_SECONDARY};
    }}

    /* ================= Aviso de datos de demostración ================= */
    QLabel#demoBanner {{
        background-color: {c.WARNING};
        color: {'#141310' if c.is_dark else '#FFFFFF'};
        padding: 8px 14px;
        font-weight: 700;
        border-radius: 4px;
    }}
    """


# Compatibilidad hacia atrás: el resto de la interfaz importa `Colors` y lee
# atributos sueltos (Colors.ACCENT, Colors.TEXT_MUTED...). En vez de tocar
# cada uso, `Colors` es un puntero al tema activo que `apply_theme()` mueve.
class _ActivePalette:
    """Proxy al tema activo: `Colors.ACCENT` devuelve el del tema en uso."""

    def __init__(self, palette: Palette):
        object.__setattr__(self, "_palette", palette)

    def __getattr__(self, item):
        return getattr(object.__getattribute__(self, "_palette"), item)

    def _set(self, palette: Palette) -> None:
        object.__setattr__(self, "_palette", palette)


Colors = _ActivePalette(DARK)


def build_qpalette(palette: Palette):
    """
    Construye la `QPalette` equivalente a un tema.

    Hace falta además de la hoja de estilos porque **Qt no dibuja todo con
    CSS**: los indicadores de opción, las flechas de los desplegables, el
    texto deshabilitado, la selección y los tooltips los pinta el estilo
    nativo leyendo la QPalette. Con la hoja de estilos oscura y la paleta
    nativa clara, esos elementos quedaban oscuros sobre oscuro — el motivo
    de que las opciones del diálogo de accesibilidad "se perdieran".
    """
    from PySide6.QtGui import QColor, QPalette

    qp = QPalette()
    window = QColor(palette.BG_APP)
    base = QColor(palette.BG_INPUT)
    text = QColor(palette.TEXT_PRIMARY)
    disabled = QColor(palette.TEXT_MUTED)

    qp.setColor(QPalette.Window, window)
    qp.setColor(QPalette.WindowText, text)
    qp.setColor(QPalette.Base, base)
    qp.setColor(QPalette.AlternateBase, QColor(palette.BG_PANEL))
    qp.setColor(QPalette.Text, text)
    qp.setColor(QPalette.Button, QColor(palette.BG_PANEL))
    qp.setColor(QPalette.ButtonText, text)
    qp.setColor(QPalette.BrightText, QColor(palette.DANGER))
    qp.setColor(QPalette.Highlight, QColor(palette.ACCENT))
    qp.setColor(QPalette.HighlightedText, QColor(palette.ACCENT_TEXT_ON))
    qp.setColor(QPalette.ToolTipBase, QColor(palette.BG_PANEL))
    qp.setColor(QPalette.ToolTipText, text)
    qp.setColor(QPalette.PlaceholderText, QColor(palette.TEXT_MUTED))
    qp.setColor(QPalette.Link, QColor(palette.INFO_BLUE))
    qp.setColor(QPalette.Mid, QColor(palette.BORDER))
    qp.setColor(QPalette.Dark, QColor(palette.BORDER_SOFT))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        qp.setColor(QPalette.Disabled, role, disabled)

    return qp


def apply_theme(app, theme: str = DEFAULT_THEME, font_scale: float = 1.0) -> Palette:
    """
    Aplica un tema a la QApplication y actualiza `Colors`.

    Cambia las tres cosas que definen el aspecto: la paleta nativa (para lo
    que Qt dibuja sin CSS), la hoja de estilos y la fuente base de la
    aplicación. Devuelve la paleta activa.

    La fuente de la aplicación se fija aquí y no solo por CSS porque los
    cálculos de tamaño de los layouts usan `QApplication.font()`: si solo
    cambia el CSS, los widgets se dibujan con la letra nueva pero los
    layouts siguen midiendo con la vieja, y la ventana queda con el tamaño
    anterior sin reacomodarse.
    """
    from PySide6.QtGui import QFont

    palette = THEMES.get(theme, DARK)
    Colors._set(palette)

    app.setPalette(build_qpalette(palette))

    base_font = QFont(app.font())
    base_font.setPointSizeF(scaled(Fonts.SIZE_NORMAL, font_scale))
    app.setFont(base_font)

    app.setStyleSheet(build_stylesheet(theme, font_scale))
    return palette
