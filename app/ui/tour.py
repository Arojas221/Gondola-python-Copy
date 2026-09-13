"""
Tour guiado de la aplicación (primer arranque y repetible bajo demanda).

Cómo funciona: `TourOverlay` es un widget hijo de la ventana principal que
la cubre entera. Pinta un velo semitransparente y **recorta un hueco** sobre
el widget del que habla cada paso, de modo que el usuario ve la interfaz
real resaltada, no una captura ni un texto suelto. Al lado del hueco se
dibuja una tarjeta con el título, la explicación y los controles.

Decisiones que importan:

- **El overlay no bloquea con un diálogo modal.** Es un widget que se
  redimensiona con la ventana y se puede cerrar con Escape en cualquier
  momento. Un tour del que no se puede salir es una trampa, no una ayuda.
- **Cada paso apunta a un widget vivo**, resuelto por una función en el
  momento de mostrarlo. Si un paso apunta a algo que todavía no existe (una
  pestaña no construida, un botón oculto), el paso se salta solo en vez de
  romperse.
- **Es navegable con teclado**: flechas y Enter avanzan, Escape sale, y el
  foco entra en la tarjeta al abrirse para que un lector de pantalla lea el
  texto del paso.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import Colors

# Anchos de la tarjeta. Los pasos sin elemento resaltado (bienvenida,
# cierre) van centrados y sin nada que esquivar, así que se les da más
# ancho: son los que llevan más texto y quedaban innecesariamente
# estrechos.
CARD_WIDTH = 430
CARD_WIDTH_CENTERED = 560
CARD_MARGIN = 18          # separación entre el hueco resaltado y la tarjeta
CARD_SCREEN_MARGIN = 24   # aire mínimo entre la tarjeta y el borde de la ventana
SPOTLIGHT_PADDING = 8     # aire alrededor del widget resaltado
SPOTLIGHT_RADIUS = 8


@dataclass
class TourStep:
    """
    Un paso del tour.

    `target` es una función que devuelve el widget a resaltar (o None para
    un paso sin resaltado, centrado en pantalla). Es una función y no el
    widget directamente porque los widgets de una pestaña pueden no existir
    todavía cuando se define el tour.

    `before` se ejecuta antes de mostrar el paso — típicamente para cambiar
    de pestaña, de modo que el elemento resaltado esté visible.
    """
    title: str
    body: str
    target: Optional[Callable[[], Optional[QWidget]]] = None
    before: Optional[Callable[[], None]] = None


class TourOverlay(QWidget):
    """Capa de resaltado + tarjeta de paso, sobre la ventana principal."""

    finished = Signal()

    def __init__(self, host: QWidget, steps: List[TourStep], parent=None):
        super().__init__(parent or host)
        self.host = host
        self.steps = steps
        self.index = 0
        self._target_rect = QRect()

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)
        # Recibe todos los clicks: durante el tour, pulsar "detrás" del velo
        # no debe activar controles de la aplicación por accidente.
        self.setAttribute(Qt.WA_NoMousePropagation, True)

        self._build_card()
        host.installEventFilter(self)

    # ------------------------------------------------------------ tarjeta --
    def _build_card(self):
        self.card = QWidget(self)
        self.card.setObjectName("panel")

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        self.step_counter = QLabel()
        self.step_counter.setObjectName("fieldLabel")
        layout.addWidget(self.step_counter)

        self.title_label = QLabel()
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        # El texto va dentro de un área con scroll: con la letra al 150%,
        # o en una ventana baja, los pasos largos no caben y antes se
        # cortaban sin ninguna forma de leer el resto.
        self.body_label = QLabel()
        self.body_label.setWordWrap(True)
        self.body_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.body_scroll = QScrollArea()
        self.body_scroll.setWidget(self.body_label)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body_scroll.setStyleSheet("background: transparent;")
        layout.addWidget(self.body_scroll, stretch=1)

        self.hint_label = QLabel(
            "← → cambian de paso · ↑ ↓ desplazan el texto · Esc sale"
        )
        self.hint_label.setObjectName("mutedText")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.btn_skip = QPushButton("Saltar tour")
        self.btn_skip.setAccessibleName("Saltar el tour de la aplicación")
        self.btn_skip.clicked.connect(self.finish)
        buttons.addWidget(self.btn_skip)

        buttons.addStretch()

        self.btn_prev = QPushButton("Anterior")
        self.btn_prev.setAccessibleName("Paso anterior del tour")
        self.btn_prev.clicked.connect(self.previous_step)
        buttons.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Siguiente")
        self.btn_next.setObjectName("primary")
        self.btn_next.setAccessibleName("Siguiente paso del tour")
        self.btn_next.clicked.connect(self.next_step)
        buttons.addWidget(self.btn_next)

        layout.addLayout(buttons)

    # -------------------------------------------------------------- ciclo --
    def start(self):
        self.index = 0
        self.resize(self.host.size())
        self.show()
        self.raise_()
        self._show_step()
        self.btn_next.setFocus()

    def next_step(self):
        if self.index >= len(self.steps) - 1:
            self.finish()
            return
        self.index += 1
        self._show_step()

    def previous_step(self):
        if self.index > 0:
            self.index -= 1
            self._show_step()

    def finish(self):
        self.host.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def _show_step(self):
        step = self.steps[self.index]
        if step.before:
            step.before()

        self.step_counter.setText(f"PASO {self.index + 1} DE {len(self.steps)}")
        self.title_label.setText(step.title)
        self.body_label.setText(step.body)
        self.btn_prev.setEnabled(self.index > 0)
        self.btn_next.setText("Entendido" if self.index == len(self.steps) - 1 else "Siguiente")

        # Nombre accesible del paso completo: un lector de pantalla anuncia
        # título y cuerpo al llegar aquí, sin tener que recorrer la tarjeta.
        self.card.setAccessibleName(f"{step.title}. {step.body}")

        self._target_rect = self._resolve_target(step)
        self._place_card()
        self.body_scroll.verticalScrollBar().setValue(0)
        self.update()

    def _resolve_target(self, step: TourStep) -> QRect:
        """Rectángulo del widget a resaltar, en coordenadas del overlay."""
        if step.target is None:
            return QRect()
        try:
            widget = step.target()
        except Exception:  # noqa: BLE001 - un paso roto no debe tumbar el tour
            return QRect()
        if widget is None or not widget.isVisible():
            return QRect()

        top_left = widget.mapTo(self.host, QPoint(0, 0))
        rect = QRect(top_left, widget.size())
        return rect.adjusted(-SPOTLIGHT_PADDING, -SPOTLIGHT_PADDING,
                             SPOTLIGHT_PADDING, SPOTLIGHT_PADDING)

    def _size_card(self):
        """
        Ajusta la tarjeta al espacio disponible.

        El ancho y el alto máximos salen del tamaño de la ventana, no de
        constantes fijas: con la letra grande o en una pantalla baja, una
        tarjeta de tamaño fijo se sale por abajo. Lo que sobra se resuelve
        con el scroll del texto, nunca recortándolo.
        """
        area = self.rect()
        centered = self._target_rect.isNull()
        preferred = CARD_WIDTH_CENTERED if centered else CARD_WIDTH
        card_w = min(preferred, max(280, area.width() - 2 * CARD_SCREEN_MARGIN))
        self.card.setFixedWidth(card_w)

        # Alto máximo de la tarjeta completa.
        max_card_h = max(240, area.height() - 2 * CARD_SCREEN_MARGIN)
        if not centered:
            # Con un elemento resaltado, la tarjeta debe caber en el hueco
            # que queda por encima o por debajo de él.
            above = self._target_rect.top() - CARD_MARGIN - CARD_SCREEN_MARGIN
            below = area.height() - self._target_rect.bottom() - CARD_MARGIN - CARD_SCREEN_MARGIN
            available = max(above, below)
            if available >= 240:
                max_card_h = min(max_card_h, available)

        # Alto que pediría el texto completo con este ancho. `heightForWidth`
        # es lo correcto en un QLabel con ajuste de línea: fijarle el ancho
        # pelearía con el QScrollArea, que lo redimensiona él mismo.
        text_width = card_w - 36 - 14   # márgenes de la tarjeta + barra de scroll
        natural_body = max(60, self.body_label.heightForWidth(text_width))

        # Todo lo que no es el texto: contador, título, pista de teclado,
        # botones, márgenes y espaciado del layout.
        layout = self.card.layout()
        chrome = layout.contentsMargins().top() + layout.contentsMargins().bottom()
        chrome += layout.spacing() * 4
        chrome += self.step_counter.sizeHint().height()
        chrome += self.title_label.heightForWidth(text_width)
        chrome += self.hint_label.heightForWidth(text_width)
        chrome += self.btn_next.sizeHint().height()

        body_h = max(60, min(natural_body, max_card_h - chrome))
        self.body_scroll.setFixedHeight(body_h)

        self.card.setMaximumHeight(max_card_h)
        self.card.adjustSize()

    def _place_card(self):
        """
        Coloca la tarjeta sin taparse con el hueco resaltado.

        Prueba debajo, arriba, a la derecha y a la izquierda del objetivo, y
        se queda con la primera posición que quepa entera en la ventana. Si
        no hay objetivo (o ninguna posición cabe), va al centro.
        """
        self._size_card()
        card_w, card_h = self.card.width(), self.card.height()
        area = self.rect()

        if self._target_rect.isNull():
            self.card.move(area.center().x() - card_w // 2, area.center().y() - card_h // 2)
            return

        t = self._target_rect
        candidates = [
            QPoint(min(max(t.left(), 12), area.width() - card_w - 12), t.bottom() + CARD_MARGIN),
            QPoint(min(max(t.left(), 12), area.width() - card_w - 12), t.top() - CARD_MARGIN - card_h),
            QPoint(t.right() + CARD_MARGIN, min(max(t.top(), 12), area.height() - card_h - 12)),
            QPoint(t.left() - CARD_MARGIN - card_w, min(max(t.top(), 12), area.height() - card_h - 12)),
        ]
        for point in candidates:
            if area.contains(QRect(point, self.card.size())):
                self.card.move(point)
                return
        # Ninguna posición junto al objetivo cabe: al centro, pero acotado
        # a la ventana para que no se salga por ningún borde.
        x = min(max(area.center().x() - card_w // 2, CARD_SCREEN_MARGIN),
                max(CARD_SCREEN_MARGIN, area.width() - card_w - CARD_SCREEN_MARGIN))
        y = min(max(area.center().y() - card_h // 2, CARD_SCREEN_MARGIN),
                max(CARD_SCREEN_MARGIN, area.height() - card_h - CARD_SCREEN_MARGIN))
        self.card.move(x, y)

    # -------------------------------------------------------------- pintado --
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Velo con un hueco recortado sobre el objetivo: se construye como
        # un path del área completa menos el rectángulo redondeado del
        # objetivo, y se rellena de una sola pasada.
        veil = QPainterPath()
        veil.addRect(self.rect())
        if not self._target_rect.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self._target_rect, SPOTLIGHT_RADIUS, SPOTLIGHT_RADIUS)
            veil = veil.subtracted(hole)

        painter.fillPath(veil, QColor(0, 0, 0, 190))

        if not self._target_rect.isNull():
            painter.setPen(QPen(QColor(Colors.ACCENT), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self._target_rect, SPOTLIGHT_RADIUS, SPOTLIGHT_RADIUS)

        painter.end()

    # -------------------------------------------------------------- eventos --
    def keyPressEvent(self, event):
        """
        Izquierda/derecha cambian de paso; arriba/abajo desplazan el texto.

        Separarlos importa: si las flechas verticales también avanzaran, un
        paso con texto largo no se podría terminar de leer con el teclado.
        """
        key = event.key()
        bar = self.body_scroll.verticalScrollBar()

        if key == Qt.Key_Escape:
            self.finish()
        elif key in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next_step()
        elif key == Qt.Key_Left:
            self.previous_step()
        elif key == Qt.Key_Down:
            bar.setValue(bar.value() + bar.singleStep() * 3)
        elif key == Qt.Key_Up:
            bar.setValue(bar.value() - bar.singleStep() * 3)
        elif key == Qt.Key_PageDown:
            bar.setValue(bar.value() + bar.pageStep())
        elif key == Qt.Key_PageUp:
            bar.setValue(bar.value() - bar.pageStep())
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """La rueda desplaza el texto del paso, no avanza el tour."""
        bar = self.body_scroll.verticalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y())
        event.accept()

    def relayout(self):
        """
        Recalcula tamaño y posición.

        La ventana principal lo llama tras cambiar el tema o el tamaño de
        letra: el hueco resaltado está en coordenadas ya calculadas y, sin
        esto, quedaría señalando donde el widget estaba antes.
        """
        self.resize(self.host.size())
        self._target_rect = self._resolve_target(self.steps[self.index])
        self._place_card()
        self.update()

    def eventFilter(self, watched, event):
        """Sigue el tamaño de la ventana: el velo debe cubrirla siempre."""
        if watched is self.host and event.type() == QEvent.Resize:
            self.relayout()
        return False

    def mousePressEvent(self, event):
        """Un click fuera de la tarjeta avanza, como en cualquier tour."""
        if not self.card.geometry().contains(event.position().toPoint()):
            self.next_step()


def build_default_tour(window) -> List[TourStep]:
    """
    Guion del tour sobre la ventana principal.

    Está escrito en lenguaje de negocio, no de código: quien lo lee la
    primera vez no sabe qué es un PositionSample ni una máquina de estados.
    """
    tabs = window.tabs
    ingest = window.ingest_tab
    zones = window.zone_tab
    dashboard = window.dashboard_tab

    def go(index: int):
        return lambda: tabs.setCurrentIndex(index)

    return [
        TourStep(
            title="Bienvenido a Scapder Vision",
            body=(
                "Esta aplicación mide qué hacen los clientes frente a la góndola: "
                "qué productos toman, cuáles devuelven, cuánto tiempo se detienen "
                "y por dónde circulan. Todo se procesa en este equipo, sin enviar "
                "nada a internet.\n\n"
                "El recorrido son tres pasos y dura menos de un minuto."
            ),
        ),
        TourStep(
            title="Las tres pestañas son un solo camino",
            body=(
                "Se avanza de izquierda a derecha: primero se carga el video, "
                "después se marcan las zonas de góndola, y al analizar se llega "
                "al tablero de resultados. La aplicación te va llevando sola de "
                "una pestaña a la siguiente."
            ),
            target=lambda: tabs.tabBar(),
        ),
        TourStep(
            title="1. Carga tu video",
            body=(
                "Elige un archivo de video de la cámara de la tienda. La "
                "aplicación lo revisa, descarta los tramos en negro o congelados "
                "y guarda la equivalencia con la grabación original, para que "
                "después cada evento se pueda ubicar en el minuto exacto."
            ),
            before=go(0),
            target=lambda: ingest.btn_connect,
        ),
        TourStep(
            title="La lista de videos analizados",
            body=(
                "Aquí aparecen los videos cargados con su duración y su estado. "
                "Al seleccionar uno verás su vista previa y sus datos técnicos; "
                "los botones de limpieza actúan sobre lo que tengas seleccionado."
            ),
            before=go(0),
            target=lambda: ingest.list_widget,
        ),
        TourStep(
            title="2. Revisa las zonas de góndola",
            body=(
                "Al terminar la limpieza, la aplicación elige un fotograma nítido "
                "y te propone sola las zonas de estantería, dibujadas con línea "
                "punteada. Puedes aceptarlas, corregirlas haciendo click en una, "
                "o dibujar las tuyas sobre la imagen."
            ),
            before=go(1),
            target=lambda: zones.canvas,
        ),
        TourStep(
            title="Cada zona tiene un rol",
            body=(
                "Una zona de góndola mide el interés de los clientes. Una zona de "
                "personal sirve para lo contrario: marcar dónde se para un "
                "empleado, para que no cuente como cliente en las métricas ni "
                "ensucie el mapa de calor."
            ),
            before=go(1),
            target=lambda: zones.type_combo,
        ),
        TourStep(
            title="Inicia el análisis",
            body=(
                "Este botón recorre el video completo detectando personas, "
                "siguiéndolas y midiendo sus interacciones con cada zona. Verás "
                "el avance sobre la propia imagen. Al terminar, la aplicación "
                "salta al tablero con los resultados."
            ),
            before=go(1),
            target=lambda: zones.btn_debug,
        ),
        TourStep(
            title="3. Lee los resultados",
            body=(
                "El tablero muestra cuántas interacciones hubo, en qué zonas, "
                "cuánto tiempo se detuvo la gente y por dónde circuló. Si "
                "todavía no analizaste nada, puedes cargar una sesión de "
                "demostración para ver cómo se ve con datos."
            ),
            before=go(2),
            target=lambda: dashboard.session_combo,
        ),
        TourStep(
            title="Accesibilidad y ayuda",
            body=(
                "Desde estos botones puedes repetir este tour cuando quieras y "
                "ajustar el tamaño de la letra o el tema de color: hay un tema "
                "claro para salas iluminadas y uno de alto contraste para baja "
                "visión.\n\n"
                "Listo. Empieza cargando un video en la primera pestaña."
            ),
            target=lambda: window.corner_widget,
        ),
    ]
