"""
Pestaña 5: Dashboard de Métricas (Team 4).

A diferencia del resto de la UI (que opera sobre archivos/estado en
memoria), este tab lee directamente de `EventStore` (SQLite,
`data/scapder_events.db`) — el mismo almacén al que el pipeline de
detección publica en producción vía `InProcessPublisher`. No hay datos
mockeados en el widget: si la sesión ya tiene eventos reales, se grafican
esos; si está vacía (el pipeline de las pestañas 3/4 aún no corrió),
se ofrece sembrar una sesión de demostración explícitamente marcada como
tal (ver `app/core/backend/demo_seed.py`), nunca de forma automática o
silenciosa.
"""
import json
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.backend.demo_seed import FRAME_SIZE, has_data, seed_demo_session
from app.core.backend.event_store import EventStore
from app.core.backend.heatmap import build_density_grid
from app.core.detection.schemas import Zone
from app.core.detection.zone import ZoneManager
from app.ui.theme import Colors
from app.ui.widgets.header import HeaderBar, create_heatmap_icon
from app.utils import config

# Los colores de serie salen de la paleta de datos, NO del acento de marca.
# Antes el mismo amarillo era botón primario, pestaña activa, etiqueta mono
# y serie "tomado": un color con cinco significados. El par actual está
# validado para daltonismo (ΔE > 23 en protanopia y deuteranopia) y dentro
# de la banda de luminosidad de cada tema.
#
# Son funciones porque el tema se cambia en caliente: una constante de
# módulo se quedaría con el color del tema inicial.
def taken_color() -> str:
    return Colors.SERIES_TAKEN


def returned_color() -> str:
    return Colors.SERIES_RETURNED


def employee_color() -> str:
    return Colors.WARNING

REFRESH_INTERVAL_MS = 3000

# Texto del combo cuando no hay ninguna sesión: ni zonas dibujadas ni datos.
NO_SESSION_LABEL = "(sin sesiones)"


def _format_seconds(seconds: float) -> str:
    """Segundos del video como mm:ss — más legible que un decimal suelto."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ============================================================ widgets base --
class Card(QFrame):
    """Tarjeta contenedora estándar del dashboard (título + contenido)."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        head = QVBoxLayout()
        head.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        head.addWidget(title_label)
        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setObjectName("mutedText")
            head.addWidget(sub_label)
        layout.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        layout.addLayout(self.body, stretch=1)


class KpiCard(QFrame):
    """Tarjeta compacta: etiqueta + valor grande + nota."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self.label = QLabel(label)
        self.label.setObjectName("fieldLabel")
        layout.addWidget(self.label)

        self.value_label = QLabel("—")
        # objectName en vez de stylesheet en línea: así el tamaño sigue la
        # escala de fuente del usuario y la fuente monoespaciada mantiene
        # el ancho de las cifras estable entre refrescos.
        self.value_label.setObjectName("kpiValue")
        layout.addWidget(self.value_label)

        self.note_label = QLabel("")
        self.note_label.setObjectName("mutedText")
        layout.addWidget(self.note_label)

    def set_value(self, value: str, note: str = "", note_color: str | None = None):
        self.value_label.setText(value)
        self.note_label.setText(note)
        color = note_color or Colors.TEXT_SECONDARY
        self.note_label.setStyleSheet(f"color: {color};")
        # Nombre accesible completo: un lector de pantalla anuncia
        # "Interacciones totales: 42", no un "42" suelto.
        self.setAccessibleName(f"{self.label.text()}: {value}. {note}".strip())


class EmptyState(QLabel):
    """Aviso centrado para gráficos sin datos (evita canvases vacíos mudos)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setObjectName("mutedText")
        self.setMinimumHeight(80)


