"""
Ventana principal.

Diseñada como QTabWidget para que agregar módulos futuros sea
simplemente crear una nueva pestaña, sin tocar esta clase más allá de
una línea en __init__.
"""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.detection.zone import normalize_video_id
from app.core.ingestion.video_loader import VideoInfo, VideoLoadError, extract_thumbnail, load_video
from app.core.ingestion.session import parse_live_source
from app.core.ingestion.workers import LiveSessionWorker, ReferenceFrameWorker, VideoCleaningWorker
from app.ui.dialogs.accessibility_dialog import AccessibilityDialog
from app.ui.dialogs.cut_video_dialog import CutVideoDialog
from app.ui.widgets.footer import FooterBar
from app.ui.widgets.header import HeaderBar, create_accessibility_icon, create_help_icon
from app.ui.dashboard_tab import DashboardTab
from app.ui.theme import FONT_SCALES, Colors, apply_theme
from app.ui.tour import TourOverlay, build_default_tour
from app.ui.zone_editor_tab import ZoneEditorTab
from app.utils import config
from app.utils.settings import AppSettings


class VideoIngestTab(QWidget):

    # Emitida con una `AnalysisSession` lista para analizar — venga de un
    # video limpio o de una cámara en directo. Es el paso 1 → 2 del flujo.
    session_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.videos: dict[str, VideoInfo] = {}
        self.worker: VideoCleaningWorker | None = None
        self._reference_worker: ReferenceFrameWorker | None = None
        self._live_worker: LiveSessionWorker | None = None
        # Último video limpiado con éxito en esta tanda: es el que pasa a la
        # pestaña de zonas cuando termina la limpieza.
        self._last_cleaned: VideoInfo | None = None
        self._source_type = "ip_camera"  # "ip_camera" | "file_upload"

        # Se mantienen para no romper la lógica de preview/limpieza existente,
        # aunque este mockup (Source Setup & Configuration) no los muestra.
        self.thumbnail_label = QLabel()
        self.metadata_label = QLabel()

        self._build_ui()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Header --- (sin botón de acción: no había ninguna "Configuración"
        # real conectada a él en esta pestaña)
        self.header = HeaderBar("VISION_CORE_05", show_action=False)
        main_layout.addWidget(self.header)

        # --- Cuerpo: dos columnas ---
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)
        # Columna de archivos angosta (franja, como el rojo de la
        # referencia) y columna de video dominante (como el azul) —
        # antes era 1:2, ahora 1:3 para acentuar más la diferencia.
        body_layout.addWidget(self._build_left_column(), stretch=1)
        body_layout.addWidget(self._build_right_column(), stretch=3)
        main_layout.addWidget(body, stretch=1)

        # --- Footer ---
        self.footer = FooterBar()
        main_layout.addWidget(self.footer)

    def _build_left_column(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Archivos recientemente analizados")
        title.setObjectName("sectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        # stretch=3: la lista es ahora el elemento dominante de la
        # columna (antes competía en espacio con el VideoInfoPanel).
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Lista de videos cargados")
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.setSpacing(6)  # más aire entre cada video de la lista
        self.list_widget.setStyleSheet("QListWidget::item { padding: 10px; }")
        layout.addWidget(self.list_widget, stretch=3)

        # TODO (pendiente de ubicación definitiva): el mockup de esta pantalla
        # no muestra estos botones. Se dejan aquí, discretos, para no perder
        # la función mientras se decide dónde van (¿toolbar? ¿menú contextual?).
        # "Limpiar seleccionados" es la acción principal de esta pestaña, así
        # que lleva el estilo primario: antes competía en gris contra un
        # botón amarillo que no hacía nada.
        actions_row = QHBoxLayout()
        self.btn_clean = QPushButton("&Limpiar seleccionados")
        self.btn_clean.setObjectName("primary")
        self.btn_clean.setToolTip(
            "Descarta los tramos en negro o congelados y deja el video listo "
            "para analizar."
        )
        self.btn_clean.setAccessibleName("Limpiar los videos seleccionados")
        self.btn_clean.clicked.connect(self.on_clean_videos)
        self.btn_clean.setEnabled(False)

        self.btn_clean_all = QPushButton("Limpiar &todos")
        self.btn_clean_all.setAccessibleName("Limpiar todos los videos de la lista")
        self.btn_clean_all.clicked.connect(self.on_clean_all)
        self.btn_clean_all.setEnabled(False)

        self.btn_cut = QPushButton("&Cortar video")
        self.btn_cut.setAccessibleName("Cortar un fragmento del video seleccionado")
        self.btn_cut.clicked.connect(self.on_cut_video)
        self.btn_cut.setEnabled(False)

        actions_row.addWidget(self.btn_clean)
        actions_row.addWidget(self.btn_clean_all)
        actions_row.addWidget(self.btn_cut)
        layout.addLayout(actions_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setAccessibleName("Progreso de la limpieza")
        layout.addWidget(self.progress_bar)

        # Estado en texto, separado del log: el log es un historial que hay
        # que leer entero, y el usuario necesita saber de un vistazo qué
        # está pasando ahora.
        self.status_label = QLabel("Carga un video para empezar.")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Estado actual")
        layout.addWidget(self.status_label)

        # stretch=1 en vez del alto fijo que tenía antes: sigue siendo
        # más chico que la lista (stretch=3), pero ya no compite con un
        # VideoInfoPanel que ocupaba espacio sin aportar nada aquí.
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setAccessibleName("Historial de mensajes")
        layout.addWidget(self.log_area, stretch=1)

        return panel

    def _build_right_column(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Subir nuevo video")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # --- Vista previa grande del video cargado/seleccionado ---
        # Bloque dominante de la pantalla (el "azul" de la referencia):
        # tamaño mínimo más grande y stretch=3 en el layout vertical,
        # para que absorba todo el espacio extra por encima de la
        # tarjeta de subida (que se queda con su tamaño natural, sin
        # stretch — el "blanco", más chico y de menor jerarquía visual).
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setMinimumSize(420, 260)
        self.thumbnail_label.setObjectName("panel")
        self.thumbnail_label.setText("Selecciona un video de la lista para ver su vista previa")
        self.thumbnail_label.setWordWrap(True)
        self.thumbnail_label.setAccessibleName("Vista previa del video seleccionado")
        layout.addWidget(self.thumbnail_label, stretch=3)

        # Los metadatos ya se calculaban (resolución, fps, duración, peso,
        # resultado de la limpieza) pero este label nunca se añadía a
        # ningún layout: el trabajo se hacía y el usuario no lo veía nunca.
        self.metadata_label.setObjectName("mutedText")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextFormat(Qt.RichText)
        self.metadata_label.setText("Sin video seleccionado.")
        self.metadata_label.setAccessibleName("Datos del video seleccionado")
        layout.addWidget(self.metadata_label)

        card = QFrame()
        card.setObjectName("panel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        params_label = QLabel("INPUT_PARAMETERS")
        params_label.setObjectName("fieldLabel")
        card_layout.addWidget(params_label)

        source_type_label = QLabel("SOURCE_TYPE")
        source_type_label.setObjectName("fieldLabel")
        card_layout.addWidget(source_type_label)

        toggle_row = QHBoxLayout()
        self.btn_ip_camera = QPushButton("IP CAMERA")
        self.btn_ip_camera.clicked.connect(lambda: self._set_source_type("ip_camera"))
        self.btn_file_upload = QPushButton("FILE UPLOAD")
        self.btn_file_upload.clicked.connect(lambda: self._set_source_type("file_upload"))
        toggle_row.addWidget(self.btn_ip_camera)
        toggle_row.addWidget(self.btn_file_upload)
        card_layout.addLayout(toggle_row)

        # --- Bloque RTSP (visible cuando source_type == "ip_camera") ---
        self.rtsp_label = QLabel("DIRECCIÓN DE LA CÁMARA")
        self.rtsp_label.setObjectName("fieldLabel")
        self.rtsp_input = QLineEdit()
        self.rtsp_input.setPlaceholderText("rtsp://192.168.1.42:8080/h264_ulaw.sdp  ·  o  0  para la webcam")
        self.rtsp_input.setAccessibleName("Dirección de la cámara o número de webcam")
        self.rtsp_input.returnPressed.connect(self._on_connect_clicked)
        card_layout.addWidget(self.rtsp_label)
        card_layout.addWidget(self.rtsp_input)

        self.rtsp_help = QLabel(
            "Acepta una dirección de cámara IP (rtsp:// o http://) o el número "
            "de una webcam local: 0 es la integrada. Para probar con el móvil, "
            "usa su punto de acceso: en una red compartida los dispositivos "
            "suelen estar aislados entre sí."
        )
        self.rtsp_help.setObjectName("mutedText")
        self.rtsp_help.setWordWrap(True)
        card_layout.addWidget(self.rtsp_help)

        # --- Bloque subir archivo (visible cuando source_type == "file_upload") ---
        self.btn_load = QPushButton("\U0001F4C1 Haz clic para buscar un archivo")
        self.btn_load.clicked.connect(self.on_load_videos)
        card_layout.addWidget(self.btn_load)

        self.btn_connect = QPushButton("CONNECT STREAM")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        card_layout.addWidget(self.btn_connect)

        layout.addWidget(card)

        # Estado inicial: subir archivo, no cámara IP. Antes arrancaba en
        # "IP CAMERA" con "CONNECT STREAM" como botón primario — es decir,
        # lo primero que veía el usuario era la única función que todavía
        # no existe, mientras la limpieza de video (lo que la aplicación sí
        # hace) quedaba en dos botones pequeños y grises.
        self._set_source_type("file_upload")
        return panel

    # ------------------------------------------------------- toggle fuente --
    def _set_source_type(self, source_type: str):
        self._source_type = source_type
        is_ip = source_type == "ip_camera"

        self.btn_ip_camera.setObjectName("toggleActive" if is_ip else "toggleInactive")
        self.btn_file_upload.setObjectName("toggleInactive" if is_ip else "toggleActive")
        for btn in (self.btn_ip_camera, self.btn_file_upload):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.rtsp_label.setVisible(is_ip)
        self.rtsp_input.setVisible(is_ip)
        self.rtsp_help.setVisible(is_ip)
        self.btn_load.setVisible(not is_ip)
        self.btn_connect.setText("CONNECT STREAM" if is_ip else "SUBIR ARCHIVO")

    def _on_connect_clicked(self):
        if self._source_type == "file_upload":
            self.on_load_videos()
        else:
            self.connect_live_camera()

    # ------------------------------------------------------ cámara en vivo --
    def connect_live_camera(self):
        """
        Abre la cámara indicada y prepara su sesión de análisis.

        La conexión corre en un hilo: abrir un stream RTSP puede tardar
        varios segundos, o agotar el timeout si la dirección está mal, y
        congelar la ventana mientras tanto haría parecer que la aplicación
        se colgó justo cuando el usuario duda de lo que escribió.
        """
        if self._live_worker is not None and self._live_worker.isRunning():
            self._set_status("Ya hay una conexión en curso, espera un momento.")
            return

        try:
            source = parse_live_source(self.rtsp_input.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Dirección no válida", str(exc))
            return

        # Un id estable y legible por fuente, para que las zonas dibujadas
        # hoy sigan sirviendo la próxima vez que se conecte la misma cámara.
        label = f"webcam_{source}" if isinstance(source, int) else f"camara_{source.split('//')[-1]}"
        video_id = normalize_video_id(label, is_live=True)

        self.btn_connect.setEnabled(False)
        self._set_status("Conectando con la cámara…")
        self._log(f" Conectando con {source}…")

        self._live_worker = LiveSessionWorker(source, video_id)
        self._live_worker.progress_note.connect(self._log)
        self._live_worker.failed.connect(self._on_live_failed)
        self._live_worker.session_ready.connect(self._on_live_session_ready)
        self._live_worker.finished.connect(lambda: self.btn_connect.setEnabled(True))
        self._live_worker.start()

    def _on_live_failed(self, message: str):
        self._set_status("No se pudo conectar con la cámara.")
        self._log(f"❌ {message}")
        QMessageBox.warning(self, "Sin conexión con la cámara", message)

    def _on_live_session_ready(self, session):
        self._set_status(
            f"Cámara conectada: {len(session.suggested_zones)} zona(s) propuesta(s). "
            "Continúa en la pestaña 2."
        )
        self._log(f"✅ {session.describe_origin()} — sesión '{session.video_id}' lista.")
        self.session_ready.emit(session)

    # --------------------------------------------------------- cortar video --
    def on_cut_video(self):
        items = self.list_widget.selectedItems()
        if not items:
            QMessageBox.information(self, "Sin selección", "Selecciona un video de la lista para cortar.")
            return
        filename = items[0].data(Qt.UserRole)
        video_info = self.videos.get(filename)
        if not video_info:
            return

        dialog = CutVideoDialog(video_info, parent=self)
        dialog.range_selected.connect(self._on_cut_range_selected)
        dialog.exec()

    def _on_cut_range_selected(self, start_sec: float, end_sec: float):
        # Solo interfaz por ahora: el recorte real queda pendiente de
        # backend (ver TODO en cut_video_dialog.py).
        self._log(
            f" Rango de recorte elegido: {start_sec:.0f}s a {end_sec:.0f}s "
            f"(recorte real pendiente de backend)."
        )

    # ---------------------------------------------------------- callbacks --
    def on_load_videos(self):
        extensions = " ".join(f"*{ext}" for ext in config.SUPPORTED_VIDEO_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar videos", str(Path.home()), f"Videos ({extensions})"
        )
        if not paths:
            return

        for path_str in paths:
            path = Path(path_str)
            try:
                video_info = load_video(path)
            except VideoLoadError as exc:
                self._log(f"❌ {path.name}: {exc}")
                continue

            # Fecha real de carga (no inventada por el widget, viene de afuera)
            video_info.loaded_at = datetime.now().strftime("%Y-%m-%d %H:%M")

            self.videos[video_info.filename] = video_info

            item = QListWidgetItem(
                f"✅ {video_info.filename}   —   {video_info.duration_sec:.1f}s"
            )
            item.setData(Qt.UserRole, video_info.filename)
            self.list_widget.addItem(item)
            self._log(f"Cargado: {video_info.filename} — {video_info.width}x{video_info.height} @ {video_info.fps:.1f}fps")

        self.btn_clean.setEnabled(len(self.videos) > 0)
        self.btn_clean_all.setEnabled(len(self.videos) > 0)

    def _on_selection_changed(self):
        items = self.list_widget.selectedItems()
        self.btn_cut.setEnabled(bool(items))
        if not items:
            return
        filename = items[0].data(Qt.UserRole)
        video_info = self.videos.get(filename)
        if not video_info:
            return

        thumb_path = config.LOGS_DIR / f"{Path(filename).stem}_thumb.jpg"
        try:
            if not thumb_path.exists():
                extract_thumbnail(video_info, thumb_path)
            pixmap = QPixmap(str(thumb_path)).scaled(
                self.thumbnail_label.width(), self.thumbnail_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(pixmap)
        except VideoLoadError as exc:
            self.thumbnail_label.setText(f"Sin vista previa: {exc}")

        status_line = f"Estado: {video_info.status}"
        if video_info.cleaning_report:
            r = video_info.cleaning_report
            status_line += (
                f"\nFrames leídos: {r['frames_read']} | escritos: {r['frames_written']}"
                f"\nNegros removidos: {r['black_frames_removed']} | congelados removidos: {r['frozen_frames_removed']}"
            )

        self.metadata_label.setText(
            f"<b>{video_info.filename}</b><br>"
            f"Resolución: {video_info.width}x{video_info.height}<br>"
            f"FPS: {video_info.fps:.2f}<br>"
            f"Duración: {video_info.duration_sec:.1f} s<br>"
            f"Tamaño: {video_info.size_mb} MB<br>"
            f"{status_line}"
        )

    def on_clean_videos(self):
        items = self.list_widget.selectedItems()
        if not items:
            QMessageBox.information(self, "Sin selección", "Selecciona al menos un video de la lista.")
            return
        filenames = [item.data(Qt.UserRole) for item in items]
        self._run_cleaning([self.videos[f] for f in filenames])

    def on_clean_all(self):
        if not self.videos:
            return
        self._run_cleaning(list(self.videos.values()))

    def _run_cleaning(self, videos_to_clean: list[VideoInfo]):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "En proceso", "Ya hay una limpieza en curso, espera a que termine.")
            return

        self.btn_load.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.btn_clean_all.setEnabled(False)
        self.progress_bar.setValue(0)

        self.footer.reset_fps()
        self.worker = VideoCleaningWorker(videos_to_clean)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.video_finished.connect(self._on_video_finished)
        self.worker.video_failed.connect(self._on_video_failed)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.start()

        self._set_status(f"Limpiando {len(videos_to_clean)} video(s)…")
        self._log(f"Iniciando limpieza de {len(videos_to_clean)} video(s)...")

    def _on_progress(self, filename: str, current: int, total: int):
        pct = int((current / total) * 100) if total else 0
        self.progress_bar.setValue(pct)
        self.footer.note_frame_progress(current)

    def _on_video_finished(self, filename: str, report: dict):
        video_info = self.videos[filename]
        video_info.status = "limpio"
        video_info.cleaning_report = report
        video_info.output_path = Path(report["output_path"])
        self._last_cleaned = video_info

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == filename:
                item.setText(f"🟢 {filename}  (limpio → {video_info.output_path.name})")

        self._log(
            f"✅ {filename} limpio: {report['frames_written']} frames útiles, "
            f"{report['black_frames_removed']} negros y {report['frozen_frames_removed']} congelados removidos."
        )

    def _on_video_failed(self, filename: str, error: str):
        video_info = self.videos.get(filename)
        if video_info:
            video_info.status = "error"
            video_info.error_message = error
        self._set_status(f"No se pudo limpiar {filename}.")
        self._log(f"❌ Falló limpieza de {filename}: {error}")

    def _on_all_finished(self):
        self.btn_load.setEnabled(True)
        self.btn_clean.setEnabled(True)
        self.btn_clean_all.setEnabled(True)
        self.progress_bar.setValue(100)
        self._set_status("Limpieza terminada. Preparando las zonas de góndola…")
        self._log("Proceso de limpieza finalizado.")
        self._prepare_session()

    # ------------------------------------------------- paso 1 → paso 2 --
    def _prepare_session(self):
        """
        Prepara la sesión del último video limpiado y la pasa a la pestaña
        de zonas: elige un frame de referencia bueno y propone las ROI.

        Antes, la pestaña de zonas estaba desconectada de esta: había que
        volver a buscar el mismo video a mano en un segundo diálogo. Ahora
        el video limpio, su frame y unas zonas de partida llegan solos.
        """
        video_info = self._last_cleaned
        if video_info is None or video_info.output_path is None:
            return
        if self._reference_worker is not None and self._reference_worker.isRunning():
            return

        video_id = normalize_video_id(video_info.output_path.stem)
        self._set_status("Buscando el mejor fotograma y proponiendo zonas de góndola…")
        self._log(f" Preparando sesión de análisis para '{video_id}'...")

        self._reference_worker = ReferenceFrameWorker(
            video_id=video_id,
            clean_video_path=video_info.output_path,
            fps=video_info.cleaning_report.get("output_fps") or video_info.fps,
        )
        self._reference_worker.progress_note.connect(self._log)
        self._reference_worker.failed.connect(
            lambda msg: self._log(f"⚠️ No se pudo preparar la sesión automáticamente: {msg}")
        )
        self._reference_worker.session_ready.connect(self._on_session_ready)
        self._reference_worker.start()

    def _on_session_ready(self, session):
        self._log(
            f"✅ Sesión lista: {len(session.suggested_zones)} zona(s) sugerida(s). "
            "Revísalas en la pestaña 2 antes de iniciar el análisis."
        )
        self._set_status(
            f"Listo: {len(session.suggested_zones)} zona(s) propuesta(s). "
            "Continúa en la pestaña 2."
        )
        self.session_ready.emit(session)

    def _set_status(self, message: str):
        """
        Mensaje de estado visible fuera del log.

        Además de mostrarlo, actualiza la descripción accesible del panel:
        los lectores de pantalla anuncian el cambio sin que el usuario
        tenga que ir a buscarlo al historial.
        """
        self.status_label.setText(message)
        self.status_label.setAccessibleDescription(message)

    def _log(self, message: str):
        self.log_area.append(message)


class MainWindow(QMainWindow):
    """
    Ventana principal: tres pestañas encadenadas en un solo flujo.

        1. Carga y limpieza   --session_ready-->   2. Zonas (ROI)
        2. Zonas (ROI)     --analysis_finished-->  3. Dashboard

    Las pestañas no se conocen entre sí: se comunican por señales que se
    conectan acá. Cada una sigue siendo usable por separado (se puede
    cargar un video directamente en la 2, o abrir el dashboard sin haber
    analizado nada), pero el camino natural ya no obliga al usuario a
    volver a buscar el mismo archivo en cada pantalla.
    """

    TAB_INGEST, TAB_ZONES, TAB_DASHBOARD = 0, 1, 2

    # Suelo de tamaño de la ventana. Por debajo de esto la interfaz es
    # inservible aunque técnicamente quepa gracias al scroll.
    MIN_WINDOW_SIZE = (720, 520)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scapder Vision — Prototipo de Space Management")
        # Tamaño inicial acotado a la pantalla: en un portátil de 1366x768
        # una ventana de 1180x760 aparecía con los bordes fuera del área útil.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(1180, available.width() - 40), min(760, available.height() - 60))
        else:
            self.resize(1180, 760)
        self.setMinimumSize(*self.MIN_WINDOW_SIZE)

        self._tour: TourOverlay | None = None

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.ingest_tab = VideoIngestTab()
        self.zone_tab = ZoneEditorTab()
        self.dashboard_tab = DashboardTab()

        # Cada pestaña va dentro de un área con scroll. Sin esto, el mínimo
        # de la ventana lo marcaba el contenido más ancho (1217 px con la
        # letra normal, 1752 px al 150%): más que el ancho útil de un
        # portátil de 1366, así que el tamaño de letra grande — justo el que
        # necesita quien no ve bien — dejaba la aplicación inusable. Ahora la
        # ventana se puede achicar y el contenido se desplaza.
        self.tabs.addTab(self._scrollable(self.ingest_tab), "1. Carga y Limpieza de Video")
        self.tabs.addTab(self._scrollable(self.zone_tab), "2. Edición de Zonas (ROI)")
        self.tabs.addTab(self._scrollable(self.dashboard_tab), "3. Dashboard de Métricas")

        # Mnemónicos: Alt+1/2/3 saltan de pestaña sin tocar el ratón.
        for index, key in enumerate(("Alt+1", "Alt+2", "Alt+3")):
            QShortcut(QKeySequence(key), self, lambda i=index: self.tabs.setCurrentIndex(i))
        QShortcut(QKeySequence("F1"), self, self.start_tour)

        self.tabs.setCornerWidget(self._build_corner_widget(), Qt.TopRightCorner)

        # Paso 1 → 2: video limpio + frame de referencia + ROI sugeridas.
        self.ingest_tab.session_ready.connect(self._on_session_ready)
        # Paso 2 → 3: el análisis terminó y ya hay datos que mostrar.
        self.zone_tab.analysis_finished.connect(self._on_analysis_finished)

        self.setCentralWidget(self.tabs)

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        """Envuelve una pestaña en un área con scroll, sin marco visible."""
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        return area

    # ------------------------------------------------- esquina superior --
    def _build_corner_widget(self) -> QWidget:
        """
        Ayuda y accesibilidad, siempre visibles en la esquina superior
        derecha — no dentro de un menú. Son justo los controles que alguien
        que llega perdido, o que no ve bien la pantalla, necesita encontrar
        sin buscar.
        """
        self.corner_widget = QWidget()
        layout = QHBoxLayout(self.corner_widget)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        self.btn_tour = QPushButton()
        self.btn_tour.setObjectName("iconButton")
        self.btn_tour.setIcon(create_help_icon(color=Colors.TEXT_PRIMARY))
        self.btn_tour.setIconSize(QSize(18, 18))
        self.btn_tour.setToolTip("Ver el tour de la aplicación (F1)")
        self.btn_tour.setAccessibleName("Ver el tour de la aplicación")
        self.btn_tour.setAccessibleDescription(
            "Abre un recorrido guiado que explica las tres pestañas paso a paso."
        )
        self.btn_tour.clicked.connect(self.start_tour)
        layout.addWidget(self.btn_tour)

        self.btn_accessibility = QPushButton()
        self.btn_accessibility.setObjectName("iconButton")
        self.btn_accessibility.setIcon(create_accessibility_icon(color=Colors.TEXT_PRIMARY))
        self.btn_accessibility.setIconSize(QSize(18, 18))
        self.btn_accessibility.setToolTip("Accesibilidad y apariencia")
        self.btn_accessibility.setAccessibleName("Accesibilidad y apariencia")
        self.btn_accessibility.setAccessibleDescription(
            "Cambia el tema de color y el tamaño de la letra de la aplicación."
        )
        self.btn_accessibility.clicked.connect(self.open_accessibility)
        layout.addWidget(self.btn_accessibility)

        return self.corner_widget

    # -------------------------------------------------- tema y tipografía --
    def apply_preferences(self, theme: str, scale_key: str, persist: bool = False) -> None:
        """
        Aplica tema y tamaño de letra a toda la aplicación, en caliente.

        Repintar no basta. Al cambiar el tamaño de letra cambian los
        tamaños que cada widget pide, pero Qt tiene esos valores en caché:
        sin invalidarlos, la ventana se quedaba con la geometría anterior
        y el contenido aparecía cortado o apretado hasta que el usuario la
        redimensionaba a mano. Por eso, además de aplicar el tema:

        1. `unpolish`/`polish` obliga a cada widget a releer la hoja de
           estilos nueva.
        2. `updateGeometry` + `invalidate`/`activate` de los layouts tira
           la caché de tamaños y vuelve a repartir el espacio.
        3. La ventana crece si su nuevo mínimo ya no cabe en su tamaño
           actual — nunca se encoge sola, para no deshacer el tamaño que
           el usuario le haya dado.
        """
        app = QApplication.instance()
        if app is None:
            return
        scale = FONT_SCALES.get(scale_key, FONT_SCALES["normal"])[0]
        apply_theme(app, theme, scale)

        if persist:
            AppSettings.set_theme(theme)
            AppSettings.set_font_scale_key(scale_key)

        self._refresh_icons()
        self._relayout_after_style_change()

    def _relayout_after_style_change(self) -> None:
        """
        Invalida las cachés de tamaño y vuelve a acomodar la ventana.

        Tres detalles que hacen que esto funcione y sin los cuales la
        ventana se quedaba trabada:

        1. **Se limpia el mínimo anterior.** Qt deja fijado en la ventana el
           mínimo que calculó con la letra grande; al volver a una letra
           chica ese mínimo seguía vigente y la ventana ya no se podía
           encoger — el mismo bloqueo, al revés.
        2. **Los layouts se activan de hijos a padres.** `findChildren`
           devuelve de arriba abajo; si se activa el padre antes que el
           hijo, el padre mide con los tamaños viejos del hijo.
        3. **Las pestañas ocultas también.** Un `QStackedWidget` solo
           recalcula la página visible, pero su mínimo es el máximo de
           TODAS: una pestaña oculta con medidas viejas inflaba el mínimo
           de la ventana entera.
        """
        pages = [self.ingest_tab, self.zone_tab, self.dashboard_tab]
        widgets = [self] + self.findChildren(QWidget)

        # 1. Soltar el mínimo que quedó de la escala anterior (se restaura
        #    el suelo propio de la aplicación al final).
        self.setMinimumSize(0, 0)

        # 2. Releer la hoja de estilos en cada widget.
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)

        # 3. Invalidar y reactivar de hijos a padres (orden inverso).
        for widget in reversed(widgets):
            widget.updateGeometry()
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

        # 4. Forzar a las pestañas ocultas a recalcularse: su tamaño cuenta
        #    para el mínimo del contenedor aunque no se estén viendo.
        for page in pages:
            page.adjustSize()
            page_layout = page.layout()
            if page_layout is not None:
                page_layout.invalidate()
                page_layout.activate()
        self.tabs.updateGeometry()
        if self.tabs.layout() is not None:
            self.tabs.layout().activate()

        # 5. Crecer si el contenido ya no cabe; nunca encoger por su cuenta,
        #    para no deshacer el tamaño que el usuario le haya dado, y nunca
        #    pasarse del área útil de la pantalla: con la letra al 150% el
        #    tamaño que pide el contenido supera el alto de un portátil, y
        #    una ventana más grande que la pantalla deja los botones de
        #    abajo fuera de alcance.
        needed = self.minimumSizeHint()
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_w, max_h = available.width(), available.height()
        else:
            max_w, max_h = needed.width(), needed.height()

        self.resize(
            min(max(self.width(), needed.width()), max_w),
            min(max(self.height(), needed.height()), max_h),
        )

        self.setMinimumSize(*self.MIN_WINDOW_SIZE)

        for widget in widgets:
            widget.update()
        self.update()

        # El tour dibuja un hueco sobre coordenadas ya calculadas: si está
        # abierto cuando cambia el tamaño de letra, hay que recolocarlo.
        if self._tour is not None and self._tour.isVisible():
            self._tour.relayout()

    def _refresh_icons(self):
        """
        Redibuja los íconos vectoriales con el color del tema activo.

        Se generan con QPainter sobre un color concreto: al pasar al tema
        claro, un ícono blanco quedaba invisible sobre fondo blanco.
        """
        ink = Colors.TEXT_PRIMARY
        self.btn_tour.setIcon(create_help_icon(color=ink))
        self.btn_accessibility.setIcon(create_accessibility_icon(color=ink))
        for tab in (self.ingest_tab, self.zone_tab, self.dashboard_tab):
            header = getattr(tab, "header", None)
            if header is not None and hasattr(header, "refresh_icon_color"):
                header.refresh_icon_color(ink)

    def open_accessibility(self):
        dialog = AccessibilityDialog(AppSettings.theme(), AppSettings.font_scale_key(), parent=self)
        dialog.preview_requested.connect(
            lambda theme, scale: self.apply_preferences(theme, scale, persist=False)
        )
        dialog.tour_requested.connect(self.start_tour)
        if dialog.exec() == AccessibilityDialog.Accepted:
            theme, scale = dialog.selection()
            self.apply_preferences(theme, scale, persist=True)

    # ------------------------------------------------------------- tour --
    def start_tour(self):
        """Lanza el tour guiado. Si ya hay uno abierto, no abre un segundo."""
        if self._tour is not None and self._tour.isVisible():
            return
        self._tour = TourOverlay(self, build_default_tour(self))
        self._tour.finished.connect(self._on_tour_finished)
        self._tour.start()

    def _on_tour_finished(self):
        AppSettings.set_tour_seen(True)
        self._tour = None
        self.tabs.setCurrentIndex(self.TAB_INGEST)

    def showEvent(self, event):
        """
        En el primer arranque, abre el tour solo.

        Se difiere con `singleShot(0, ...)` para que la ventana ya tenga su
        geometría final: el overlay necesita medir los widgets que va a
        resaltar, y antes de que Qt termine el primer layout todos miden 0.
        """
        super().showEvent(event)
        if not AppSettings.tour_seen() and self._tour is None:
            QTimer.singleShot(250, self.start_tour)

    def _on_session_ready(self, session):
        """Carga la sesión en la pestaña de zonas y salta a ella."""
        self.zone_tab.load_session(session)
        self.tabs.setCurrentIndex(self.TAB_ZONES)

    def _on_analysis_finished(self, video_id: str):
        """Muestra en el dashboard la sesión recién analizada y salta a él."""
        self.dashboard_tab.show_session(video_id)
        self.tabs.setCurrentIndex(self.TAB_DASHBOARD)