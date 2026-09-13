"""
Pestaña de edición de zonas (ROI).

Layout simplificado (esta versión): se quitó `VideoInfoPanel` de esta
pantalla (el header ya muestra el nombre del video activo, así que ese
panel era información repetida sin ninguna acción real). El panel
"Regiones de interés activas" pasó de la derecha a la izquierda, y el
lienzo de dibujo ahora ocupa el resto del ancho disponible — antes
competía por espacio con tres columnas, ahora son solo dos.
"""
import cv2
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.backend.event_store import EventStore, connect_store_to_publisher
from app.core.detection.event_publisher import InProcessPublisher
from app.core.detection.pipeline import DetectionPipeline
from app.core.detection.pipeline_worker import DetectionPipelineWorker
from app.core.detection.pose import PoseEstimator
from app.core.detection.roi_suggester import SUGGESTED_ID_PREFIX
from app.core.detection.schemas import Zone
from app.core.detection.state_machine import InteractionState, InteractionStateMachine
from app.core.detection.tracker import PersonTracker
from app.core.detection.zone import ZoneManager, normalize_video_id
from app.core.ingestion.frame_source import VideoFileFrameSource
from app.core.ingestion.session import AnalysisSession
from app.core.ingestion.video_loader import VideoLoadError, extract_thumbnail, load_video
from app.ui.theme import Colors
from app.ui.widgets.footer import FooterBar
from app.ui.widgets.header import HeaderBar
from app.utils.config import ANALYSIS_FRAME_STRIDE, LOGS_DIR

# Colores por rol de zona, consistentes con el heatmap del Dashboard
# (app/ui/dashboard_tab.py): producto = azul info, personal = ámbar.
#
# Es una función y no un diccionario a nivel de módulo porque el tema se
# cambia en caliente: un diccionario construido al importar se quedaría
# con los colores del tema inicial para siempre.
def zone_type_color(zone_type: str) -> str:
    return Colors.WARNING if zone_type == "staff" else Colors.INFO_BLUE


def suggested_color() -> str:
    """
    Color de las zonas propuestas y aún no guardadas.

    Se distingue de las guardadas por color **y** por trazo punteado: el
    estado de una zona no puede depender solo del color.
    """
    return Colors.SUCCESS


def _polygon_area_px(points: List[Tuple[float, float]]) -> float:
    """
    Área de un polígono en píxeles cuadrados (fórmula del "shoelace").
    No hay calibración píxel→metro en el proyecto: este valor es solo
    referencial en px², no representa metros cuadrados reales.
    """
    if len(points) < 3:
        return 0.0
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


class InfoBanner(QFrame):
    """Aviso informativo sobre el lienzo (ej. "Modo de dibujo de ROI's")."""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.title_label = QLabel()
        self.title_label.setObjectName("sectionTitle")
        layout.addWidget(self.title_label)

        self.desc_label = QLabel()
        self.desc_label.setObjectName("mutedText")
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        self.set_content(title, description)

    def set_content(self, title: str, description: str):
        """Actualiza el título/descripción sin reconstruir el widget
        (usado al cambiar el rol de zona: producto vs. personal)."""
        self.title_label.setText(f"ⓘ  {title}")
        self.desc_label.setText(description)


class ZoneCanvas(QWidget):
    """Lienzo sobre el frame de referencia: cada click agrega un vértice del polígono."""

    # Emitida al agregar un vértice con el teclado, para que la pestaña
    # refresque la lista de zonas igual que hace tras un click.
    point_added = Signal()

    # Paso del cursor de teclado, en píxeles de la imagen. Con Shift se
    # multiplica por 10 para poder cruzar el frame sin cien pulsaciones.
    KEY_STEP = 4
    KEY_STEP_FAST = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        # El lienzo era exclusivamente de ratón: no había forma de marcar
        # una zona sin él. Con foco de teclado, las flechas mueven un
        # cursor y Enter fija el vértice.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Lienzo de zonas")
        self.setAccessibleDescription(
            "Usa las flechas para mover el cursor sobre la imagen, Enter para "
            "agregar un vértice y Retroceso para deshacer el último."
        )
        self._key_cursor: Optional[Tuple[float, float]] = None
        self._image: Optional[QImage] = None
        self._offset = (0.0, 0.0)
        self._scale = 1.0
        self.points: List[Tuple[float, float]] = []
        self.existing_zone: Optional[Zone] = None  # zona guardada seleccionada (overlay azul)
        # Zonas propuestas por el sugeridor automático: se pintan de fondo,
        # punteadas, hasta que el usuario las acepte o las descarte. No
        # están guardadas en disco.
        self.suggested_zones: List[Zone] = []
        # Color del polígono en construcción: cambia según el rol elegido en
        # el combo "Tipo" (producto/personal), para que quede visualmente
        # claro para cuál de los dos se están agregando puntos.
        self._draw_color = QColor(Colors.ACCENT)

    # ------------------------------------------------------------- API --
    def set_frame(self, image: QImage) -> None:
        """Fija el frame de referencia (resolución original) y reinicia el dibujo."""
        self._image = image
        self.points = []
        self.existing_zone = None
        self.update()

    def set_suggested_zones(self, zones: List[Zone]) -> None:
        """Fija las zonas propuestas que se dibujan de fondo (sin guardar)."""
        self.suggested_zones = list(zones)
        self.update()

    def set_draw_color(self, color: QColor) -> None:
        """Cambia el color de los puntos/línea en construcción (rol de zona)."""
        self._draw_color = color
        self.update()

    # ------------------------------------------------------- teclado --
    def keyPressEvent(self, event):
        """
        Alternativa completa al ratón para dibujar una zona.

        Flechas mueven el cursor (Shift acelera), Enter fija un vértice,
        Retroceso deshace el último y Suprimir limpia el polígono.
        """
        if self._image is None:
            super().keyPressEvent(event)
            return

        if self._key_cursor is None:
            self._key_cursor = (self._image.width() / 2, self._image.height() / 2)

        step = self.KEY_STEP_FAST if event.modifiers() & Qt.ShiftModifier else self.KEY_STEP
        x, y = self._key_cursor
        key = event.key()

        if key == Qt.Key_Left:
            x -= step
        elif key == Qt.Key_Right:
            x += step
        elif key == Qt.Key_Up:
            y -= step
        elif key == Qt.Key_Down:
            y += step
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.points.append((x, y))
            self.point_added.emit()
            self.update()
            return
        elif key == Qt.Key_Backspace:
            self.undo_point()
            return
        elif key == Qt.Key_Delete:
            self.clear_points()
            return
        else:
            super().keyPressEvent(event)
            return

        self._key_cursor = (
            min(max(x, 0.0), float(self._image.width() - 1)),
            min(max(y, 0.0), float(self._image.height() - 1)),
        )
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None

    def clear_points(self) -> None:
        self.points = []
        self.update()

    def undo_point(self) -> None:
        if self.points:
            self.points.pop()
            self.update()

    # ----------------------------------------------------- geometría --
    def _widget_to_image(self, widget_pos: QPointF) -> Optional[Tuple[float, float]]:
        """Convierte un punto del widget a coordenadas del frame original."""
        if self._image is None or self._scale <= 0:
            return None
        img_x = (widget_pos.x() - self._offset[0]) / self._scale
        img_y = (widget_pos.y() - self._offset[1]) / self._scale
        if img_x < 0 or img_y < 0 or img_x >= self._image.width() or img_y >= self._image.height():
            return None
        return (img_x, img_y)

    def _image_to_widget(self, img_x: float, img_y: float) -> QPointF:
        return QPointF(
            self._offset[0] + img_x * self._scale,
            self._offset[1] + img_y * self._scale,
        )

    # --------------------------------------------------------- eventos --
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._image is not None:
            xy = self._widget_to_image(event.position())
            if xy is not None:
                self.points.append(xy)
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(Colors.BG_INPUT))

        if self._image is None:
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.drawText(self.rect(), Qt.AlignCenter, "Carga un video para definir zonas")
            return

        # Dibujar frame escalado (KeepAspectRatio, centrado)
        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        offset_x = (self.width() - scaled.width()) // 2
        offset_y = (self.height() - scaled.height()) // 2
        self._offset = (float(offset_x), float(offset_y))
        self._scale = scaled.width() / pixmap.width()
        painter.drawPixmap(offset_x, offset_y, scaled)

        # Overlay: zonas sugeridas (punteadas, al fondo). Se dibujan antes
        # que todo lo demás para que nunca tapen el polígono en edición.
        for zone in self.suggested_zones:
            if len(zone.polygon) < 3:
                continue
            pts = [self._image_to_widget(x, y) for (x, y) in zone.polygon]
            pen = QPen(QColor(suggested_color()), 2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(pts + [pts[0]])
            painter.drawText(pts[0] + QPointF(4, -4), zone.name)

        # Overlay: zona ya guardada seleccionada (azul)
        if self.existing_zone is not None and len(self.existing_zone.polygon) >= 3:
            pts = [self._image_to_widget(x, y) for (x, y) in self.existing_zone.polygon]
            painter.setPen(QPen(QColor(0, 128, 255), 2))
            painter.drawPolyline(pts + [pts[0]])
            painter.setBrush(QColor(0, 128, 255))
            painter.setPen(Qt.NoPen)
            for p in pts:
                painter.drawEllipse(p, 3, 3)

        # Cursor de teclado: solo visible cuando el lienzo tiene el foco,
        # para no ensuciar la imagen cuando se trabaja con el ratón.
        if self.hasFocus() and self._key_cursor is not None:
            cursor_point = self._image_to_widget(*self._key_cursor)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(Colors.FOCUS), 2))
            painter.drawLine(cursor_point.x() - 10, cursor_point.y(),
                             cursor_point.x() + 10, cursor_point.y())
            painter.drawLine(cursor_point.x(), cursor_point.y() - 10,
                             cursor_point.x(), cursor_point.y() + 10)
            painter.drawEllipse(cursor_point, 6, 6)

        # Polígono en construcción — color según el rol de zona seleccionado
        pts = [self._image_to_widget(x, y) for (x, y) in self.points]
        if pts:
            painter.setPen(QPen(self._draw_color, 2))
            painter.drawPolyline(pts + [pts[0]])
            painter.setBrush(self._draw_color)
            painter.setPen(Qt.NoPen)
            for p in pts:
                painter.drawEllipse(p, 4, 4)