# ============================================================ gráficos ------
class ZoneBarChart(QWidget):
    """Barras horizontales agrupadas: `taken` vs `returned` por zona."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows: list[dict]):
        self._rows = rows
        row_h = 46
        self.setMinimumHeight(max(140, len(rows) * row_h + 20))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._rows:
            painter.end()
            return

        w = self.width()
        row_h = 46
        max_total = max((r["taken"] + r["returned"] for r in self._rows), default=1) or 1
        label_w = 170
        bar_x0 = label_w
        bar_w_max = w - bar_x0 - 200

        font_label = QFont("Segoe UI", 9)
        font_mono = QFont("Consolas", 8)

        for i, row in enumerate(self._rows):
            y = i * row_h
            name = row.get("name", row["zone_id"])
            total = row["taken"] + row["returned"]

            painter.setFont(font_label)
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            painter.drawText(QRectF(0, y + 4, label_w - 10, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            painter.setFont(font_mono)
            painter.setPen(QColor(Colors.TEXT_MUTED))
            painter.drawText(
                QRectF(0, y + 22, label_w - 10, 14), Qt.AlignLeft | Qt.AlignVCenter,
                f"{total} interacciones",
            )

            track_rect = QRectF(bar_x0, y + 8, bar_w_max, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(Colors.BG_INPUT))
            painter.drawRoundedRect(track_rect, 4, 4)

            taken_w = bar_w_max * (row["taken"] / max_total)
            returned_w = bar_w_max * (row["returned"] / max_total)

            painter.setBrush(QColor(taken_color()))
            painter.drawRoundedRect(QRectF(bar_x0, y + 8, taken_w, 18), 4, 4)
            painter.setBrush(QColor(returned_color()))
            painter.drawRoundedRect(QRectF(bar_x0 + taken_w + 2, y + 8, returned_w, 18), 4, 4)

            # Etiqueta directa sobre la barra: sin eje ni números, una barra
            # solo comunica "más que la otra", nunca una magnitud. El texto
            # va en tinta neutra, no en el color de la serie.
            painter.setFont(font_mono)
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            painter.drawText(
                QRectF(bar_x0 + bar_w_max + 10, y + 6, 190, 13), Qt.AlignLeft | Qt.AlignVCenter,
                f"{row['taken']} tomados · {row['returned']} devueltos",
            )
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.drawText(
                QRectF(bar_x0 + bar_w_max + 10, y + 21, 190, 13), Qt.AlignLeft | Qt.AlignVCenter,
                f"{row['avg_dwell_sec']:.1f} s de permanencia",
            )

        painter.end()


class TimelineChart(QWidget):
    """Línea de `taken`/`returned` por bucket de tiempo, con relleno bajo la curva."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bins: list[dict] = []
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, bins: list[dict]):
        self._bins = bins
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if len(self._bins) < 2:
            painter.end()
            return

        pad_l, pad_r, pad_t, pad_b = 38, 12, 10, 28
        w, h = self.width(), self.height()
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        n = len(self._bins)
        max_v = max((b["taken"] + b["returned"] for b in self._bins), default=1) or 1
        x_step = plot_w / (n - 1)

        def xy(i, v):
            x = pad_l + i * x_step
            y = pad_t + plot_h - (v / max_v) * plot_h
            return x, y

        # grid
        painter.setPen(QPen(QColor(Colors.BORDER_SOFT), 1))
        for f in (0, 0.5, 1.0):
            y = pad_t + plot_h * (1 - f)
            painter.drawLine(int(pad_l), int(y), int(w - pad_r), int(y))
            painter.setPen(QColor(Colors.TEXT_MUTED))
            painter.setFont(QFont("Consolas", 7))
            painter.drawText(0, int(y) + 3, pad_l - 6, 10, Qt.AlignRight, str(int(max_v * f)))
            painter.setPen(QPen(QColor(Colors.BORDER_SOFT), 1))

        def draw_series(key, color, dashed=False):
            pen = QPen(QColor(color), 2)
            if dashed:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            points = [xy(i, b[key]) for i, b in enumerate(self._bins)]
            for j in range(len(points) - 1):
                x1, y1 = points[j]
                x2, y2 = points[j + 1]
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # área bajo "taken"
        fill_points = [xy(i, b["taken"]) for i, b in enumerate(self._bins)]
        fill_color = QColor(taken_color())
        fill_color.setAlpha(40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_color)
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF
        poly = QPolygonF([QPointF(*p) for p in fill_points])
        poly.append(QPointF(*xy(n - 1, 0)))
        poly.append(QPointF(*xy(0, 0)))
        painter.drawPolygon(poly)

        draw_series("taken", taken_color())
        draw_series("returned", returned_color(), dashed=True)

        # Eje X: sin él la serie no dice a qué momento del video pertenece
        # cada punto — se veía la forma, pero no se podía ubicar nada.
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor(Colors.TEXT_SECONDARY))
        label_y = h - pad_b + 10
        for position, rect in (
            (0, QRectF(pad_l, label_y, 60, 13)),
            (n // 2, QRectF(pad_l + plot_w / 2 - 30, label_y, 60, 13)),
            (n - 1, QRectF(w - pad_r - 60, label_y, 60, 13)),
        ):
            seconds = self._bins[position].get("bucket_start_sec", 0.0)
            align = Qt.AlignLeft if position == 0 else (
                Qt.AlignRight if position == n - 1 else Qt.AlignHCenter)
            painter.drawText(rect, align | Qt.AlignVCenter, _format_seconds(seconds))

        painter.drawText(QRectF(pad_l, label_y - 13, plot_w, 12), Qt.AlignHCenter,
                         "minuto del video")

        painter.end()


class HeatmapWidget(QWidget):
    """
    Mapa de calor de circulación sobre el layout real de la góndola.

    Construido con `build_density_grid` (app/core/backend/heatmap.py) a
    partir de los `PositionSample.foot_position` almacenados — los mismos
    "puntos de pie" que publica el pipeline por cada frame y cada persona
    trackeada. Sobre esa cuadrícula se dibuja el contorno de cada zona
    (sólido = producto, punteado = personal) en su posición real.

    El widget recibe ya filtradas las muestras de personal (ver
    `EventStore.get_position_samples(exclude_employees=True)`, el default):
    un empleado no debe tratarse como densidad de cliente, solo como el
    contorno de referencia de su zona.
    """

    GRID_SIZE = (64, 36)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples = []
        self._zones: list[Zone] = []
        self._frame_size = FRAME_SIZE
        # Imagen del heatmap ya calculada. `paintEvent` corre en cada
        # repintado (redimensionar la ventana, pasar el mouse por encima);
        # recalcular ahí la cuadrícula de densidad y el colormap sobre miles
        # de muestras hacía trabajo pesado decenas de veces por segundo.
        self._heat_image: QImage | None = None
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, samples, zones: list[Zone], frame_size: tuple[int, int] = FRAME_SIZE):
        self._samples = samples
        self._zones = zones
        self._frame_size = frame_size
        self._heat_image = self._build_heat_image()
        self.update()

    def _build_heat_image(self) -> QImage | None:
        """Cuadrícula de densidad -> imagen RGBA lista para dibujar."""
        if not self._samples:
            return None

        cols, rows = self.GRID_SIZE
        grid = build_density_grid(self._samples, self._frame_size, grid_size=self.GRID_SIZE, sigma=1.2)
        peak = float(grid.max()) or 1.0
        normalized = np.clip((grid / peak) * 255, 0, 255).astype(np.uint8)
        colored_bgr = cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)
        colored_rgb = cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB)
        # Celdas casi vacías se dejan transparentes para no pintar todo
        # el frame de "azul oscuro" cuando en realidad no hay muestras ahí.
        alpha = np.where(normalized > 6, 235, 0).astype(np.uint8)
        rgba = np.ascontiguousarray(np.dstack([colored_rgb, alpha]))
        # .copy(): QImage no toma posesión del buffer de numpy, y `rgba` es
        # local — sin la copia la imagen apuntaría a memoria liberada.
        return QImage(rgba.data, cols, rows, rgba.strides[0], QImage.Format_RGBA8888).copy()

    def _draw_area_rect(self) -> QRectF:
        """ROI dibujable dentro del widget, respetando el aspecto del frame."""
        frame_w, frame_h = self._frame_size
        aspect = frame_w / frame_h
        w, h = self.width(), self.height()
        if w / h > aspect:
            draw_h = h
            draw_w = h * aspect
        else:
            draw_w = w
            draw_h = w / aspect
        return QRectF((w - draw_w) / 2, (h - draw_h) / 2, draw_w, draw_h)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        draw_rect = self._draw_area_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Colors.BG_INPUT))
        painter.drawRoundedRect(draw_rect, 6, 6)

        if self._heat_image is not None:
            painter.drawImage(draw_rect, self._heat_image)

        frame_w, frame_h = self._frame_size
        sx, sy = draw_rect.width() / frame_w, draw_rect.height() / frame_h

        def to_widget(point: tuple[float, float]) -> QPointF:
            return QPointF(draw_rect.left() + point[0] * sx, draw_rect.top() + point[1] * sy)

        for zone in self._zones:
            is_staff = zone.zone_type == "staff"
            pen = QPen(QColor(Colors.INFO_BLUE if not is_staff else Colors.WARNING), 2)
            if is_staff:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([to_widget(p) for p in zone.polygon]))

            centroid = to_widget((
                sum(p[0] for p in zone.polygon) / len(zone.polygon),
                sum(p[1] for p in zone.polygon) / len(zone.polygon),
            ))
            # Las zonas 'staff' son un ROI de rastreo de personal (para
            # excluirlo de las métricas de cliente vía StaffZoneTracker),
            # no una persona detectada — el nombre que le haya puesto quien
            # las dibujó (ej. "Persona 1") es solo una etiqueta de esa zona,
            # así que aquí se muestra genérico para no dar a entender que
            # el heatmap está identificando individuos.
            label = "Zona de personal" if is_staff else zone.name
            painter.setFont(QFont("Consolas", 7))
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            painter.drawText(centroid, label)

        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(draw_rect, 6, 6)

        self._draw_scale(painter, draw_rect)
        painter.end()

    def _draw_scale(self, painter: QPainter, draw_rect: QRectF) -> None:
        """
        Escala de intensidad del mapa de calor.

        Sin ella, un degradado de color no dice nada: el usuario ve manchas
        brillantes sin saber si significan mucha gente o poca.
        """
        if self._heat_image is None:
            return

        bar_w, bar_h = 120, 8
        x = draw_rect.right() - bar_w - 12
        y = draw_rect.bottom() - bar_h - 26

        # Las mismas paradas del colormap INFERNO que usa la cuadrícula.
        steps = 24
        ramp = np.linspace(0, 255, steps).astype(np.uint8).reshape(1, steps)
        colors = cv2.applyColorMap(ramp, cv2.COLORMAP_INFERNO)[0]
        for i, bgr in enumerate(colors):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(int(bgr[2]), int(bgr[1]), int(bgr[0])))
            painter.drawRect(QRectF(x + i * bar_w / steps, y, bar_w / steps + 1, bar_h))

        # Las dos etiquetas van DEBAJO de la barra y dentro del recuadro:
        # colocadas a los lados se salían del área dibujable y se recortaban.
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor(Colors.TEXT_PRIMARY))
        painter.drawText(QRectF(x, y + bar_h + 2, bar_w, 13), Qt.AlignLeft | Qt.AlignVCenter, "menos")
        painter.drawText(QRectF(x, y + bar_h + 2, bar_w, 13), Qt.AlignRight | Qt.AlignVCenter, "más gente")


