from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class VideoInfoPanel(QFrame):
    """Panel reutilizable: nombre de video + fecha + toggle de vista."""

    # Emite "events" o "gallery" según qué botón quede activo.
    view_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._build_ui()
        self._set_active_view("events")  # vista por defecto al arrancar

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.name_label = QLabel("Nombre video")
        self.name_label.setObjectName("sectionTitle")
        layout.addWidget(self.name_label)

        self.date_label = QLabel("Fecha de análisis")
        self.date_label.setObjectName("mutedText")
        layout.addWidget(self.date_label)

        # --- Toggle de vista (dos botones, uno activo a la vez) ---
        toggle_row = QHBoxLayout()

        self.btn_events = QPushButton("\U0001F4E1")   # ícono "red / compartir"
        self.btn_events.setToolTip("Ver eventos")
        self.btn_events.clicked.connect(lambda: self._set_active_view("events"))

        self.btn_gallery = QPushButton("\U0001F5BC")  # ícono "imagen"
        self.btn_gallery.setToolTip("Ver galería")
        self.btn_gallery.clicked.connect(lambda: self._set_active_view("gallery"))

        toggle_row.addWidget(self.btn_events)
        toggle_row.addWidget(self.btn_gallery)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # --- Área de contenido, reemplazable desde afuera ---
        self.content_area = QWidget()
        self._content_layout = QVBoxLayout(self.content_area)
        self._content_layout.setContentsMargins(0, 8, 0, 0)

        self.placeholder_label = QLabel(
            "Aquí se mostrarán los datos generados para su análisis posterior"
        )
        self.placeholder_label.setObjectName("mutedText")
        self.placeholder_label.setWordWrap(True)
        self._content_layout.addWidget(self.placeholder_label)
        self._content_layout.addStretch()

        layout.addWidget(self.content_area, stretch=1)

    # ------------------------------------------------------------ API --
    def set_video_info(self, name: str, date: str = ""):
        """Actualiza el nombre y la fecha mostrados en el panel."""
        self.name_label.setText(name)
        self.date_label.setText(date)

    def set_content_widget(self, widget: QWidget):

        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._content_layout.addWidget(widget)

    # ------------------------------------------------------------- interno --
    def _set_active_view(self, view: str):
        is_events = view == "events"

        # Reutiliza el mismo par de estilos "toggleActive"/"toggleInactive"
        # que ya define theme.py para el selector "IP CAMERA / SUBIR ARCHIVO".
        self.btn_events.setObjectName("toggleActive" if is_events else "toggleInactive")
        self.btn_gallery.setObjectName("toggleInactive" if is_events else "toggleActive")

        # Qt no vuelve a leer el QSS solo porque cambiamos objectName en
        # caliente; hay que forzarlo con unpolish/polish en cada botón.
        for btn in (self.btn_events, self.btn_gallery):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.view_changed.emit(view)