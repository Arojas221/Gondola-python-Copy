import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from app.utils import config

METRICS_POLL_INTERVAL_MS = 1000


class FooterBar(QFrame):
    """Barra inferior: versión del motor + métricas en vivo (FPS/CPU)"""

    def __init__(self, engine_version: str = "", parent=None):
        super().__init__(parent)
        engine_version = engine_version or config.ENGINE_VERSION
        self.setObjectName("panel")

        # CPU: % del proceso de la app (no del sistema completo), normalizado
        # por núcleos para que lea como el Task Manager de Windows (0-100%).
        # La primera llamada a cpu_percent() siempre devuelve 0.0 — se
        # "ceba" acá para que la primera lectura real (1s después) ya sea
        # válida en vez de mostrar 0% falso.
        self._process = psutil.Process()
        self._process.cpu_percent(None)
        self._cpu_count = psutil.cpu_count() or 1

        # FPS: se calcula como la cantidad de frames que avanzó el contador
        # entre un tick del timer y el siguiente (1s), no un promedio desde
        # el inicio — así refleja el throughput actual del proceso corriendo
        # (limpieza de video o debug de detección), no uno viejo.
        self._total_frames = 0
        self._last_total_frames = 0

        self._build_ui(engine_version)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(METRICS_POLL_INTERVAL_MS)

    def _build_ui(self, engine_version: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self.version_label = QLabel(engine_version)
        self.version_label.setObjectName("mutedText")  # estilo gris/pequeño, de theme.py
        layout.addWidget(self.version_label)

        layout.addStretch()

        self.metrics_label = QLabel("FPS: -- | CPU: --%")
        self.metrics_label.setObjectName("mutedText")
        layout.addWidget(self.metrics_label)

    # --------------------------------------------------------------- API --
    def note_frame_progress(self, total_frames_processed: int):
        """
        Reporta cuántos frames lleva procesados el trabajo activo (limpieza
        de video o debug de detección) — se conecta directo a la señal
        `progress_updated` del worker correspondiente. El footer calcula
        los FPS solo, comparando este valor entre ticks de 1 segundo.
        """
        self._total_frames = total_frames_processed

    def reset_fps(self):
        """Reinicia el conteo de frames al arrancar un trabajo nuevo, para
        no mostrar un FPS negativo/erróneo por un contador que volvió a 0."""
        self._total_frames = 0
        self._last_total_frames = 0

    def update_metrics(self, fps: float, cpu_pct: float):
        """Actualiza el texto de métricas"""
        self.metrics_label.setText(f"FPS: {fps:.1f} | CPU: {cpu_pct:.0f}%")

    # ----------------------------------------------------------- interno --
    def _tick(self):
        cpu_pct = self._process.cpu_percent(None) / self._cpu_count
        fps = max(0, self._total_frames - self._last_total_frames)
        self._last_total_frames = self._total_frames
        self.update_metrics(fps, cpu_pct)
