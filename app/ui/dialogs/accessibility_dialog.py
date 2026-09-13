"""
Diálogo de accesibilidad y apariencia.

Los cambios se aplican **en vivo**: al mover el tema o el tamaño de letra,
la aplicación entera se repinta de inmediato y el usuario ve el resultado
antes de aceptar. Un diálogo de accesibilidad que obliga a reiniciar para
comprobar si el texto ya se lee es, precisamente, inaccesible.

Si se cancela, se restauran los valores con los que se abrió.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import FONT_SCALES, THEMES, contrast_ratio


class AccessibilityDialog(QDialog):
    """Tema, tamaño de fuente y acceso al tour."""

    # (clave de tema, clave de escala de fuente) — se emite en cada cambio,
    # para que la ventana principal repinte al instante.
    preview_requested = Signal(str, str)
    tour_requested = Signal()

    def __init__(self, current_theme: str, current_scale: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accesibilidad y apariencia")
        self.setMinimumWidth(560)

        self._initial_theme = current_theme
        self._initial_scale = current_scale
        self._theme = current_theme
        self._scale = current_scale

        # El contenido va dentro de un área con scroll y los botones quedan
        # fijos abajo. Es un diálogo de accesibilidad: con la letra al 150%
        # su contenido no cabe en una pantalla de portátil, y recortar
        # justo las explicaciones de accesibilidad sería lo peor que puede
        # hacer esta ventana.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)

        layout.addWidget(self._build_theme_group(current_theme))
        layout.addWidget(self._build_font_group(current_scale))
        layout.addWidget(self._build_tour_group())

        hint = QLabel(
            "Los cambios se aplican al instante. Si cancelas, se restaura "
            "como estaba."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        button_row = QWidget()
        button_layout = QVBoxLayout(button_row)
        button_layout.setContentsMargins(18, 8, 18, 14)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self._on_cancel)
        button_layout.addWidget(buttons)
        outer.addWidget(button_row)

        self._fit_to_screen(content)

    def _fit_to_screen(self, content: QWidget) -> None:
        """
        Abre el diálogo con el alto que pide su contenido, sin pasarse del
        alto de la pantalla. Si no cabe, el scroll se encarga.
        """
        screen = QGuiApplication.primaryScreen()
        max_h = int(screen.availableGeometry().height() * 0.85) if screen else 900
        content.adjustSize()
        wanted = content.sizeHint().height() + 80  # + fila de botones
        self.resize(self.minimumWidth(), min(wanted, max_h))

    # ------------------------------------------------------------- grupos --
    def _build_theme_group(self, current: str) -> QGroupBox:
        group = QGroupBox("Tema de color")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._theme_buttons = QButtonGroup(self)
        descriptions = {
            "dark": "Para trabajar en interiores con poca luz.",
            "light": "Para salas iluminadas y proyección.",
            "high_contrast": "Contraste máximo (AAA) para baja visión.",
        }

        for key, palette in THEMES.items():
            radio = QRadioButton(palette.name)
            radio.setChecked(key == current)
            # El nombre accesible incluye la descripción: un lector de
            # pantalla anuncia para qué sirve el tema, no solo su nombre.
            radio.setAccessibleName(f"Tema {palette.name}. {descriptions.get(key, '')}")
            radio.toggled.connect(lambda checked, k=key: checked and self._set_theme(k))
            self._theme_buttons.addButton(radio)
            layout.addWidget(radio)

            note = QLabel(descriptions.get(key, ""))
            note.setObjectName("mutedText")
            note.setIndent(24)
            note.setWordWrap(True)
            layout.addWidget(note)

        # Dato verificable, no una promesa de marketing: el contraste real
        # del texto principal del tema de alto contraste.
        hc = THEMES["high_contrast"]
        ratio = contrast_ratio(hc.TEXT_PRIMARY, hc.BG_APP)
        detail = QLabel(f"El tema de alto contraste alcanza {ratio:.0f}:1 en el texto principal.")
        detail.setObjectName("mutedText")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        return group

    def _build_font_group(self, current: str) -> QGroupBox:
        group = QGroupBox("Tamaño de la letra")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._font_buttons = QButtonGroup(self)
        for key, (_factor, label) in FONT_SCALES.items():
            radio = QRadioButton(label)
            radio.setChecked(key == current)
            radio.setAccessibleName(f"Tamaño de letra {label}")
            radio.toggled.connect(lambda checked, k=key: checked and self._set_scale(k))
            self._font_buttons.addButton(radio)
            layout.addWidget(radio)

        note = QLabel(
            "Los botones y campos crecen junto con la letra, para que el "
            "área en la que se puede hacer click no se quede pequeña."
        )
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        return group

    def _build_tour_group(self) -> QGroupBox:
        group = QGroupBox("Ayuda")
        layout = QHBoxLayout(group)

        label = QLabel("¿Primera vez con la aplicación?")
        layout.addWidget(label, stretch=1)

        button = QPushButton("Ver el tour")
        button.setAccessibleName("Ver el tour guiado de la aplicación")
        button.clicked.connect(self._on_tour)
        layout.addWidget(button)
        return group

    # ------------------------------------------------------------ acciones --
    def _set_theme(self, key: str):
        self._theme = key
        self.preview_requested.emit(self._theme, self._scale)

    def _set_scale(self, key: str):
        self._scale = key
        self.preview_requested.emit(self._theme, self._scale)

    def _on_tour(self):
        self.accept()
        self.tour_requested.emit()

    def _on_cancel(self):
        # Restaurar lo que había antes de abrir el diálogo.
        self.preview_requested.emit(self._initial_theme, self._initial_scale)
        self.reject()

    def selection(self) -> tuple:
        """(clave de tema, clave de escala) elegidas."""
        return self._theme, self._scale