# ============================================================ tab principal --
class DashboardTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = EventStore()
        self.zone_manager = ZoneManager()
        self._zone_names: dict[str, str] = {}
        self._current_zones: list[Zone] = []

        self._build_ui()
        self._populate_sessions()
        self.refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_INTERVAL_MS)

    # -------------------------------------------------------------- UI --
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = HeaderBar("DASHBOARD_METRICAS")
        # El engranaje de HeaderBar no tenía ninguna acción de "Configuración"
        # real en esta pestaña; se reutiliza como acceso directo al mapa de
        # calor en grande (el widget embebido más abajo es chico y comparte
        # espacio con el ranking de zonas).
        self.header.set_action(create_heatmap_icon(), "Ver mapa de calor en grande")
        self.header.settings_clicked.connect(self._open_heatmap_dialog)
        outer.addWidget(self.header)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 10, 12, 0)
        toolbar.addWidget(QLabel("Video analizado:"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(260)
        self.session_combo.currentIndexChanged.connect(self._on_session_changed)
        toolbar.addWidget(self.session_combo)
        toolbar.addStretch()

        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedText")
        toolbar.addWidget(self.status_label)

        self.btn_seed = QPushButton("Cargar sesión de demostración")
        self.btn_seed.setToolTip(
            "Genera eventos de ejemplo (marcados como demo) para esta sesión "
            "mientras el pipeline de detección no haya publicado eventos reales."
        )
        self.btn_seed.clicked.connect(self._on_seed_demo)
        toolbar.addWidget(self.btn_seed)

        self.btn_clear_demo = QPushButton("Borrar datos de demo")
        self.btn_clear_demo.setToolTip(
            "Elimina únicamente las filas sintéticas de esta sesión. Los "
            "datos de un análisis real no se tocan."
        )
        self.btn_clear_demo.clicked.connect(self._on_clear_demo)
        toolbar.addWidget(self.btn_clear_demo)

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.setObjectName("primary")
        self.btn_refresh.clicked.connect(self.refresh)
        toolbar.addWidget(self.btn_refresh)

        outer.addLayout(toolbar)

        # Aviso permanente de datos sintéticos. Mientras la sesión tenga
        # filas sembradas, esta banda queda visible: un dashboard que
        # presenta números de ejemplo sin decirlo es peor que uno vacío.
        self.demo_banner = QLabel()
        self.demo_banner.setWordWrap(True)
        self.demo_banner.setStyleSheet(
            f"background-color: {Colors.WARNING}; color: #1A1A1A; "
            f"padding: 6px 12px; font-weight: 700;"
        )
        self.demo_banner.setVisible(False)
        outer.addWidget(self.demo_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)

        # --- KPI row ---
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.kpi_total = KpiCard("INTERACCIONES TOTALES")
        self.kpi_take_rate = KpiCard("SE LO LLEVARON")
        self.kpi_dwell = KpiCard("TIEMPO MEDIO FRENTE A LA GÓNDOLA")
        self.kpi_employee = KpiCard("ACTIVIDAD DE PERSONAL")
        self.kpi_zones = KpiCard("ZONAS CON ACTIVIDAD")
        for kpi in (self.kpi_total, self.kpi_take_rate, self.kpi_dwell, self.kpi_employee, self.kpi_zones):
            kpi_row.addWidget(kpi)
        content_layout.addLayout(kpi_row)

        # --- grid principal: gráficos (izq, ancho) + laterales (der) ---
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)

        timeline_card = Card("Interacciones a lo largo del video", "Tomado (línea sólida) y devuelto (línea punteada)")
        self.timeline_chart = TimelineChart()
        self.timeline_empty = EmptyState("Todavía no hay interacciones. Inicia el análisis en la pestaña 2 o carga la demostración.")
        timeline_card.body.addWidget(self.timeline_chart)
        timeline_card.body.addWidget(self.timeline_empty)
        grid.addWidget(timeline_card, 0, 0)

        zones_card = Card("Interacciones por zona de góndola", "Cuántas veces se tomó y se devolvió producto en cada zona")
        self.zone_chart = ZoneBarChart()
        self.zone_empty = EmptyState("Todavía no hay interacciones asociadas a ninguna zona.")
        zones_card.body.addWidget(self.zone_chart)
        zones_card.body.addWidget(self.zone_empty)
        grid.addWidget(zones_card, 1, 0)

        recent_card = Card("Últimas interacciones detectadas", "Las 15 más recientes de esta sesión")
        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(["Track", "Zona", "Acción", "t (s)"])
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.setSelectionMode(QTableWidget.NoSelection)
        self.events_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.events_table.setMinimumHeight(240)
        recent_card.body.addWidget(self.events_table)
        grid.addWidget(recent_card, 2, 0)

        heatmap_card = Card(
            "Mapa de calor de circulación de clientes",
            "Personal excluido del cálculo · botón de la barra superior para verlo en grande",
        )
        self.heatmap = HeatmapWidget()
        self.heatmap_empty = EmptyState("Todavía no hay recorridos registrados. Inicia el análisis en la pestaña 2.")
        heatmap_card.body.addWidget(self.heatmap)
        heatmap_card.body.addWidget(self.heatmap_empty)
        grid.addWidget(heatmap_card, 0, 1)

        perf_card = Card("Zonas con más movimiento", "Ordenadas por número de interacciones")
        self.ranking_label = QLabel("")
        self.ranking_label.setWordWrap(True)
        perf_card.body.addWidget(self.ranking_label)
        grid.addWidget(perf_card, 1, 1)

        legend_card = Card("Leyenda")
        legend_layout = QVBoxLayout()
        legend_layout.addWidget(self._legend_row(taken_color(), "Tomado — el cliente se llevó el producto"))
        legend_layout.addWidget(self._legend_row(returned_color(), "Devuelto — lo dejó de vuelta en el estante"))
        legend_layout.addWidget(self._legend_row(Colors.INFO_BLUE, "Zona de góndola"))
        legend_layout.addWidget(self._legend_row(employee_color(), "Zona de personal (excluida de las métricas)"))
        legend_card.body.addLayout(legend_layout)
        grid.addWidget(legend_card, 2, 1)

        content_layout.addLayout(grid)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

    @staticmethod
    def _legend_row(color: str, text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background-color:{color}; border-radius:5px;")
        layout.addWidget(dot)
        label = QLabel(text)
        label.setObjectName("mutedText")
        layout.addWidget(label)
        layout.addStretch()
        return row

    # --------------------------------------------------------- sesiones --
    def _populate_sessions(self):
        """
        Lista las sesiones disponibles: las que tienen zonas dibujadas más
        las que ya tienen datos en la base (puede haber datos de una sesión
        cuyas zonas se borraron después).
        """
        base = Path(config.ZONES_STORAGE_PATH)
        from_zones = {p.name for p in base.iterdir() if p.is_dir()} if base.exists() else set()
        from_data = {v for v in self.store.list_sessions() if v}
        video_ids = sorted(from_zones | from_data)

        current = self.session_combo.currentText() if self.session_combo.count() else ""
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItems(video_ids or [NO_SESSION_LABEL])
        if current:
            index = self.session_combo.findText(current)
            if index >= 0:
                self.session_combo.setCurrentIndex(index)
        self.session_combo.blockSignals(False)
        self._load_zone_names()

    def show_session(self, video_id: str) -> None:
        """
        Selecciona una sesión y refresca. Es el punto de entrada desde la
        pestaña de zonas cuando termina un análisis (paso 2 → 3).
        """
        self._populate_sessions()
        index = self.session_combo.findText(video_id)
        if index >= 0:
            self.session_combo.setCurrentIndex(index)
        self._load_zone_names()
        self.refresh()

    @property
    def current_video_id(self) -> str | None:
        """
        `video_id` de la sesión seleccionada, o None si no hay ninguna.

        None significa "no filtrar" para las consultas del almacén: es lo
        que se usa cuando todavía no hay ninguna sesión con nombre.
        """
        text = self.session_combo.currentText()
        return None if not text or text == NO_SESSION_LABEL else text

    def _on_session_changed(self, _index: int):
        self._load_zone_names()
        self.refresh()

    def _load_zone_names(self):
        video_id = self.current_video_id
        zones = self.zone_manager.load_zones(video_id) if video_id else []
        self._zone_names = {z.zone_id: z.name for z in zones}
        self._current_zones = zones

    def _frame_size_for_session(self) -> tuple[int, int]:
        """
        Resolución del frame sobre el que se dibujaron las zonas.

        Sale del reporte `.json` que la limpieza deja junto al video
        (`output_resolution`). Antes estaba fija en 1280x720: con un video
        4K, las muestras de posición y los polígonos quedaban en escalas
        distintas y el heatmap aparecía desalineado respecto a las zonas.
        """
        video_id = self.current_video_id
        if not video_id:
            return FRAME_SIZE
        report_path = Path(config.PROCESSED_DIR) / f"{video_id}.json"
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                resolution = json.load(f).get("output_resolution")
            if resolution and len(resolution) == 2 and all(int(v) > 0 for v in resolution):
                return int(resolution[0]), int(resolution[1])
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass  # sin sidecar legible se cae al default
        return FRAME_SIZE

    def _on_clear_demo(self):
        video_id = self.current_video_id
        deleted = self.store.delete_demo_rows(video_id)
        self.status_label.setText(
            f"Datos de demostración eliminados ({deleted} evento(s))."
            if deleted else "Esta sesión no tenía datos de demostración."
        )
        self.refresh()

    # ----------------------------------------------------------- acciones --
    def _open_heatmap_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Mapa de calor de circulación")
        dialog.resize(960, 660)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        caption = QLabel(
            "Contorno sólido = zona de producto (ROI de góndola). Contorno punteado = "
            "zona de personal — un área de rastreo definida en la pestaña 2 para identificar "
            "empleados, no una persona detectada por el sistema. Sus muestras de posición se "
            "excluyen del cálculo de densidad: un empleado parado horas en el mismo punto no "
            "debería aparecer como una mancha de interés de cliente."
        )
        caption.setWordWrap(True)
        caption.setObjectName("mutedText")
        layout.addWidget(caption)

        big_heatmap = HeatmapWidget()
        big_heatmap.set_data(
            self.store.get_position_samples(video_id=self.current_video_id),
            self._current_zones,
            self._frame_size_for_session(),
        )
        layout.addWidget(big_heatmap, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(dialog.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        dialog.exec()

    def _on_seed_demo(self):
        zones = self._current_zones
        if not zones:
            self.status_label.setText("No hay zonas guardadas para esta sesión: crea zonas en la pestaña 2 primero.")
            return
        inserted = seed_demo_session(self.store, zones, video_id=self.current_video_id or "")
        self.status_label.setText(f"Sesión de demostración cargada ({inserted} eventos sintéticos).")
        self.refresh()

    # ------------------------------------------------------------ refresco --
    def refresh(self):
        # Relee la geometría de zonas desde disco en cada refresco (no solo
        # al cambiar de sesión): si en la pestaña "Edición de Zonas" se
        # movieron puntos y se sobreescribió el JSON, el heatmap los
        # refleja en el siguiente tick (<=3s) sin tener que tocar el combo.
        self._load_zone_names()

        video_id = self.current_video_id
        summary = self.store.get_summary(video_id)
        zone_rows = self.store.get_zone_breakdown(video_id)
        timeline = self.store.get_timeline(bucket_sec=30.0, video_id=video_id)
        recent = self.store.get_recent_events(limit=15, video_id=video_id)
        position_samples = self.store.get_position_samples(video_id=video_id)

        # Sembrar la demo solo tiene sentido mientras no haya datos reales
        # de esta sesión; el aviso de datos sintéticos se mantiene mientras
        # queden filas de demo, aunque ya se haya sembrado.
        has_real = has_data(self.store, video_id)
        demo_events = self.store.count_demo_events(video_id)
        self.btn_seed.setEnabled(not has_real and not demo_events)
        self.btn_clear_demo.setVisible(demo_events > 0)

        if demo_events:
            self.demo_banner.setText(
                f"DATOS DE DEMOSTRACIÓN — {demo_events} de los {summary['total_events']} eventos "
                "de esta sesión son sintéticos, generados para poder ver el tablero antes de "
                "correr el análisis. No provienen de ningún video."
            )
            self.demo_banner.setVisible(True)
        else:
            self.demo_banner.setVisible(False)

        if not has_real and not demo_events and not self.status_label.text():
            self.status_label.setText(
                "Sin eventos todavía — inicia el análisis en la pestaña 2 o carga la demostración."
            )

        # KPIs
        self.kpi_total.set_value(str(summary["total_events"]))
        self.kpi_take_rate.set_value(
            f"{summary['take_rate']*100:.1f}%",
            f"{summary['taken']} tomados / {summary['returned']} devueltos",
        )
        self.kpi_dwell.set_value(f"{summary['avg_dwell_sec']:.1f}s")
        self.kpi_employee.set_value(
            f"{summary['employee_share']*100:.1f}%",
            f"{summary['employee_events']} de {summary['total_events']} eventos",
        )
        self.kpi_zones.set_value(str(summary["active_zones"]))

        # Zone chart
        for row in zone_rows:
            row["name"] = self._zone_names.get(row["zone_id"], row["zone_id"])
        self.zone_chart.set_data(zone_rows)
        self.zone_chart.setVisible(bool(zone_rows))
        self.zone_empty.setVisible(not zone_rows)

        # Timeline
        self.timeline_chart.set_data(timeline)
        self.timeline_chart.setVisible(len(timeline) >= 2)
        self.timeline_empty.setVisible(len(timeline) < 2)

        # Heatmap de circulación (PositionSample -> build_density_grid)
        zones = self._current_zones
        self.heatmap.set_data(position_samples, zones, self._frame_size_for_session())
        self.heatmap.setVisible(bool(position_samples))
        self.heatmap_empty.setVisible(not position_samples)

        # Ranking
        ranked = sorted(zone_rows, key=lambda r: r["taken"] + r["returned"], reverse=True)
        if ranked:
            lines = [
                f"{i+1}. {r['name']} — {r['taken']+r['returned']} interacciones "
                f"· {r['avg_dwell_sec']:.1f} s de permanencia"
                for i, r in enumerate(ranked[:5])
            ]
            self.ranking_label.setText("\n".join(lines))
        else:
            self.ranking_label.setText("Sin datos todavía.")

        # Tabla de eventos recientes
        self.events_table.setRowCount(len(recent))
        for i, ev in enumerate(recent):
            zone_name = self._zone_names.get(ev["zone_id"], ev["zone_id"])
            action_item = QTableWidgetItem("● Tomado" if ev["action"] == "taken" else "● Devuelto")
            action_item.setForeground(QColor(taken_color() if ev["action"] == "taken" else returned_color()))
            self.events_table.setItem(i, 0, QTableWidgetItem(f"#{ev['track_id']}"))
            self.events_table.setItem(i, 1, QTableWidgetItem(zone_name))
            self.events_table.setItem(i, 2, action_item)
            self.events_table.setItem(i, 3, QTableWidgetItem(f"{ev['timestamp']:.1f}"))
