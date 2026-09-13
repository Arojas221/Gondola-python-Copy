from typing import Optional

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


def _create_gear_icon(size: int = 18, color: str = "#F2F0E6") -> QIcon:
    """
    Dibuja un ícono de engranaje como gráfico vectorial (QPainter), en vez
    de depender de un glifo de emoji (⚙) que no todas las fuentes/sistemas
    renderizan igual — el bug documentado de que se veía como "|" en
    Windows era justamente por depender de la fuente del sistema.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))

    center = size / 2
    outer_r = size * 0.40
    inner_r = size * 0.24
    tooth_w = size * 0.16
    tooth_h = size * 0.16

    # Cuerpo circular del engranaje
    painter.drawEllipse(QPointF(center, center), outer_r, outer_r)

    # 8 dientes distribuidos alrededor del círculo
    painter.translate(center, center)
    for i in range(8):
        painter.save()
        painter.rotate(i * 45)
        painter.drawRect(QRectF(-tooth_w / 2, -(outer_r + tooth_h * 0.55), tooth_w, tooth_h))
        painter.restore()
    painter.resetTransform()

    # Hueco central (deja transparente el centro, como un engranaje real)
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    painter.setBrush(QColor(0, 0, 0, 255))
    painter.drawEllipse(QPointF(center, center), inner_r, inner_r)

    painter.end()
    return QIcon(pixmap)


def create_heatmap_icon(size: int = 18) -> QIcon:
    """
    Ícono de "mapa de calor": cuadrícula 3x3 con un degradado frío -> cálido
    hacia el centro, para el botón que abre la vista grande del heatmap
    (mismo criterio que `_create_gear_icon`: vectorial, no emoji).
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    cells = 3
    cell = size / cells
    heat_hex = [
        ["#3B2A78", "#8C3D6B", "#3B2A78"],
        ["#8C3D6B", "#F2A93B", "#8C3D6B"],
        ["#2A2560", "#8C3D6B", "#2A2560"],
    ]
    for row in range(cells):
        for col in range(cells):
            painter.setBrush(QColor(heat_hex[row][col]))
            painter.drawRoundedRect(QRectF(col * cell + 1, row * cell + 1, cell - 2, cell - 2), 2, 2)

    painter.end()
    return QIcon(pixmap)


def create_help_icon(size: int = 18, color: str = "#F2F0E6") -> QIcon:
    """Signo de interrogación en un círculo, para el botón que repite el tour."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.11)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    inset = size * 0.10
    painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))

    font = QFont()
    font.setPointSizeF(size * 0.55)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "?")
    painter.end()
    return QIcon(pixmap)


def create_accessibility_icon(size: int = 18, color: str = "#F2F0E6") -> QIcon:
    """
    Figura humana con los brazos extendidos dentro de un círculo — el
    símbolo internacional de accesibilidad universal.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.10)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    inset = size * 0.08
    painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))

    cx = size / 2
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    head_r = size * 0.09
    painter.drawEllipse(QPointF(cx, size * 0.27), head_r, head_r)

    painter.setPen(pen)
    painter.drawLine(QPointF(size * 0.26, size * 0.45), QPointF(size * 0.74, size * 0.45))  # brazos
    painter.drawLine(QPointF(cx, size * 0.40), QPointF(cx, size * 0.62))                     # tronco
    painter.drawLine(QPointF(cx, size * 0.62), QPointF(size * 0.34, size * 0.80))            # pierna izq.
    painter.drawLine(QPointF(cx, size * 0.62), QPointF(size * 0.66, size * 0.80))            # pierna der.
    painter.end()
    return QIcon(pixmap)


class HeaderBar(QFrame):
    """Barra superior: nombre de la fuente activa + botón de settings"""

    # Señal vacía: solo avisa "se apretó settings", sin pasar datos.
    settings_clicked = Signal()

    def __init__(self, source_name: str = "", show_action: bool = True, parent=None):
        super().__init__(parent)
        # "panel" ya tiene estilo definido en theme.py (fondo + borde).
        self.setObjectName("panel")
        self.btn_settings: Optional[QPushButton] = None
        # Si una pestaña reemplazó el ícono con `set_action`, no se debe
        # sobrescribir al cambiar de tema.
        self._uses_default_icon = True
        self._build_ui(source_name, show_action)

    def _build_ui(self, source_name: str, show_action: bool):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)

        self.source_label = QLabel(source_name.upper())
        self.source_label.setObjectName("monoTag")  # estilo mono + amarillo, de theme.py
        layout.addWidget(self.source_label)

        layout.addStretch()  # empuja el botón de acción hacia la derecha (si existe)

        # `show_action=False`: tabs sin ninguna acción real conectada a este
        # botón (Carga de video, Edición de zonas) no lo muestran — un
        # engranaje que no hace nada es peor que no tener botón.
        if show_action:
            self.btn_settings = QPushButton()
            self.btn_settings.setObjectName("iconButton")
            self.btn_settings.setIcon(_create_gear_icon())
            self.btn_settings.setIconSize(QSize(18, 18))
            self.btn_settings.setMinimumWidth(36)
            self.btn_settings.setToolTip("Configuración")
            # Un botón de solo ícono es invisible para un lector de
            # pantalla sin esto: el tooltip no se expone como nombre.
            self.btn_settings.setAccessibleName("Configuración")
            self.btn_settings.clicked.connect(self.settings_clicked.emit)
            layout.addWidget(self.btn_settings)

    def refresh_icon_color(self, color: str):
        """
        Redibuja el ícono con el color del tema activo.

        Los íconos se generan con QPainter sobre un color fijo, así que al
        cambiar a un tema claro un ícono blanco desaparecía sobre el fondo.
        """
        if self.btn_settings is not None and self._uses_default_icon:
            self.btn_settings.setIcon(_create_gear_icon(color=color))

    def set_source_name(self, name: str):
        """Actualiza el texto de la fuente sin reconstruir el widget entero"""
        self.source_label.setText(name.upper())

    def set_action(self, icon: QIcon, tooltip: str):
        """
        Reemplaza el ícono/tooltip del botón de la esquina (por defecto el
        engranaje de "Configuración"). El botón sigue emitiendo la misma
        señal `settings_clicked` — cada tab decide qué significa ese click
        conectándose a ella; no todos los tabs necesitan un settings real.

        No-op si este HeaderBar se construyó con `show_action=False`.
        """
        if self.btn_settings is None:
            return
        self.btn_settings.setIcon(icon)
        self.btn_settings.setToolTip(tooltip)
        self.btn_settings.setAccessibleName(tooltip)
        self._uses_default_icon = False