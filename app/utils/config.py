
"""
Configuración global del proyecto Scapder Vision.
Todos los parámetros ajustables viven aquí para no tocar código
cuando se necesite calibrar el sistema.
"""
from pathlib import Path

# ---- Rutas base ----
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LOGS_DIR = DATA_DIR / "logs"

for d in (RAW_DIR, PROCESSED_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---- Formatos soportados ----
SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".wmv")

# ---- Límites de carga (evitan que un video gigante o de horas tumbe la app) ----
# Duración máxima permitida en segundos. None = sin límite.
MAX_VIDEO_DURATION_SEC = 43200        # 12 horas

# Peso máximo permitido en MB. None = sin límite.
MAX_VIDEO_SIZE_MB = 10000             # 10 GB

# ---- Seguridad de carga (archivos de fuentes no confiables) ----
# Segundos máximos que se espera a que OpenCV abra el video y lea el
# primer frame antes de abortar la carga. Un contenedor corrupto o
# deliberadamente malformado puede colgar la lectura indefinidamente;
# esto evita que la UI se congele para siempre esperándola.
VIDEO_LOAD_TIMEOUT_SEC = 20

# Resolución máxima aceptada (ancho, alto). Un header manipulado que
# reporte una resolución absurda podría disparar asignaciones de memoria
# enormes más adelante (miniatura, tracking, pose) — 8K de margen es más
# que suficiente para cualquier cámara de vigilancia real.
MAX_VIDEO_WIDTH = 7680
MAX_VIDEO_HEIGHT = 4320

# Tope de sanidad para frame_count reportado por el contenedor — no es una
# duración esperada (para eso está MAX_VIDEO_DURATION_SEC), sino una
# defensa contra un valor de header corrupto/manipulado fuera de todo
# rango razonable.
MAX_VIDEO_FRAME_COUNT = 20_000_000

# ---- Parámetros de limpieza de video ----
# FPS objetivo al reencodar (None = mantener el original)
DEFAULT_TARGET_FPS = None

# Resolución objetivo (ancho, alto). None = mantener original.
DEFAULT_TARGET_RESOLUTION = None

# Umbral de desviación estándar de intensidad para considerar un frame
# "congelado" o corrupto (frames casi idénticos consecutivos o pantalla negra)
FROZEN_FRAME_STD_THRESHOLD = 2.0
BLACK_FRAME_MEAN_THRESHOLD = 8.0

# Cuántos frames idénticos consecutivos se toleran antes de marcar como
# "cámara congelada" (posible corte de señal)
MAX_CONSECUTIVE_FROZEN_FRAMES = 15

# Codec de salida para los videos limpios
OUTPUT_CODEC = "mp4v"
OUTPUT_EXTENSION = ".mp4"

# --- Módulo 2: Detección, tracking y pose ---
DETECTION_MODEL_NAME = "yolo11n.pt"       # Modelo de detección de personas (pre-entrenado COCO)
POSE_MODEL_NAME = "yolo11n-pose.pt"       # Modelo de pose (pre-entrenado COCO-Keypoints)
DETECTION_CONF_THRESHOLD = 0.4            # Confianza mínima para aceptar una detección de persona
DETECTION_IOU_THRESHOLD = 0.5             # Umbral de IoU para NMS
TRACKER_CONFIG = "bytetrack.yaml"         # Tracker integrado de ultralytics

# --- Módulo 2: Zonas e interacción ---
ZONES_STORAGE_PATH = str(DATA_DIR / "zones") # Carpeta donde se guardan los polígonos de zona (.json)
ARM_EXTENSION_MIN_RATIO = 1.3             # Ratio distancia(muñeca,hombro)/longitud_antebrazo para considerar "brazo extendido"
MIN_KEYPOINT_CONFIDENCE = 0.3             # Confianza mínima de un keypoint para considerarlo válido en el cálculo geométrico

# --- Módulo 2: Emparejamiento pose <-> track ---
POSE_TRACK_MATCH_IOU_MIN = 0.25           # IoU mínimo entre bbox de pose y bbox de track para considerarlos la misma persona
POSE_TRACK_MATCH_MAX_DIST_SQ = 22500      # Distancia euclidiana al cuadrado (px^2) máxima como fallback si no hay solapamiento de IoU

# --- Módulo 2: Máquina de estados ---
MIN_FRAMES_REACHING_TO_HOLDING = 5        # Frames consecutivos en zona con brazo extendido antes de pasar a "holding"
MIN_FRAMES_HOLDING = 8                    # Frames mínimos en "holding" antes de poder emitir taken/returned
MAX_FRAMES_MISSING_TO_RESET = 10          # Frames sin detección de esa persona antes de resetear su estado a "idle"
MAX_SECONDS_STUCK_REACHING = 1.0          # Segundos con la muñeca dentro de la zona pero brazo no extendido antes de resetear a IDLE (evita "atascos")

# --- Módulo 2: Trayectoria continua (heatmaps de circulación) ---
TRAJECTORY_SAMPLE_EVERY_N_FRAMES = 1      # Publicar una PositionSample por persona cada N frames (1 = todos los frames)

# --- Módulo 2: Publicación de eventos ---
EVENT_PUBLISHER_MODE = "file"             # "file" | "stdout" | "inprocess" (websocket descartado para MVP: ver docs/event_schema.md)
EVENTS_LOCAL_LOG_PATH = str(DATA_DIR / "events") # Carpeta de respaldo local mientras no hay transporte confirmado con Team 3

# --- Módulo 3: Almacenamiento de eventos (backend local) ---
EVENT_STORE_DB_PATH = str(DATA_DIR / "scapder_events.db") # SQLite local para eventos + muestras de posición

# --- Flujo de la app: análisis lanzado desde la pestaña de zonas ---
# El análisis corre sobre el video YA limpio. A 1 frame de cada
# ANALYSIS_FRAME_STRIDE, un clip de demo termina en un tiempo razonable en
# CPU sin GPU (criterio de viabilidad edge del reto). Subirlo a 1 procesa
# todos los frames: máxima fidelidad de la máquina de estados y del dwell
# time, pero mucho más lento.
ANALYSIS_FRAME_STRIDE = 3

# --- Auto-ROI: sugerencia de zonas sobre el frame de referencia ---
# El frame de referencia se elige automáticamente al terminar la limpieza
# (ver app/core/ingestion/frame_picker.py) y sobre él se proponen zonas de
# góndola (ver app/core/detection/roi_suggester.py). Son SUGERENCIAS: no se
# escriben en disco hasta que el usuario las acepta en la pestaña 2.
REFERENCE_FRAME_SAMPLES = 12              # cuántos frames se muestrean para elegir el "mejor" frame
ROI_SUGGEST_MAX_ZONES = 6                 # tope de zonas propuestas (más que esto satura el lienzo)
ROI_SUGGEST_MIN_AREA_RATIO = 0.010        # área mínima de una zona, como fracción del área del frame
ROI_SUGGEST_MAX_AREA_RATIO = 0.350        # área máxima (por encima de esto es pared/piso, no un estante)
ROI_SUGGEST_MIN_ASPECT_RATIO = 0.6        # ancho/alto mínimo: un estante es más ancho que alto
ROI_SUGGEST_MERGE_IOU = 0.25              # IoU por encima del cual dos candidatos se consideran la misma zona

# Asegurar que existan los directorios
Path(ZONES_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
Path(EVENTS_LOCAL_LOG_PATH).mkdir(parents=True, exist_ok=True)

# --- UI: identidad visual (Header/Footer) ---
ENGINE_VERSION = "VISION_ENGINE v2.4.0-STABLE"
