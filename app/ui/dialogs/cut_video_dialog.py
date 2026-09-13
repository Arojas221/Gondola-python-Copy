from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.core.ingestion.video_loader import VideoInfo, VideoLoadError, extract_thumbnail
from app.utils import config


def _format_seconds(seconds: float) -> str:
    """Convierte segundos a texto "mm:ss" para mostrar en las etiquetas."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes:02d}:{secs:02d}"


class CutVideoDialog(QDialog):
    """Modal para elegir un rango de tiempo sobre un video ya cargado (solo UI)."""

    # Se emite al apretar "Aplicar", con el rango elegido en segundos.
    # NO significa que el recorte ya se hizo — ver docstring del módulo.
    range_selected = Signal(float, float)

    def __init__(self, video_info: VideoInfo, parent=None):
        super().__init__(parent)
        self.video_info = video_info
        self.setWindowTitle("Cortar Video")
        self.setMinimumWidth(420)
        self._build_ui()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("\u2702  Cortar Video")  # símbolo de tijeras
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # --- Vista previa (mismo mecanismo que VideoIngestTab/ZoneEditorTab) ---
        self.preview_label = QLabel("Cargando vista previa...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(360, 200)
        self.preview_label.setObjectName("panel")
        layout.addWidget(self.preview_label)
        self._load_preview(ratio=0.1)

        # --- Slider de inicio ---
        self.start_label = QLabel(f"Inicio: {_format_seconds(0)}")
        layout.addWidget(self.start_label)

        self.start_slider = QSlider(Qt.Horizontal)
        self.start_slider.setRange(0, int(self.video_info.duration_sec))
        self.start_slider.setValue(0)
        self.start_slider.valueChanged.connect(self._on_range_changed)
        layout.addWidget(self.start_slider)

        # --- Slider de fin ---
        self.end_label = QLabel(f"Final: {_format_seconds(self.video_info.duration_sec)}")
        layout.addWidget(self.end_label)

        self.end_slider = QSlider(Qt.Horizontal)
        self.end_slider.setRange(0, int(self.video_info.duration_sec))
        self.end_slider.setValue(int(self.video_info.duration_sec))
        self.end_slider.valueChanged.connect(self._on_range_changed)
        layout.addWidget(self.end_slider)

        note = QLabel(
            "El recorte real todavía no está conectado al backend — "
            "esto por ahora solo registra el rango elegido."
        )
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        layout.addWidget(note)

        # --- Botones ---
        buttons_row = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_apply = QPushButton("Aplicar")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(self._on_apply)

        buttons_row.addWidget(self.btn_cancel)
        buttons_row.addWidget(self.btn_apply)
        layout.addLayout(buttons_row)

    # ------------------------------------------------------------ acciones --
    def _load_preview(self, ratio: float):
        """Extrae un frame de referencia y lo muestra escalado en el label."""
        thumb_path = config.LOGS_DIR / f"{self.video_info.path.stem}_cutpreview.jpg"
        try:
            extract_thumbnail(self.video_info, thumb_path, frame_position_ratio=ratio)
            pixmap = QPixmap(str(thumb_path)).scaled(
                self.preview_label.width(), self.preview_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(pixmap)
        except VideoLoadError as exc:
            self.preview_label.setText(f"Sin vista previa: {exc}")

    def _on_range_changed(self):
        """
        Mantiene inicio < fin (si el usuario cruza los sliders, se
        empujan entre sí) y actualiza las etiquetas de tiempo.
        """
        start = self.start_slider.value()
        end = self.end_slider.value()

        if start >= end:
            if self.sender() is self.start_slider:
                self.start_slider.blockSignals(True)
                self.start_slider.setValue(max(end - 1, 0))
                self.start_slider.blockSignals(False)
                start = self.start_slider.value()
            else:
                self.end_slider.blockSignals(True)
                self.end_slider.setValue(min(start + 1, self.end_slider.maximum()))
                self.end_slider.blockSignals(False)
                end = self.end_slider.value()

        self.start_label.setText(f"Inicio: {_format_seconds(start)}")
        self.end_label.setText(f"Final: {_format_seconds(end)}")

    def _on_apply(self):
        start_sec = float(self.start_slider.value())
        end_sec = float(self.end_slider.value())

        # TODO(backend): cuando exista una función real de recorte en
        # app/core/ingestion/ (ver contrato sugerido en el docstring del
        # módulo), reemplazar esto por la llamada real y mostrar su
        # resultado. Por ahora solo se informa el rango elegido.
        self.range_selected.emit(start_sec, end_sec)
        self.accept()