class ZoneEditorTab(QWidget):
    """
    Pestaña 2: zonas (ROI) sobre el frame de referencia, y arranque del análisis.

    Es el centro del flujo de la app: recibe la sesión ya preparada de la
    pestaña 1 (`load_session`), deja corregir las zonas propuestas, y al
    terminar el análisis avisa a la pestaña 3 con `analysis_finished`.
    """

    # Emitida con el video_id cuando el análisis termina de recorrer el
    # video: es el paso 2 → 3 del flujo (MainWindow salta al dashboard).
    analysis_finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.zone_manager = ZoneManager()
        # La sesión activa: sabe crear su propia fuente de frames, sea un
        # archivo o una cámara en directo. Antes aquí solo había una ruta,
        # y por eso no se podía analizar nada que no fuera un archivo.
        self._session: Optional[AnalysisSession] = None
        self._current_video_id: Optional[str] = None
        self._current_video_path: Optional[Path] = None
        self._current_video_fps: float = 30.0
        # Zonas propuestas automáticamente, aún NO guardadas en disco.
        self._suggested_zones: List[Zone] = []
        # zone_id provisional de la sugerencia que se está editando en el
        # lienzo: al guardarla deja de ser propuesta y sale de la lista.
        self._editing_suggested_id: Optional[str] = None
        # Almacén de la corrida de análisis actual. Se crea al iniciar el
        # análisis y se conecta al bus del pipeline: sin esta conexión, todo
        # lo que el pipeline publica se pierde y el dashboard queda vacío.
        self._store: Optional[EventStore] = None
        self._publisher: Optional[InProcessPublisher] = None
        self._debug_worker: Optional[DetectionPipelineWorker] = None
        self._analysis_total: int = 0
        self._debug_reference_image: Optional[QImage] = None
        self._debug_zones: List[Zone] = []
        # Referencia a la state_machine de la corrida de debug actual: se
        # necesita en `_on_debug_frame` para saber en qué estado
        # (IDLE/REACHING/HOLDING) está cada (track_id, zone_id) y así
        # colorear/etiquetar igual que `scripts/run_pipeline_debug.py`.
        self._debug_state_machine: Optional[InteractionStateMachine] = None
        # zone_id de la zona guardada que se está editando ahora mismo (sus
        # puntos viven ya cargados en self.canvas.points); None = se está
        # dibujando una zona nueva. Ver `_on_zone_selected`/`_on_save`.
        self._editing_zone_id: Optional[str] = None
        # Workers de debug que ya se pidieron interrumpir (`_stop_debug_worker`)
        # pero cuyo hilo real puede seguir vivo un instante más: se guarda la
        # referencia acá (en vez de perderla al reasignar `_debug_worker`)
        # para que Qt no lo destruya mientras el QThread sigue corriendo.
        self._retiring_workers: List[DetectionPipelineWorker] = []
        self._build_ui()
        self._refresh_zone_list()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # show_action=False: esta pestaña no tenía ninguna "Configuración"
        # real conectada al engranaje.
        self.header = HeaderBar(source_name="VISION_ZONE_05", show_action=False)
        main_layout.addWidget(self.header)

        # --- Zona central: panel de zonas (izquierda) + lienzo (derecha, más grande) ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_zone_panel())
        splitter.addWidget(self._build_canvas_section())
        splitter.setSizes([300, 780])  # el lienzo ahora domina el espacio
        main_layout.addWidget(splitter, stretch=1)

        # El combo "Tipo" vive en el panel de zonas (construido primero) pero
        # actualiza el banner/color del lienzo (construido después) — se
        # aplica el estado inicial acá, una vez que ambos ya existen.
        self._on_type_changed()

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(70)
        main_layout.addWidget(self.log_area)

        self.footer = FooterBar()
        main_layout.addWidget(self.footer)

    def _build_canvas_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self.banner = InfoBanner(
            "Modo de dibujo de ROI's",
            "Dibuja o edita cómo están las áreas en donde los clientes "
            "sacan y ponen los productos de las góndolas.",
        )
        layout.addWidget(self.banner)

        self.canvas = ZoneCanvas()
        self.canvas.point_added.connect(self._refresh_zone_list)
        layout.addWidget(self.canvas, stretch=1)

        # Ayuda de teclado, siempre visible: si la alternativa al ratón no
        # se anuncia, es como si no existiera.
        keyboard_hint = QLabel(
            "Con el lienzo enfocado: flechas mueven el cursor (Shift acelera), "
            "Enter agrega un vértice, Retroceso deshace."
        )
        keyboard_hint.setObjectName("mutedText")
        keyboard_hint.setWordWrap(True)
        layout.addWidget(keyboard_hint)

        # --- Barra de acciones ---
        actions = QHBoxLayout()
        self.btn_load = QPushButton("Cargar &video")
        self.btn_load.setAccessibleName("Cargar un video para definir zonas")
        self.btn_load.clicked.connect(self._on_load_video)
        self.btn_undo = QPushButton("Deshacer &punto")
        self.btn_undo.setAccessibleName("Deshacer el último vértice")
        self.btn_undo.clicked.connect(self._on_undo)
        self.btn_clear = QPushButton("Limpiar puntos")
        self.btn_clear.setAccessibleName("Borrar todos los vértices del polígono actual")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_debug = QPushButton("▶  Iniciar análisis")
        self.btn_debug.setObjectName("primary")
        self.btn_debug.setAccessibleName("Iniciar el análisis del video")
        self.btn_debug.setToolTip(
            "Corre el pipeline completo sobre el video: detecta personas, "
            "mide interacciones y permanencia, y guarda todo en la base "
            "local. Al terminar, pasa al Dashboard de Métricas."
        )
        self.btn_debug.clicked.connect(self.on_analysis_button)
        self.btn_reset = QPushButton("&Reiniciar análisis")
        self.btn_reset.setAccessibleName("Reiniciar el análisis sobre el mismo video")
        self.btn_reset.setToolTip(
            "Detiene el análisis en curso (si hay uno, sin esperar a que "
            "termine el video) y lo vuelve a correr desde el inicio sobre "
            "el mismo video ya cargado — no hace falta cargarlo de nuevo. "
            "Para analizar un video distinto, usa 'Cargar video'."
        )
        self.btn_reset.clicked.connect(self._on_reset_session)

        actions.addWidget(self.btn_load)
        actions.addWidget(self.btn_undo)
        actions.addWidget(self.btn_clear)
        actions.addWidget(self.btn_debug)
        actions.addStretch()
        actions.addWidget(self.btn_reset)
        layout.addLayout(actions)

        # Progreso del análisis. Antes el único indicio de que el pipeline
        # seguía vivo era el contador de FPS del pie: un video de dos
        # minutos parecía colgado.
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setAccessibleName("Progreso del análisis")
        self.analysis_progress.setVisible(False)
        layout.addWidget(self.analysis_progress)

        self.analysis_status = QLabel("")
        self.analysis_status.setObjectName("mutedText")
        self.analysis_status.setWordWrap(True)
        self.analysis_status.setAccessibleName("Estado del análisis")
        layout.addWidget(self.analysis_status)

        return container

    def _build_zone_panel(self) -> QWidget:
        """Panel izquierdo: "Regiones de interés activas" + formulario de guardado."""
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)

        title = QLabel("Regiones de interés activas")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.zone_list = QListWidget()
        self.zone_list.setAccessibleName("Zonas definidas para este video")
        self.zone_list.itemSelectionChanged.connect(self._on_zone_selected)
        layout.addWidget(self.zone_list, stretch=1)

        # --- Formulario para guardar la zona en construcción ---
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Nombre:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ej: Góndola A1, Pasillo 2…")
        self.name_input.setAccessibleName("Nombre de la zona")
        name_row.addWidget(self.name_input, stretch=1)
        layout.addLayout(name_row)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Rol de la zona:"))
        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName("Rol de la zona")
        # Los únicos dos valores que el esquema `Zone.zone_type` acepta hoy:
        # "product" (góndola, dwell time de cliente) y "staff" (personal de
        # la tienda/establecimiento — puntos aparte de los de la góndola,
        # excluidos de las métricas de cliente vía StaffZoneTracker).
        self.type_combo.addItem("Góndola / producto (dwell time de cliente)", userData="product")
        self.type_combo.addItem("Personal de la tienda (excluida de métricas)", userData="staff")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.type_combo, stretch=1)

        self.type_color_dot = QLabel()
        self.type_color_dot.setFixedSize(12, 12)
        type_row.addWidget(self.type_color_dot)
        layout.addLayout(type_row)

        hint = QLabel(
            "Elige el rol arriba y haz click sobre el frame para agregar sus "
            "vértices — cada zona guardada queda con ese rol (góndola o "
            "personal). Mínimo 3 puntos."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # --- Acciones sobre las zonas propuestas automáticamente ---
        # Solo visibles cuando hay sugerencias pendientes de revisar.
        suggested_row = QHBoxLayout()
        self.btn_accept_suggested = QPushButton("Aceptar sugeridas")
        self.btn_accept_suggested.setToolTip(
            "Guarda todas las zonas propuestas tal como están. Después se "
            "pueden seguir editando una por una como cualquier otra zona."
        )
        self.btn_accept_suggested.clicked.connect(self._on_accept_suggested)
        self.btn_discard_suggested = QPushButton("Descartar sugeridas")
        self.btn_discard_suggested.clicked.connect(self._on_discard_suggested)
        suggested_row.addWidget(self.btn_accept_suggested)
        suggested_row.addWidget(self.btn_discard_suggested)
        layout.addLayout(suggested_row)
        self._set_suggested_actions_visible(False)

        buttons_row = QHBoxLayout()
        self.btn_delete = QPushButton("&Eliminar zona")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setAccessibleName("Eliminar la zona seleccionada")
        self.btn_delete.clicked.connect(self._on_delete_zone)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self._on_clear)

        self.btn_save = QPushButton("&Guardar zona")
        self.btn_save.setAccessibleName("Guardar la zona dibujada")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._on_save)

        buttons_row.addWidget(self.btn_delete)
        buttons_row.addWidget(self.btn_cancel)
        buttons_row.addWidget(self.btn_save)
        layout.addLayout(buttons_row)

        return panel

    # ------------------------------------------- entrada desde pestaña 1 --
    def load_session(self, session: AnalysisSession) -> None:
        """
        Carga una sesión ya preparada por la pestaña de carga.

        La sesión trae el frame de referencia y las zonas propuestas, y sabe
        crear su fuente de frames — sea el video limpio o la cámara en
        directo. Las zonas llegan como propuesta: se dibujan punteadas y no
        tocan el disco hasta que el usuario las acepta.
        """
        self._stop_debug_worker()

        rgb = cv2.cvtColor(session.reference_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()

        self._session = session
        self._current_video_id = session.video_id
        self._current_video_path = session.video_path
        self._current_video_fps = session.fps or 30.0
        self._editing_zone_id = None

        self.canvas.set_frame(image)
        self._debug_reference_image = image

        # Se descartan las sugerencias que coincidan con una zona ya
        # guardada: si el usuario ya marcó ese estante a mano, volver a
        # proponerlo solo estorba.
        saved = self.zone_manager.load_zones(self._current_video_id)
        self._suggested_zones = list(session.suggested_zones) if not saved else []
        self.canvas.set_suggested_zones(self._suggested_zones)
        self._set_suggested_actions_visible(bool(self._suggested_zones))

        self.header.set_source_name(session.title)
        self._update_analysis_button()
        self._refresh_zone_list()

        origin = session.describe_origin()
        if self._suggested_zones:
            self._log(
                f"✅ {origin} — {len(self._suggested_zones)} zona(s) sugerida(s) "
                "(línea punteada). Haz click en una para editarla, o acéptalas todas."
            )
        elif saved:
            self._log(f"✅ {origin} — ya tenía {len(saved)} zona(s) guardada(s).")
        else:
            self._log(f"✅ {origin} — dibuja las zonas a mano sobre el frame.")

        if session.is_live:
            self._set_analysis_status(
                "Cámara en directo: el análisis corre hasta que lo detengas."
            )

    def _update_analysis_button(self):
        """El botón cambia de texto según haya o no un análisis corriendo."""
        running = self._debug_worker is not None and self._debug_worker.isRunning()
        if running:
            self.btn_debug.setText("■  Detener análisis")
            self.btn_debug.setAccessibleName("Detener el análisis en curso")
        else:
            live = self._session is not None and self._session.is_live
            self.btn_debug.setText("▶  Analizar en vivo" if live else "▶  Iniciar análisis")
            self.btn_debug.setAccessibleName("Iniciar el análisis")

    def _set_suggested_actions_visible(self, visible: bool) -> None:
        self.btn_accept_suggested.setVisible(visible)
        self.btn_discard_suggested.setVisible(visible)

    def _on_accept_suggested(self):
        """Guarda todas las zonas propuestas, con zone_id definitivo."""
        if not self._suggested_zones or self._current_video_id is None:
            return
        for zone in self._suggested_zones:
            saved = Zone(
                zone_id=self._next_zone_id(),
                video_id=self._current_video_id,
                name=zone.name,
                polygon=zone.polygon,
                zone_type=zone.zone_type,
            )
            self.zone_manager.save_zone(saved)
        self._log(f"✅ {len(self._suggested_zones)} zona(s) sugerida(s) guardadas.")
        self._clear_suggestions()

    def _on_discard_suggested(self):
        self._log(" Sugerencias descartadas — dibuja las zonas a mano.")
        self._clear_suggestions()

    def _clear_suggestions(self):
        self._suggested_zones = []
        self.canvas.set_suggested_zones([])
        self._set_suggested_actions_visible(False)
        self._refresh_zone_list()

    # --------------------------------------------------------- acciones --
    def _on_load_video(self):
        """Carga un video y extrae el frame de referencia (10% de su duración)."""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar video para frame de referencia", str(Path.home()), "Videos (*.mp4 *.avi *.mov *.mkv *.wmv)"
        )
        if not path_str:
            return

        try:
            video_info = load_video(Path(path_str))
        except VideoLoadError as exc:
            self._log(f"❌ {exc}")
            return

        thumb_path = LOGS_DIR / f"{Path(path_str).stem}_ref.jpg"
        try:
            extract_thumbnail(video_info, thumb_path)
            image = QImage(str(thumb_path))
            if image.isNull():
                raise VideoLoadError(f"No se pudo leer la miniatura: {thumb_path}")
            self.canvas.set_frame(image)
            self._editing_zone_id = None
            # normalize_video_id: si se cargó el video crudo (sin limpiar)
            # como referencia, sus zonas igual quedan bajo el mismo
            # "<nombre>_clean" que usará el pipeline real — evita crear una
            # segunda carpeta en data/zones/ para la misma sesión.
            self._current_video_id = normalize_video_id(video_info.path.stem)
            self._current_video_path = video_info.path
            self._current_video_fps = video_info.fps or 30.0
            self._session = AnalysisSession.from_video(
                video_id=self._current_video_id,
                video_path=video_info.path,
                fps=self._current_video_fps,
            )
            self._update_analysis_button()
            # Carga manual: cualquier sugerencia que hubiera quedado en
            # pantalla pertenecía al video anterior.
            self._clear_suggestions()
            self.header.set_source_name(video_info.filename)
            self._refresh_zone_list()
            self._log(f"✅ Frame de referencia cargado: {video_info.filename} "
                      f"({video_info.width}x{video_info.height}) — escala de dibujo lista.")
        except VideoLoadError as exc:
            self._log(f"❌ {exc}")

    def _on_undo(self):
        self.canvas.undo_point()
        self._refresh_zone_list()

    def _on_clear(self):
        self.canvas.clear_points()
        self.name_input.clear()
        self._editing_zone_id = None
        self._editing_suggested_id = None
        self._refresh_zone_list()

    def _on_type_changed(self, _index: int = 0):
        """
        Cambia de rol de zona (góndola/producto vs. personal): actualiza el
        color con el que se dibujan los puntos en construcción y el aviso
        sobre el lienzo, para que sea obvio para cuál de los dos rieles se
        están agregando vértices en este momento.
        """
        zone_type = self.type_combo.currentData()
        color = zone_type_color(zone_type)
        self.type_color_dot.setStyleSheet(f"background-color:{color}; border-radius:6px;")

        if zone_type == "staff":
            self.banner.set_content(
                "Modo de dibujo de ROI's — Personal",
                "Dibuja las áreas donde suele ubicarse el personal de la tienda o "
                "establecimiento (caja, mostrador, bodega...), aparte de las de "
                "góndola. StaffZoneTracker las usa para excluir a los empleados "
                "de las métricas de cliente.",
            )
        else:
            self.banner.set_content(
                "Modo de dibujo de ROI's — Producto",
                "Dibuja o edita cómo están las áreas en donde los clientes "
                "sacan y ponen los productos de las góndolas.",
            )
        self.canvas.set_draw_color(QColor(color))

    def _stop_debug_worker(self):
        """
        Pide interrumpir el debug en curso (si hay uno) sin bloquear la UI
        esperando a que termine — `requestInterruption()` es cooperativo:
        `DetectionPipeline.run()` lo consulta al inicio de cada frame
        (`should_stop`) y corta ahí, pero el hilo real puede tardar hasta
        ese chequeo en salir.

        Para no esperar ese instante (`QThread.wait()` bloquearía la UI),
        se desconectan sus señales — cualquier `frame_processed`/
        `pipeline_finished` que llegue después de esto ya no hace nada — y
        se guarda la referencia en `_retiring_workers` únicamente para que
        Qt no destruya el QThread mientras el hilo real todavía sigue vivo.
        """
        worker = self._debug_worker
        if worker is None:
            return

        worker.requestInterruption()
        for signal, slot in (
            (worker.frame_processed, self._on_debug_frame),
            (worker.pipeline_finished, self._on_debug_finished),
            (worker.pipeline_failed, self._on_debug_failed),
            (worker.progress_updated, self.footer.note_frame_progress),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # ya estaba desconectada

        self._retiring_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._retiring_workers.remove(w) if w in self._retiring_workers else None)

        # El almacén se cierra ya: lo que alcanzó a escribirse queda
        # confirmado, y el worker interrumpido no vuelve a tocarlo (sus
        # señales quedaron desconectadas justo arriba).
        self._close_store()

        self._debug_worker = None
        self._debug_state_machine = None
        self._end_analysis_ui()
        self.btn_debug.setEnabled(True)
        self.btn_load.setEnabled(True)
        self._update_analysis_button()

    def _on_reset_session(self):
        """
        Reinicia el ANÁLISIS, no la sesión: detiene el debug en curso (si
        lo hay, sin esperar a que el video termine) y lo vuelve a correr
        desde el principio sobre el MISMO video que ya está cargado — no
        pide cargar otro ni descarta el video actual. Para analizar un
        video distinto se sigue usando "Cargar video", que ya reemplaza
        la sesión completa sin tener que cerrar y reabrir la app.
        """
        if self._current_video_path is None:
            QMessageBox.information(self, "Sin video", "Carga un video con 'Cargar video' antes de reiniciar.")
            return

        was_running = self._debug_worker is not None and self._debug_worker.isRunning()
        self._stop_debug_worker()

        # `on_run_debug()` no arranca si el lienzo tiene un polígono suelto
        # sin guardar — se descarta acá para que "Reiniciar" siempre pueda
        # relanzar el análisis sin un diálogo de advertencia de por medio.
        self.canvas.clear_points()
        self.name_input.clear()
        self._editing_zone_id = None
        if self._debug_reference_image is not None:
            # Vuelve del frame anotado en vivo al frame de referencia
            # estático (por si el debug interrumpido dejó el lienzo con
            # cajas/keypoints dibujados encima).
            self.canvas.set_frame(self._debug_reference_image)
        self.footer.reset_fps()
        self._refresh_zone_list()

        self._log(
            " Análisis interrumpido — reiniciando sobre el mismo video..."
            if was_running else " Reiniciando análisis sobre el mismo video..."
        )
        self.on_run_debug()

    # ------------------------------------------------------- análisis --
    def on_analysis_button(self):
        """
        Un solo botón para iniciar y detener.

        En directo esto es imprescindible: el stream no se acaba solo, así
        que sin una forma explícita de parar no habría manera de llegar a
        los resultados.
        """
        if self._debug_worker is not None and self._debug_worker.isRunning():
            self.stop_analysis()
        else:
            self.on_run_debug()

    def stop_analysis(self):
        """Detiene el análisis en curso y pasa a los resultados."""
        video_id = self._current_video_id
        self._log(" Deteniendo el análisis…")
        self._set_analysis_status("Deteniendo…")
        self._stop_debug_worker()
        self._restore_reference_frame()
        self._end_analysis_ui()

        summary = self._close_store()
        self._set_analysis_status(
            f"Análisis detenido: {summary['events']} interacción(es) medidas."
        )
        self._log(
            f"■ Análisis detenido — {summary['events']} interacción(es), "
            f"{summary['dwell']} permanencia(s) y {summary['samples']} muestra(s) guardadas."
        )
        if video_id:
            self.analysis_finished.emit(video_id)

    def on_run_debug(self):
        """
        Corre el pipeline completo sobre el video cargado, en un QThread
        (`DetectionPipelineWorker`).

        Hace dos cosas a la vez:

        - **Muestra** el frame anotado (cajas + IDs + pose + zonas +
          estados) sobre el lienzo, reemplazando temporalmente el frame de
          referencia mientras corre.
        - **Persiste** lo que el pipeline produce. El `InProcessPublisher`
          se conecta a un `EventStore`: eventos de interacción, dwell time
          y muestras de posición quedan en SQLite bajo el `video_id` de
          esta sesión, que es lo que después lee el Dashboard.

        Se procesa 1 de cada `ANALYSIS_FRAME_STRIDE` frames para que un
        clip de demo termine en un tiempo razonable en CPU.
        """
        if self._session is None:
            QMessageBox.warning(
                self, "Sin fuente",
                "Carga un video o conecta una cámara en la pestaña 1 antes de analizar.",
            )
            return
        if self.canvas.points:
            QMessageBox.warning(
                self, "Dibujo en curso",
                "Guarda o descarta ('Limpiar puntos') el polígono actual antes de iniciar el análisis.",
            )
            return
        if self._debug_worker is not None and self._debug_worker.isRunning():
            QMessageBox.warning(self, "En curso", "Ya hay un análisis corriendo, espera a que termine.")
            return

        self._debug_zones = self.zone_manager.load_zones(self._current_video_id)
        if not self._debug_zones:
            if self._suggested_zones:
                QMessageBox.warning(
                    self, "Zonas sin confirmar",
                    "Hay zonas sugeridas sin guardar. Acéptalas o dibuja las tuyas "
                    "antes de iniciar el análisis: sin zonas guardadas no se puede "
                    "medir ninguna interacción.",
                )
                return
            self._log(
                f"⚠️ No hay zonas guardadas para '{self._current_video_id}' — el análisis "
                "va a registrar circulación, pero ninguna interacción con góndola."
            )

        # La sesión sabe qué fuente construir: archivo con submuestreo, o
        # cámara en directo. Esta pestaña ya no distingue entre las dos.
        try:
            source = self._session.create_source(frame_stride=ANALYSIS_FRAME_STRIDE)
        except (FileNotFoundError, IOError, ValueError) as exc:
            self._log(f"❌ No se pudo abrir la fuente: {exc}")
            QMessageBox.warning(self, "Sin señal", str(exc))
            return

        tracker = PersonTracker()
        pose_estimator = PoseEstimator()
        # El stride cambia cuántos frames por segundo ve la máquina de
        # estados: sus umbrales están en frames, así que el fps efectivo es
        # el del video dividido por el salto. Sin esto, "1 segundo atascado"
        # pasaría a ser 3 segundos de video real.
        stride = 1 if self._session.is_live else ANALYSIS_FRAME_STRIDE
        effective_fps = max(1.0, self._current_video_fps / stride)
        state_machine = InteractionStateMachine(fps=effective_fps)
        # Se guarda la referencia para que `_on_debug_frame` pueda leer
        # `state_machine.states` y reproducir el mismo coloreado/etiquetado
        # de HOLDING/REACHING que usa `run_pipeline_debug.py` (sección B).
        self._debug_state_machine = state_machine

        publisher = InProcessPublisher()
        # --- Persistencia: sin esto el bus emite al vacío ---
        self._publisher = publisher
        self._store = EventStore()
        self._store.set_session(self._current_video_id, is_demo=False)
        connect_store_to_publisher(self._store, publisher)

        pipeline = DetectionPipeline(tracker, pose_estimator, self.zone_manager, state_machine, publisher)

        # ~10 actualizaciones de imagen por segundo, sin importar el fps
        # real del video — evita saturar la cola de eventos de Qt.
        frame_every_n = max(1, round(effective_fps / 10))

        self._debug_reference_image = self.canvas._image

        self.footer.reset_fps()
        # Total estimado de frames a procesar, para poder dar un porcentaje
        # real en vez de una barra indeterminada.
        # En directo no hay un total conocido: la barra queda indeterminada
        # y el estado cuenta fotogramas en vez de fingir un porcentaje.
        self._analysis_total = (
            0 if self._session.is_live
            else self._estimate_total_frames(self._current_video_path)
        )
        # Rango 0-0 = barra indeterminada, que es lo honesto cuando no se
        # sabe cuánto falta (cámara en directo o contenedor sin metadatos).
        self.analysis_progress.setRange(0, self._analysis_total or 0)
        self.analysis_progress.setValue(0)
        self.analysis_progress.setVisible(True)
        self._set_analysis_status("Analizando…")

        self._debug_worker = DetectionPipelineWorker(pipeline, source, frame_every_n=frame_every_n)
        self._debug_worker.progress_updated.connect(self._on_analysis_progress)
        self._debug_worker.frame_processed.connect(self._on_debug_frame)
        self._debug_worker.pipeline_finished.connect(self._on_debug_finished)
        self._debug_worker.pipeline_failed.connect(self._on_debug_failed)
        self._debug_worker.progress_updated.connect(self.footer.note_frame_progress)

        self.btn_load.setEnabled(False)
        if self._session.is_live:
            self._log(
                f"▶ Analizando en directo desde {self._session.describe_origin()} "
                f"({len(self._debug_zones)} zona(s)). Pulsa 'Detener análisis' para terminar."
            )
        else:
            self._log(
                f"▶ Analizando {self._session.title} "
                f"(1 de cada {ANALYSIS_FRAME_STRIDE} frames, {len(self._debug_zones)} zona(s))..."
            )
        self._debug_worker.start()
        self._update_analysis_button()

    def _on_debug_frame(self, frame, call_count, tracked_people, pose_results):
        """
        Dibuja sobre el frame la MISMA anotación completa que
        `scripts/run_pipeline_debug.py` (zonas + nombre, bounding boxes +
        ID + estado HOLDING/REACHING con color, y pose/keypoints de
        brazos), en vez de solo cajas + polígonos.

        Reutiliza `self._debug_state_machine.states` (poblada por el
        `DetectionPipeline` que corre en el worker) para saber en qué
        estado está cada (track_id, zone_id), igual que hace el script
        de debug por línea de comandos.
        """
        annotated = frame.copy()

        # A. Dibujar zonas + nombre (igual que run_pipeline_debug.py, sección A)
        for zone in self._debug_zones:
            if len(zone.polygon) >= 3:
                pts = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(annotated, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                cv2.putText(
                    annotated,
                    zone.name,
                    (int(zone.polygon[0][0]), int(zone.polygon[0][1]) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

        # B. Dibujar personas trackeadas, ID y estado de interacción
        #    (igual que run_pipeline_debug.py, sección B)
        state_machine = self._debug_state_machine
        for person in tracked_people:
            tid = person.track_id
            x1, y1, x2, y2 = map(int, person.bbox)

            current_state = InteractionState.IDLE
            active_zone = ""
            if state_machine is not None:
                for (t_id, z_id), (state, _) in state_machine.states.items():
                    if t_id == tid and state != InteractionState.IDLE:
                        current_state = state
                        active_zone = z_id
                        break

            if current_state == InteractionState.HOLDING:
                color = (0, 0, 255)  # Rojo para HOLDING
                label = f"ID: {tid} - HOLDING ({active_zone})"
            elif current_state == InteractionState.REACHING:
                color = (0, 255, 255)  # Amarillo para REACHING
                label = f"ID: {tid} - REACHING ({active_zone})"
            else:
                color = (255, 0, 0)  # Azul para IDLE
                label = f"ID: {tid}"

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                annotated,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        # C. Dibujar keypoints y líneas de brazos de la pose
        #    (igual que run_pipeline_debug.py, sección C)
        for pose in pose_results:
            joints = [
                pose.left_shoulder, pose.right_shoulder,
                pose.left_elbow, pose.right_elbow,
                pose.left_wrist, pose.right_wrist,
            ]
            for kp in joints:
                if kp.confidence > 0.3:
                    cv2.circle(annotated, (int(kp.x), int(kp.y)), 5, (0, 255, 255), -1)

            # Brazo izquierdo
            if pose.left_shoulder.confidence > 0.3 and pose.left_elbow.confidence > 0.3:
                cv2.line(
                    annotated,
                    (int(pose.left_shoulder.x), int(pose.left_shoulder.y)),
                    (int(pose.left_elbow.x), int(pose.left_elbow.y)),
                    (255, 128, 0),
                    2,
                )
            if pose.left_elbow.confidence > 0.3 and pose.left_wrist.confidence > 0.3:
                cv2.line(
                    annotated,
                    (int(pose.left_elbow.x), int(pose.left_elbow.y)),
                    (int(pose.left_wrist.x), int(pose.left_wrist.y)),
                    (255, 128, 0),
                    2,
                )
            # Brazo derecho
            if pose.right_shoulder.confidence > 0.3 and pose.right_elbow.confidence > 0.3:
                cv2.line(
                    annotated,
                    (int(pose.right_shoulder.x), int(pose.right_shoulder.y)),
                    (int(pose.right_elbow.x), int(pose.right_elbow.y)),
                    (0, 128, 255),
                    2,
                )
            if pose.right_elbow.confidence > 0.3 and pose.right_wrist.confidence > 0.3:
                cv2.line(
                    annotated,
                    (int(pose.right_elbow.x), int(pose.right_elbow.y)),
                    (int(pose.right_wrist.x), int(pose.right_wrist.y)),
                    (0, 128, 255),
                    2,
                )

        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self.canvas.set_frame(qimg)

    def _estimate_total_frames(self, video_path: Path) -> int:
        """
        Cuántos frames va a procesar el análisis: los del video divididos
        por el salto de submuestreo. Devuelve 0 si el contenedor no reporta
        el total, en cuyo caso la barra queda indeterminada en vez de
        mentir con un porcentaje inventado.
        """
        cap = cv2.VideoCapture(str(video_path))
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        return max(0, total // ANALYSIS_FRAME_STRIDE)

    def _on_analysis_progress(self, frames_done: int):
        if self._analysis_total:
            self.analysis_progress.setValue(min(frames_done, self._analysis_total))
            pct = 100 * frames_done / self._analysis_total
            self._set_analysis_status(
                f"Analizando… {frames_done} de {self._analysis_total} fotogramas ({pct:.0f}%)"
            )
        else:
            live = self._session is not None and self._session.is_live
            prefix = "Analizando en directo…" if live else "Analizando…"
            self._set_analysis_status(f"{prefix} {frames_done} fotogramas procesados")

    def _set_analysis_status(self, message: str):
        """Estado del análisis fuera del log, y anunciable por lector de pantalla."""
        self.analysis_status.setText(message)
        self.analysis_status.setAccessibleDescription(message)

    def _end_analysis_ui(self):
        self.analysis_progress.setVisible(False)

    def _close_store(self) -> dict:
        """
        Cierra el almacén de la corrida actual y devuelve su resumen.

        `flush()` (dentro de `close()`) confirma el último lote pendiente:
        el store hace commit cada N escrituras, así que sin esto los
        eventos finales del video se quedarían sin escribir.
        """
        summary = {"events": 0, "samples": 0, "dwell": 0}
        if self._store is None:
            return summary

        # Desconectar el bus ANTES de cerrar la conexión SQLite: si el
        # pipeline fue interrumpido, su hilo puede seguir vivo un instante
        # y publicar un evento más — que llegaría a un almacén ya cerrado.
        if self._publisher is not None:
            try:
                self._publisher.event_emitted.disconnect(self._store.on_bus_message)
            except (TypeError, RuntimeError):
                pass  # ya estaba desconectado
            self._publisher = None

        try:
            self._store.flush()
            summary = {
                "events": self._store.count_events(self._current_video_id),
                "samples": self._store.count_position_samples(self._current_video_id),
                "dwell": self._store.count_dwell_records(self._current_video_id),
            }
            self._store.close()
        except Exception as exc:  # noqa: BLE001 - no romper la UI por el cierre del almacén
            self._log(f"⚠️ Problema cerrando el almacén de eventos: {exc}")
        finally:
            self._store = None
        return summary

    def _restore_reference_frame(self):
        if self._debug_reference_image is not None:
            self.canvas.set_frame(self._debug_reference_image)
            self.canvas.set_suggested_zones(self._suggested_zones)
            self._refresh_zone_list()

    def _on_debug_finished(self, total_frames: int):
        self.btn_debug.setEnabled(True)
        self.btn_load.setEnabled(True)
        self._update_analysis_button()
        self._debug_state_machine = None
        self._restore_reference_frame()
        self._end_analysis_ui()

        summary = self._close_store()
        self._set_analysis_status(
            f"Análisis terminado: {summary['events']} interacción(es) medidas. "
            "Pasando al tablero de resultados…"
        )
        self._log(
            f"✅ Análisis terminado — {total_frames} frames procesados, "
            f"{summary['events']} interacción(es), {summary['dwell']} permanencia(s) "
            f"y {summary['samples']} muestra(s) de posición guardadas."
        )

        # Paso 2 → 3: MainWindow salta al dashboard con esta sesión.
        if self._current_video_id:
            self.analysis_finished.emit(self._current_video_id)

    def _on_debug_failed(self, message: str):
        self.btn_debug.setEnabled(True)
        self.btn_load.setEnabled(True)
        self._update_analysis_button()
        self._debug_state_machine = None
        self._restore_reference_frame()
        self._end_analysis_ui()
        self._close_store()
        self._set_analysis_status("El análisis falló. Revisa el historial de mensajes.")
        self._log(f"❌ Falló el análisis: {message}")

    def _on_save(self):
        """Guarda la zona dibujada con el esquema `Zone` vía ZoneManager."""
        if self.canvas._image is None or self._current_video_id is None:
            QMessageBox.warning(self, "Sin frame", "Carga primero un video con el frame de referencia.")
            return
        if len(self.canvas.points) < 3:
            QMessageBox.warning(self, "Polígono incompleto", "Se necesitan al menos 3 puntos.")
            return
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Sin nombre", "Escribe un nombre para la zona.")
            return

        # Si se venía editando una zona guardada (`_on_zone_selected` cargó
        # sus puntos en el lienzo), se reusa el mismo zone_id — save_zone()
        # sobreescribe ese JSON en vez de crear uno nuevo. El heatmap del
        # Dashboard, que relee las zonas del disco en cada refresco, queda
        # así con los puntos actualizados sin ningún paso extra.
        is_edit = self._editing_zone_id is not None
        zone_id = self._editing_zone_id or self._next_zone_id()
        polygon = [(round(x, 2), round(y, 2)) for (x, y) in self.canvas.points]
        zone_type = self.type_combo.currentData()
        zone = Zone(zone_id=zone_id, video_id=self._current_video_id, name=name, polygon=polygon, zone_type=zone_type)
        self.zone_manager.save_zone(zone)
        verb = "actualizada" if is_edit else "guardada"
        self._log(f"✅ Zona {verb}: {zone_id} — {name} ({len(polygon)} vértices, tipo={zone_type}) [{self._current_video_id}]")

        # Si lo que se acaba de guardar venía de una sugerencia, esa
        # propuesta ya está resuelta: sale de la lista de pendientes.
        if self._editing_suggested_id is not None:
            self._suggested_zones = [
                z for z in self._suggested_zones if z.zone_id != self._editing_suggested_id
            ]
            self._editing_suggested_id = None
            self.canvas.set_suggested_zones(self._suggested_zones)
            self._set_suggested_actions_visible(bool(self._suggested_zones))

        self.name_input.clear()
        self.canvas.clear_points()
        self._editing_zone_id = None
        self._refresh_zone_list()

    def _next_zone_id(self) -> str:
        """Genera el siguiente zone_id libre (zone_1, zone_2, ...) para el video actual, sin pisar los existentes."""
        existing = set()
        video_dir = self.zone_manager.storage_path / self._current_video_id
        if video_dir.exists():
            for f in video_dir.glob("*.json"):
                existing.add(f.stem)
        n = 1
        while f"zone_{n}" in existing:
            n += 1
        return f"zone_{n}"

    # ----------------------------------------------------------- helpers --
    def _refresh_zone_list(self):
        """
        Repuebla la lista de "Regiones de interés activas".

        Muestra primero (si existen) los puntos que se están dibujando
        ahora mismo, sin guardar todavía, y luego las zonas ya
        guardadas para el video actual.
        """
        self.zone_list.clear()
        self._zones = {}

        if self.canvas.points:
            status = f"Editando {self._editing_zone_id}" if self._editing_zone_id else "Dibujando"
            self._add_zone_row(
                name=self.name_input.text().strip() or "(sin nombre aún)",
                nodes=len(self.canvas.points),
                area_px=0.0,
                zone_type=self.type_combo.currentData() if self._editing_zone_id else "—",
                status=status,
                zone_id=None,  # fila "en vivo": clickearla no debe recargar la versión guardada
            )

        # Sugerencias pendientes: se listan antes que las guardadas, con su
        # estado explícito, para que nadie las confunda con zonas reales.
        for zone in self._suggested_zones:
            self._add_zone_row(
                name=zone.name,
                nodes=len(zone.polygon),
                area_px=_polygon_area_px(zone.polygon),
                zone_type=zone.zone_type,
                status="Sugerida (sin guardar)",
                zone_id=zone.zone_id,
            )

        if self._current_video_id is None:
            return

        self._zones = {z.zone_id: z for z in self.zone_manager.load_zones(self._current_video_id)}
        for zone_id, zone in self._zones.items():
            if zone_id == self._editing_zone_id:
                continue  # ya se muestra arriba, con los puntos en vivo del lienzo
            self._add_zone_row(
                name=zone.name,
                nodes=len(zone.polygon),
                area_px=_polygon_area_px(zone.polygon),
                zone_type=zone.zone_type,
                status="Válida",
                zone_id=zone_id,
            )

    def _add_zone_row(self, name: str, nodes: int, area_px: float, zone_type: str, status: str, zone_id: Optional[str]):
        """Agrega una fila con estilo de tarjeta al QListWidget de zonas."""
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(1)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        color = zone_type_color(zone_type) if zone_type in ("product", "staff") else None
        if color:
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background-color:{color}; border-radius:4px;")
            name_row.addWidget(dot)
        name_label = QLabel(name)
        name_label.setObjectName("sectionTitle")
        name_row.addWidget(name_label, stretch=1)
        row_layout.addLayout(name_row)

        area_text = f"{area_px:,.0f} px²" if area_px > 0 else "--"
        detail_label = QLabel(
            f"Nodos: {nodes}   Área: {area_text}   Tipo: {zone_type}   Estado: {status}"
        )
        detail_label.setObjectName("mutedText")
        detail_label.setWordWrap(True)
        row_layout.addWidget(detail_label)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        item.setData(Qt.UserRole, zone_id)
        self.zone_list.addItem(item)
        self.zone_list.setItemWidget(item, row)

    def _on_delete_zone(self):
        items = self.zone_list.selectedItems()
        zone_id = items[0].data(Qt.UserRole) if items else None
        if zone_id is None:
            # La fila de "edición en vivo" siempre tiene zone_id=None en el
            # QListWidgetItem (ver _refresh_zone_list) — si se está editando
            # una zona guardada, esta es la que realmente se quiere borrar.
            zone_id = self._editing_zone_id
        if zone_id is None:
            QMessageBox.information(self, "Sin selección", "Selecciona una zona guardada de la lista para eliminarla.")
            return
        zone = self._zones.get(zone_id)
        name = zone.name if zone else zone_id
        confirm = QMessageBox.question(
            self, "Eliminar zona",
            f"¿Eliminar la zona \"{name}\"? Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.zone_manager.delete_zone(self._current_video_id, zone_id)
        self._log(f" Zona eliminada: {zone_id} — {name}")
        self.canvas.existing_zone = None
        if self._editing_zone_id == zone_id:
            # Se borró justo la zona que estaba en edición: no queda nada
            # válido que sobreescribir, así que se descarta el borrador.
            self.canvas.clear_points()
            self.name_input.clear()
            self._editing_zone_id = None
        self.canvas.update()
        self._refresh_zone_list()

    def _on_zone_selected(self):
        """
        Selecciona una zona guardada de la lista para **editarla**: sus
        puntos se cargan en el lienzo (agregables/editables como cualquier
        polígono en construcción) y "Guardar zona" sobreescribe el mismo
        JSON en vez de crear uno nuevo (ver `_on_save`).
        """
        items = self.zone_list.selectedItems()
        if not items:
            return
        zone_id = items[0].data(Qt.UserRole)
        if zone_id is None:
            return  # es la fila "en construcción/edición", no una zona guardada distinta

        # Una sugerencia se "edita" pasándola al lienzo como polígono en
        # construcción: al guardarla recibe un zone_id definitivo y deja de
        # ser una propuesta (por eso _editing_zone_id queda en None).
        if zone_id.startswith(SUGGESTED_ID_PREFIX):
            suggested = next((z for z in self._suggested_zones if z.zone_id == zone_id), None)
            if suggested is None or not self.canvas.has_frame():
                return
            self._editing_zone_id = None
            self._editing_suggested_id = zone_id
            self.canvas.existing_zone = None
            self.canvas.points = list(suggested.polygon)
            self.name_input.setText(suggested.name)
            type_index = self.type_combo.findData(suggested.zone_type)
            if type_index >= 0:
                self.type_combo.setCurrentIndex(type_index)
            self.canvas.update()
            QTimer.singleShot(0, self._refresh_zone_list)
            self._log(
                f" Editando la sugerencia '{suggested.name}' — ajusta los puntos "
                "y presiona 'Guardar zona' para confirmarla."
            )
            return

        zone = self._zones.get(zone_id)
        if not zone or not self.canvas.has_frame():
            return

        self._editing_zone_id = zone_id
        self.canvas.existing_zone = None
        self.canvas.points = list(zone.polygon)
        self.name_input.setText(zone.name)
        type_index = self.type_combo.findData(zone.zone_type)
        if type_index >= 0:
            self.type_combo.setCurrentIndex(type_index)  # dispara _on_type_changed (color/banner)
        self.canvas.update()
        # OJO: NO reconstruir self.zone_list (clear() + addItem()) acá
        # mismo — este método corre dentro de la propia señal
        # `itemSelectionChanged` del widget, y reentrar sobre él desde su
        # propio handler (borrar/re-agregar items mientras Qt todavía está
        # despachando esa señal) es el crash nativo sin traceback que se
        # veía al eliminar una zona justo después de seleccionarla.
        # `singleShot(0, ...)` difiere la reconstrucción al siguiente tick
        # del event loop, ya con la señal actual completamente despachada.
        QTimer.singleShot(0, self._refresh_zone_list)
        self._log(f" Editando zona {zone_id} — modifica los puntos y presiona 'Guardar zona'.")

    def _log(self, message: str):
        self.log_area.append(message)