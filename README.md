# (Este proyecto Le pertenece al grupo usta_code)

# Scapder Vision — Prototipo

Prototipo de escritorio para el reto de space management con visión
computacional (Scapder). Este repositorio cubre, en capas incrementales:

- **Módulo 1: Carga y Limpieza de Video** — ingesta, validación (incluida
  seguridad contra archivos maliciosos/corruptos) y reencode.
- **Módulo 2: Detección y Eventos** — tracking, pose, zonas, interacciones
  (`taken`/`returned`), dwell time y detección de personal.
- **Módulo 3: Trayectoria, Transporte y Backend Local** — muestras continuas
  de posición (heatmaps), bus de eventos in-process y almacenamiento SQLite.
- **Módulo 4: Dashboard de Métricas** — KPIs, serie temporal, ranking de
  zonas, mapa de calor de circulación de clientes y feed de eventos, todo
  dentro de la misma app de escritorio.

---

## Índice

1. [Qué se construyó (visión general y estructura)](#1-qué-se-construyó-visión-general-y-estructura)
   - [El flujo de la app: las tres pestañas son un solo camino](#el-flujo-de-la-app-las-tres-pestañas-son-un-solo-camino)
2. [Cómo correr el proyecto](#2-cómo-correr-el-proyecto)
3. [Módulo 1 — Carga y Limpieza de Video](#módulo-1--carga-y-limpieza-de-video)
   - [3.1 Qué se construyó (Módulo 1)](#31-qué-se-construyó-módulo-1)
   - [3.2 Cómo limitar duración y peso de los videos cargados](#32-cómo-limitar-duración-y-peso-de-los-videos-cargados)
   - [3.3 Qué contiene el reporte `.json` de cada limpieza](#33-qué-contiene-el-reporte-json-de-cada-limpieza)
   - [3.4 Cómo se elige el frame de referencia](#34-cómo-se-elige-el-frame-de-referencia)
4. [Módulo 2 — Pipeline de Detección](#módulo-2--pipeline-de-detección)
   - [4.1 Qué se construyó (Módulo 2)](#41-qué-se-construyó-módulo-2)
   - [4.2 Flujo funcional de este módulo (Módulo 2)](#42-flujo-funcional-de-este-módulo-módulo-2)
   - [4.3 Cómo correr (Módulo 2)](#43-cómo-correr-módulo-2)
   - [4.4 Qué contiene el `Event Object` (Módulo 2)](#44-qué-contiene-el-event-object-módulo-2)
   - [4.5 Sugerencia automática de zonas (auto-ROI)](#45-sugerencia-automática-de-zonas-auto-roi)
   - [4.6 Submuestreo del análisis](#46-submuestreo-del-análisis)
5. [Módulo 3 — Trayectoria, Transporte In-Process y Backend Local](#módulo-3--trayectoria-transporte-in-process-y-backend-local)
   - [5.1 Captura de trayectoria continua (`PositionSample`)](#51-captura-de-trayectoria-continua-positionsample)
   - [5.2 Fuentes de frames: video limpio y cámara en vivo](#52-fuentes-de-frames-video-limpio-y-cámara-en-vivo)
   - [5.3 Transporte in-process (señales Qt)](#53-transporte-in-process-señales-qt)
   - [5.4 Edición de zonas (ROI) en la UI](#54-edición-de-zonas-roi-en-la-ui)
   - [5.5 Backend local (SQLite + heatmap)](#55-backend-local-sqlite--heatmap)
6. [Módulo 4 — Dashboard de Métricas](#módulo-4--dashboard-de-métricas)
   - [6.1 Qué muestra el dashboard](#61-qué-muestra-el-dashboard)
   - [6.2 Por qué el personal no cuenta en el mapa de calor](#62-por-qué-el-personal-no-cuenta-en-el-mapa-de-calor)
   - [6.3 Sesión de demostración](#63-sesión-de-demostración)
   - [6.4 Sesiones: cada análisis, sus propios números](#64-sesiones-cada-análisis-sus-propios-números)
7. [Seguridad en la carga de archivos](#7-seguridad-en-la-carga-de-archivos)
   - [Cámara en vivo](#cámara-en-vivo)
   - [Experiencia de usuario y accesibilidad](#experiencia-de-usuario-y-accesibilidad)
8. [Contratos de datos documentados](#8-contratos-de-datos-documentados)
9. [Privacidad por diseño](#9-privacidad-por-diseño)
10. [Sugerencias para continuar el desarrollo](#10-sugerencias-para-continuar-el-desarrollo)

---

## 1. Qué se construyó (visión general y estructura)

Una app de escritorio en **Python + PySide6** (Qt) con arquitectura en
capas para que cada módulo del reto (carga, detección, dashboard) sea una
pieza independiente y no un solo archivo gigante. El código se reorganizó
en subpaquetes por propiedad de equipo (ver [`MIGRATION.md`](MIGRATION.md)
para el historial de movimientos):

```
scapder-vision/
├── app/
│   ├── main.py                    # Punto de entrada de la aplicación
│   ├── ui/
│   │   ├── main_window.py         # Ventana principal (QTabWidget). Cada módulo
│   │   │                          # nuevo = una pestaña nueva (hoy: 3).
│   │   ├── zone_editor_tab.py     # Pestaña 2: dibujo/edición de zonas (ROI)
│   │   ├── dashboard_tab.py       # Pestaña 3: KPIs, timeline, heatmap, eventos
│   │   ├── theme.py               # Paleta y stylesheet Qt compartidos
│   │   └── widgets/
│   │       ├── header.py          #   Barra superior reutilizable (+ íconos vectoriales)
│   │       └── footer.py          #   Barra inferior: versión del motor + FPS/CPU en vivo
│   ├── core/
│   │   ├── ingestion/             # Team 1 — cámara/IoT e ingesta de frames
│   │   │   ├── video_loader.py    #   Carga de video + metadatos + validaciones de seguridad
│   │   │   ├── video_cleaner.py   #   Limpieza: frames negros/congelados + reencode
│   │   │   ├── workers.py         #   QThread: limpieza + preparación de sesión (frame + ROI)
│   │   │   ├── frame_picker.py    #   Elige el mejor frame de referencia (nitidez + menos gente)
│   │   │   └── frame_source.py    #   FrameSource: video limpio + mapping / cámara en vivo (stub)
│   │   ├── detection/             # Team 2 — pipeline de detección
│   │   │   ├── tracker.py         #   Detección + tracking con ByteTrack integrado (YOLOv11, clase 0 COCO)
│   │   │   ├── roi_suggester.py   #   Propone zonas de góndola sobre el frame de referencia
│   │   │   ├── pose.py            #   Estimación de pose corporal (17 keypoints)
│   │   │   ├── zone.py            #   Zonas + señales geométricas (ZoneManager, roles product/staff)
│   │   │   ├── state_machine.py   #   Máquina de estados IDLE→REACHING→HOLDING→taken/returned
│   │   │   ├── presence.py        #   DwellTracker: tiempo de permanencia por zona de producto
│   │   │   ├── staff.py           #   StaffZoneTracker: marca "empleado" al entrar a una zona staff
│   │   │   ├── frame_mapping.py   #   Traducción de timestamps limpio → original
│   │   │   ├── schemas.py         #   Contratos Pydantic (fuente de verdad)
│   │   │   ├── event_publisher.py #   Bus de eventos (file / stdout / in-process Qt)
│   │   │   ├── trajectory.py      #   Captura continua de posición (PositionSample)
│   │   │   ├── pipeline_worker.py #   QThread para correr el pipeline sin congelar la UI
│   │   │   └── pipeline.py        #   Orquestador frame a frame (consume FrameSource, interrumpible)
│   │   └── backend/               # Team 3 — almacenamiento y agregación
│   │       ├── event_store.py     #   SQLite local (eventos + muestras) + consultas agregadas del dashboard
│   │       ├── heatmap.py         #   Cuadrícula de densidad (grid + blur gaussiano)
│   │       ├── evaluation.py      #   Métricas precision/recall/F1 contra ground truth manual
│   │       └── demo_seed.py       #   Datos de demostración explícitos para el dashboard vacío
│   └── utils/
│       ├── config.py              # TODOS los parámetros ajustables del proyecto
│       └── security.py            # Sanitización de nombres, firma de archivo, timeout de lectura
├── data/
│   ├── processed/                 # Videos ya limpios, listos para el pipeline de CV
│   ├── zones/                     # Polígonos de zona (.json, esquema Zone) por video_id
│   ├── events/                    # Log local de eventos (.jsonl) para debug
│   ├── scapder_events.db          # SQLite del EventStore (se crea en tiempo de ejecución)
│   └── logs/                      # Miniaturas y logs locales
├── docs/
│   ├── event_schema.md            # Contrato de datos del bus (auto-generado)
│   ├── zone_schema.md             # Contrato de datos de zonas (auto-generado)
│   └── inteligencia-artificial.md # Documentación del pipeline de IA
├── scripts/
│   ├── run_pipeline_debug.py      # Debug visual sin UI (bboxes, keypoints, zonas)
│   ├── evaluate_pipeline.py       # Evalúa precision/recall/F1 contra un ground truth
│   ├── benchmark_pipeline.py      # Benchmark de rendimiento del pipeline
│   └── generate_schema_docs.py    # Genera docs/event_schema.md y docs/zone_schema.md
├── tests/                         # Tests unitarios (state machine, trayectoria, fuentes, backend...)
├── requirements.txt
├── run.sh / run.bat
└── README.md
```

### El flujo de la app: las tres pestañas son un solo camino

Las pestañas ya no son tres pantallas sueltas que había que alimentar a
mano una por una. Están encadenadas:

```
  Pestaña 1                     Pestaña 2                    Pestaña 3
  Carga y limpieza    ──────►   Zonas (ROI)      ──────►     Dashboard
                    session_ready              analysis_finished
```

1. **Cargar y limpiar** el video en la pestaña 1 (igual que antes).
2. Al terminar la limpieza, la app **elige sola un frame de referencia
   bueno** — nítido y con la góndola lo más despejada posible, en vez del
   arbitrario "frame al 10%" — y **propone zonas de góndola** sobre él.
3. Salta a la pestaña 2 con ese frame y esas zonas ya cargadas. El
   usuario las corrige, las acepta o dibuja las suyas, y presiona
   **"Iniciar análisis"**.
4. El pipeline recorre el video y **guarda todo en SQLite** bajo el
   `video_id` de esa sesión.
5. Al terminar, la app salta al **Dashboard**, ya posicionado en la
   sesión que se acaba de analizar.

Cada pestaña sigue siendo usable por su cuenta (se puede cargar un video
directamente en la 2 con "Cargar video", o abrir el dashboard sin haber
analizado nada), pero el camino natural ya no obliga a volver a buscar el
mismo archivo en cada pantalla.

Las pestañas **no se conocen entre sí**: se comunican por dos señales Qt
(`VideoIngestTab.session_ready` y `ZoneEditorTab.analysis_finished`) que
`MainWindow` conecta. Agregar una pestaña intermedia no obliga a tocar las
existentes.

### Flujo funcional de este módulo (Módulo 1)

1. **Cargar video(s)** → `video_loader.load_video()` abre el archivo,
   valida formato/peso/duración, **valida que el contenido realmente sea
   un video** (no solo la extensión, ver [sección 7](#7-seguridad-en-la-carga-de-archivos))
   y extrae metadatos (resolución, fps, duración, tamaño) sin recorrer
   todo el video (rápido).
2. **Vista previa** → `video_loader.extract_thumbnail()` saca un frame
   al 10% de la duración para mostrarlo en el panel derecho.
3. **Limpiar** → `video_cleaner.clean_video()` recorre frame a frame:
   - Descarta frames negros (cámara tapada / corte de señal).
   - Descarta frames "congelados" (cámara trabada repitiendo el mismo
     frame más de N veces seguidas).
   - Reencoda todo a un codec/formato consistente.
   - Devuelve un reporte (frames leídos, escritos, descartados por cada
     motivo) que se muestra en la interfaz.
   - Además, guarda automáticamente ese reporte como un archivo `.json`
     junto al video limpio (mismo nombre, extensión `.json`), incluyendo
     el mapeo `frame_mapping`: la correspondencia entre cada frame del
     video limpio y su posición/timestamp en el video original. Esto es
     necesario porque al quitar frames negros/congelados los índices se
     corren, y esa correspondencia no se puede reconstruir después de
     limpiar — sin este archivo, un evento detectado en el frame N del
     video limpio no se podría ubicar en el video original de 12 horas.
4. Todo el paso 3 corre en `app/core/ingestion/workers.py` (un
   `QThread`), para que la ventana no se congele mientras se procesa un
   video largo. La barra inferior de la pestaña muestra **FPS y % de CPU
   en vivo** (`app/ui/widgets/footer.py`, vía `psutil`) mientras corre.

La separación es intencional: `video_loader.py` y `video_cleaner.py`
**no importan nada de Qt** — se pueden probar por consola, reutilizar en
un script de línea de comandos, o llamar después desde el módulo de
detección, sin acoplarlos a la interfaz.

- **Flujo completo**: video original → carga segura + limpieza
  (`Módulo 1`) → pipeline de detección (`Módulo 2`) → trayectoria +
  eventos → SQLite/heatmap (`Módulo 3`) → Dashboard (`Módulo 4`).
- **Hilos**: la UI nunca corre trabajo pesado; limpieza y detección
  corren en `QThread` workers que reportan por señales Qt y pueden
  **interrumpirse sin esperar a que terminen** (ver botón "Reiniciar" en
  [5.4](#54-edición-de-zonas-roi-en-la-ui)).
- **Transporte de eventos**: in-process vía señales Qt (MVP). Los modos
  `file`/`stdout` quedan para debug. Un transporte de red (WebSocket/MQTT)
  es trabajo futuro explícitamente fuera de alcance — ver
  [`docs/event_schema.md`](docs/event_schema.md).

---

## 2. Cómo correr el proyecto

**Requisitos:** Python 3.10+ instalado localmente. Esta es una app de
escritorio (no corre en el navegador).

**Linux / Mac**

```bash
chmod +x run.sh
./run.sh
```

**Windows**

```bat
.\run.bat
```

(Ambos dentro de terminal en VS)
Cualquiera de los dos scripts:

1. Crea un entorno virtual (`venv/`) si no existe.
2. Instala `PySide6`, `opencv-python`, `numpy`, `ultralytics`, `shapely`,
   `pydantic` y `psutil` desde `requirements.txt`.
3. Lanza la app con `python -m app.main`.

**Después, cada vez que se quiera ejecutar la app**

1. `.\venv\Scripts\Activate.ps1` (Windows) o `source venv/bin/activate` (Linux/Mac)
2. Lanza la app con `python -m app.main`.

**Uso dentro de la app:**

- Pestaña _"1. Carga y Limpieza de Video"_:
  - Botón _"📁 Haz clic para buscar un archivo"_ → selecciona uno o varios
    archivos (se validan antes de aceptarse, ver [sección 7](#7-seguridad-en-la-carga-de-archivos)).
  - Click en un video de la lista → ver metadatos + miniatura a la derecha.
  - Botones _"Limpiar sel."_ / _"Limpiar todos"_ → procesa en segundo
    plano; el resultado queda en `data/processed/`.
  - **Al terminar la limpieza** la app prepara la sesión sola (elige el
    frame de referencia, propone zonas) y **salta a la pestaña 2**. No hay
    que volver a buscar el archivo.
- Pestaña _"2. Edición de Zonas (ROI)"_:
  - Las **zonas propuestas** llegan dibujadas con línea punteada y en
    verde agua. **No están guardadas**: aparecen en la lista como
    _"Sugerida (sin guardar)"_ hasta que se decida qué hacer con ellas.
    - _"Aceptar sugeridas"_ → las guarda todas tal cual.
    - Click en una → pasa al lienzo como polígono editable; se ajusta y
      "Guardar zona" la confirma.
    - _"Descartar sugeridas"_ → las borra de la pantalla y se dibuja a mano.
  - Botón _"Cargar video"_ → sigue existiendo para trabajar sobre un video
    cualquiera sin pasar por la pestaña 1.
  - **Rol de la zona**: combo con dos opciones — _"Góndola / producto"_
    (azul) o _"Personal de la tienda"_ (ámbar) — cada click sobre el
    frame agrega un vértice del color del rol activo.
  - Clic en una zona ya guardada de la lista **la carga para editarla**:
    modifica sus puntos y "Guardar zona" sobreescribe el mismo archivo
    (no crea uno duplicado).
  - Botón _"▶ Iniciar análisis"_ → corre el pipeline completo sobre el
    video: anota cajas/keypoints/estado sobre el lienzo **y guarda los
    eventos, permanencias y muestras de posición en la base local**. Al
    terminar salta al Dashboard con esa sesión.
  - Botón _"Reiniciar"_ → interrumpe el análisis en curso (sin esperar a
    que el video termine) y lo vuelve a correr desde el inicio **sobre el
    mismo video**, sin pedir cargar uno nuevo.
- Pestaña _"3. Dashboard de Métricas"_ (ver [Módulo 4](#módulo-4--dashboard-de-métricas)):
  - Selector de sesión (`video_id`) + KPIs, timeline, ranking de zonas,
    mapa de calor y feed de eventos recientes, todo leído en vivo desde
    `EventStore` (auto-refresco cada 3s) **y acotado a la sesión elegida**.
  - Botón de la barra superior → abre el mapa de calor a tamaño completo.
  - Botón _"Cargar sesión de demostración"_ → siembra datos sintéticos
    marcados como demo, solo si la sesión aún no tiene eventos reales.
  - Si la sesión tiene datos sembrados, una **banda ámbar permanente** lo
    dice, y el botón _"Borrar datos de demo"_ los elimina sin tocar los
    reales.

---

# Módulo 1 — Carga y Limpieza de Video

## 3.1 Qué se construyó (Módulo 1)

Ya descrito en la sección [1](#1-qué-se-construyó-visión-general-y-estructura):
carga segura, validación, limpieza (frames negros/congelados), reencode y
el reporte `.json` con el `frame_mapping` — la pieza que conecta cada
frame limpio con su momento en el video original.

## 3.2 Cómo limitar duración y peso de los videos cargados

Ya se agregaron los límites al código base. Para **cambiar los valores**,
edita únicamente este archivo — no hay que tocar nada más:

📄 **`app/utils/config.py`**

```python
# Duración máxima permitida en segundos. None = sin límite.
MAX_VIDEO_DURATION_SEC = 43200       # 12 horas

# Peso máximo permitido en MB. None = sin límite.
MAX_VIDEO_SIZE_MB = 10000            # 10 GB

# Resolución y frame_count máximos (defensa contra headers manipulados)
MAX_VIDEO_WIDTH = 7680
MAX_VIDEO_HEIGHT = 4320
MAX_VIDEO_FRAME_COUNT = 20_000_000

# Segundos que se espera a OpenCV antes de abortar la carga
VIDEO_LOAD_TIMEOUT_SEC = 20
```

- Para permitir videos más largos: sube `MAX_VIDEO_DURATION_SEC` (está
  en segundos).
- Para permitir archivos más pesados: sube `MAX_VIDEO_SIZE_MB`.
- Para quitar el límite por completo: pon `None` en cualquiera de los dos.

La validación real ocurre en `app/core/ingestion/video_loader.py`, dentro
de la función `load_video()` — ver [sección 7](#7-seguridad-en-la-carga-de-archivos)
para el detalle completo de qué valida y en qué orden.

Si un video excede alguno de los límites (o no pasa alguna de las
validaciones de seguridad), la app no lo carga y muestra el motivo en el
log de la interfaz (no se congela ni truena).

## 3.3 Qué contiene el reporte `.json` de cada limpieza

Cada vez que se limpia un video, junto al video de salida en
`data/processed/` se genera un archivo con el mismo nombre y extensión
`.json` (por ejemplo `mi_video_clean.json`). Ejemplo real de contenido:

```json
{
  "frames_read": 500,
  "frames_written": 480,
  "black_frames_removed": 15,
  "frozen_frames_removed": 5,
  "output_fps": 30.0,
  "output_resolution": [1280, 720],
  "output_path": "data/processed/mi_video_clean.mp4",
  "frame_mapping": [
    {"clean_frame": 0, "original_frame": 0, "original_timestamp_sec": 0.0},
    {"clean_frame": 1, "original_frame": 1, "original_timestamp_sec": 0.033},
    {"clean_frame": 2, "original_frame": 4, "original_timestamp_sec": 0.133}
  ]
}
```

- Los primeros campos (`frames_read`, `frames_written`, etc.) son el
  resumen general de la limpieza.
- `frame_mapping` es la parte clave para las siguientes etapas del
  pipeline: por cada frame que quedó en el video limpio, indica qué
  posición y qué segundo tenía ese mismo contenido en el video
  **original** (antes de quitar frames negros/congelados). Sin esto, un
  evento detectado en el video limpio no se podría ubicar en el video
  original de hasta 12 horas.
- Si el video no tenía frames negros ni congelados, `frame_mapping`
  simplemente queda 1 a 1 (`clean_frame` == `original_frame` en cada
  fila) — se genera igual, por consistencia entre todos los videos
  procesados.

## 3.4 Cómo se elige el frame de referencia

El frame sobre el que se dibujan las zonas era siempre el que estuviera al
10% de la duración. Ese frame es arbitrario: puede estar movido, mal
iluminado, o con tres personas tapando justamente la góndola que se quiere
marcar.

`app/core/ingestion/frame_picker.py` muestrea 12 frames repartidos entre
el 5% y el 95% del video limpio (los extremos suelen traer fundidos y
ajustes de exposición) y puntúa cada candidato por dos criterios:

- **Nitidez** — varianza del Laplaciano. Un frame movido tiene los bordes
  suavizados y por lo tanto varianza baja. No es un criterio estético: los
  bordes son exactamente lo que después usa el sugeridor de ROI para
  encontrar los estantes.
- **Ocupación** — cuánta gente hay delante, contada con el mismo YOLO del
  pipeline. Cada persona detectada penaliza el score, así que entre dos
  frames de nitidez parecida gana el que tenga la góndola despejada.

La nitidez se normaliza **dentro del propio video**: su escala absoluta
depende de la cámara, la resolución y la compresión, así que un umbral
fijo no serviría entre videos distintos.

El detector se inyecta como parámetro en vez de importarse, así que el
módulo no arrastra `ultralytics` y se puede probar sin modelos. Si el
detector no está disponible, la elección se hace solo por nitidez en vez
de fallar.

---

# Módulo 2 — Pipeline de Detección

Módulo que realiza el análisis computacional en video: detecta personas,
las sigue entre frames, estima la pose corporal, chequea zonas geométricas
de interacción con estantes, mide dwell time, distingue personal de
clientes y genera eventos cuando se detectan acciones (tomar/devolver
producto). Diseñado como una capa puramente computacional: sin Qt, sin
interfaz — solo cálculos y eventos emitidos a través de un bus generalizado.

## 4.1 Qué se construyó (Módulo 2)

Un pipeline de visión computacional con una arquitectura modular donde
cada componente tiene una responsabilidad clara (todos en
`app/core/detection/`):

```
app/core/detection/
├── tracker.py           # Detección + tracking con ByteTrack integrado (YOLOv11, clase 0 COCO)
├── pose.py              # Estimación de pose corporal (17 keypoints COCO)
├── zone.py              # Validación de zonas y cálculo de señales geométricas (roles product/staff)
├── state_machine.py     # Máquina de estados: IDLE → REACHING → HOLDING → taken/returned
├── presence.py          # DwellTracker: tiempo de permanencia por zona de producto
├── staff.py             # StaffZoneTracker: marcado "sticky" de empleados
├── frame_mapping.py     # Traducción de timestamps desde video limpio al original
├── schemas.py           # Contratos Pydantic para validación de datos
├── event_publisher.py   # Bus de eventos (archivo / stdout / in-process Qt)
├── trajectory.py        # Captura continua de posición (PositionSample, Módulo 3)
├── pipeline_worker.py   # QThread para correr el pipeline sin bloquear la UI (interrumpible)
└── pipeline.py          # Orquestador que corre todo el flujo frame a frame
```

## 4.2 Flujo funcional de este módulo (Módulo 2)

1. **Cargar frames** → `pipeline.run(source)` acepta una `FrameSource`:
   un video limpio de `data/processed/` con su `.json` de `frame_mapping`
   (comportamiento original, construido por `VideoFileFrameSource`) o una
   fuente en vivo (stub de Team 1). El pipeline ya no sabe si la entrada
   es archivo o cámara. `run()` acepta además un `should_stop()` opcional,
   consultado en cada frame — permite cancelar un análisis en curso sin
   esperar a que el video termine (lo usa `DetectionPipelineWorker` vía
   `QThread.isInterruptionRequested`, conectado al botón "Reiniciar" de
   la pestaña 2).

2. **Tracking de personas** → `tracker.track(frame, frame_index)` detecta
   y sigue personas usando YOLOv11 + ByteTrack. Cada persona recibe un
   `track_id` único que persiste a lo largo del video (se reinicia en cada
   ejecución, no es identidad persistente entre sesiones).

3. **Estimación de pose** → `pose_estimator.estimate(frame, tracked_people)`
   calcula 17 keypoints COCO (muñecas, codos, hombros, caderas, etc.) y
   los asocia a cada persona trackeada por proximidad de bounding box + IoU.

4. **Chequeo geométrico de zona** → `check_zone_signal(pose, zones)` verifica:
   - ¿Está la muñeca dentro del polígono de la zona? (`wrist_inside`)
   - ¿Está el brazo extendido? (`arm_extended`, usando relación
     distancia(muñeca, hombro) / distancia(hombro, codo) ≥ threshold)
   - **Filtro de confianza**: ambos keypoints (muñeca y hombro) deben tener
     confianza ≥ `MIN_KEYPOINT_CONFIDENCE` (0.3 por defecto) para ser válidos.

5. **Máquina de estados** → `state_machine.process(zone_signals)` sigue la
   interacción de cada persona con cada zona según este flujo:
   - **IDLE** → si `wrist_inside=True` y `arm_extended=True`, transiciona a
     **REACHING**.
   - **REACHING** → si el brazo se mantiene extendido dentro, incrementa un
     contador. Al alcanzar `MIN_FRAMES_REACHING_TO_HOLDING` (5 frames por
     defecto), transiciona a **HOLDING**. **Detección de atasco**: si la
     muñeca sigue dentro pero el brazo NO está extendido durante más de
     `MAX_SECONDS_STUCK_REACHING` (1 segundo = ~30 frames a 30 fps), la
     máquina resetea a IDLE sin emitir evento — evita falsos positivos.
   - **HOLDING** → si la muñeca permanece dentro durante al menos
     `MIN_FRAMES_HOLDING` (8 frames), y luego sale de la zona, emite un
     evento. La primera interacción de una persona con una zona en la
     sesión se emite como `action="taken"`; las siguientes **alternan**
     `"returned"`/`"taken"` (heurístico: no hay detección de producto en
     sí, así que no se puede saber con certeza si "devolvió" o "volvió a
     tomar" — alternar es la aproximación razonable sin esa información).
   - Pérdida de tracking: si una persona desaparece durante más de
     `MAX_FRAMES_MISSING_TO_RESET` (10 frames), todos sus estados se
     reinician a IDLE sin emitir eventos.

6. **Dwell time y detección de personal** (portados de la rama `corredor`
   y adaptados a los nombres de campo de este proyecto):
   - `DwellTracker` (`presence.py`) mide cuánto tiempo permanece cada
     persona dentro de cada zona de producto y emite un `DwellRecord`
     (entrada, salida, duración) al salir.
   - `StaffZoneTracker` (`staff.py`) marca como `is_employee=True` a
     cualquier persona que haya entrado alguna vez a una zona de tipo
     `staff` — el marcado es **sticky**: una vez empleado en la sesión, se
     queda marcado el resto del video. Ese flag viaja en todos los
     eventos, dwell records y muestras de posición de esa persona desde
     ese momento.

7. **Traducción de timestamps** → la `FrameSource` devuelve cada frame con
   su timestamp ya resuelto: `VideoFileFrameSource` usa `frame_mapping.py`
   para convertir el índice del video limpio al segundo absoluto del video
   original (crítico para ubicar eventos en la timeline original); una
   fuente en vivo usaría wall-clock sin mapeo.

8. **Publicación de eventos** → `event_publisher.publish(event)` emite cada
   evento (`InteractionEvent`, `PositionSample`, `DwellRecord`) según el
   modo configurado:
   - `"file"`: guarda JSON local en `data/events/` (respaldo persistente).
   - `"stdout"`: imprime en consola (para debug).
   - `"inprocess"`: señal Qt `Signal(dict)` — transporte del MVP, ver Módulo 3.

## 4.3 Cómo correr (Módulo 2)

**Script de debug visual (sin interfaz de usuario):**

```bash
python -m scripts.run_pipeline_debug --video data/processed/mi_video_clean.mp4
```

Visualiza en tiempo real:
- Bounding boxes de personas detectadas, coloreadas por **estado de
  interacción**: azul = IDLE, amarillo = REACHING, rojo = HOLDING.
- Keypoints de pose superpuestos como **círculos amarillos**,
  únicamente si superan el umbral de confianza (`MIN_KEYPOINT_CONFIDENCE`,
  0.3 por defecto); los que no lo superan simplemente **no se dibujan**.
- Polígonos de zonas siempre en verde, con su nombre.
- Eventos de interacción impresos en consola a medida que ocurren.

La misma visualización está disponible **dentro de la app**, en la
pestaña 2, con el botón _"Ver detección (debug)"_.

**Evaluar precisión contra un ground truth manual:**

```bash
python -m scripts.evaluate_pipeline --video data/processed/mi_video_clean.mp4 --ground-truth mi_gt.json
```

Usa `app/core/backend/evaluation.py` (emparejamiento por `zone_id` +
`action` dentro de una ventana temporal) para calcular precision, recall
y F1 — la misma métrica que se ve resumida en el Dashboard.

**Ejecutar tests unitarios:**

```bash
pytest tests/ -v
```

Verifica:
- Transiciones correctas de máquina de estados (IDLE → REACHING → HOLDING).
- Detección de atascos en REACHING (resetea a IDLE sin evento).
- Pérdida de tracking y reset automático.
- Independencia entre múltiples personas y zonas simultáneamente.
- Trayectoria continua (`PositionSample`), fuentes de frames, dwell time,
  detección de personal, evaluación y backend.

## 4.4 Qué contiene el `Event Object` (Módulo 2)

Un objeto `InteractionEvent` serializado a JSON se ve así:

```json
{
  "track_id": 42,
  "zone_id": "zone_1",
  "action": "taken",
  "timestamp": 125.4,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "is_employee": false
}
```

- `track_id` (int): identificador efímero de la persona en esta sesión de
  video (reinicia en 0 para cada video, no es persistente entre sesiones).
- `zone_id` (str): identificador de la zona de góndola donde ocurrió la
  interacción (ej: `"zone_1"`). Definido por el usuario en el editor
  manual de zonas (pestaña 2 de la app).
- `action` (str, enum `"reaching" | "holding" | "taken" | "returned"`):
  la máquina de estados solo emite `"taken"`/`"returned"` (ver
  [4.2, paso 5](#42-flujo-funcional-de-este-módulo-módulo-2)); `"reaching"`/`"holding"`
  quedan reservados para una futura granularidad más fina.
- `timestamp` (float): segundos desde el inicio del video **original** (antes
  de limpieza), alineado con la duración real de la cámara. Calculado usando
  `frame_mapping` para reproducibilidad exacta.
- `event_id` (str, UUID): identificador único del evento, generado al
  instante. Útil para auditoría y deduplicación si un evento se publica a
  múltiples destinos.
- `is_employee` (bool): `True` si `StaffZoneTracker` marcó a este track
  como empleado en algún momento de la sesión — se usa para separar
  interacción de cliente vs. personal en el Dashboard y, sobre todo, para
  **excluir al personal del mapa de calor** (ver [6.2](#62-por-qué-el-personal-no-cuenta-en-el-mapa-de-calor)).

Ejemplo de un archivo de log generado en `data/events/`:

```json
[
  {"track_id": 1, "zone_id": "zone_1", "action": "taken", "timestamp": 12.5, "event_id": "...", "is_employee": false},
  {"track_id": 2, "zone_id": "zone_1", "action": "taken", "timestamp": 15.3, "event_id": "...", "is_employee": false},
  {"track_id": 3, "zone_id": "zone_2", "action": "returned", "timestamp": 18.7, "event_id": "...", "is_employee": true}
]
```

## 4.5 Sugerencia automática de zonas (auto-ROI)

YOLO-COCO no tiene una clase "estantería", así que no hay un detector
directo que resuelva esto. `app/core/detection/roi_suggester.py` combina
dos señales que se refuerzan entre sí:

1. **Estructura** (`boxes_from_edges`) — una góndola es una caja
   rectangular con baldas horizontales muy marcadas. Canny saca los
   bordes (con umbrales derivados de la mediana del frame, para que
   funcione igual en una cámara oscura y en una bien iluminada), una
   dilatación con kernel ancho y bajo (25x3) une los bordes de cada balda
   en una banda continua sin pegar entre sí dos góndolas apiladas, y los
   contornos de esas bandas dan rectángulos candidatos.
2. **Contenido** (`boxes_from_products`) — donde hay producto hay góndola.
   Las clases COCO que el YOLO ya cargado sí detecta y que en una tienda
   son producto de estante (botellas, tazas, cuencos, libros, floreros) se
   agrupan por cercanía: cada caja se expande un margen y las expandidas
   que se tocan quedan en el mismo grupo. Es clustering espacial sin tener
   que elegir un número de clusters de antemano.

Los candidatos se fusionan por solapamiento (`merge_boxes` une en su
**unión**, no descarta el más débil: dos baldas de la misma góndola deben
terminar en una zona que cubra ambas) y se filtran por tamaño y forma:
demasiado chico es ruido de bordes, demasiado grande es la pared entera, y
demasiado alto y angosto es una columna. Los umbrales están en `config.py`
(`ROI_SUGGEST_*`).

**Son sugerencias, no zonas guardadas.** El módulo no escribe nada en
disco: la pestaña 2 las muestra punteadas para que el usuario las corrija,
acepte o descarte. Un heurístico de visión clásica sobre CCTV se equivoca
a menudo, y ensuciar `data/zones/` con polígonos que nadie revisó sería
peor que no sugerir nada.

Si el detector de producto no está disponible o falla, la sugerencia sale
igual usando solo la estructura de bordes.

## 4.6 Submuestreo del análisis

El análisis lanzado desde la UI procesa 1 de cada `ANALYSIS_FRAME_STRIDE`
frames (3 por defecto, en `config.py`). Los frames intermedios se saltan
con `cap.grab()` — se avanza el decodificador sin decodificar la imagen,
que es lo caro — pero **el contador de frames sigue avanzando de uno en
uno**, así que el `frame_mapping` y con él el timestamp del video original
siguen siendo exactos.

Los umbrales de la máquina de estados están expresados en frames, así que
el `fps` que recibe se divide por el salto. Sin ese ajuste, "1 segundo
atascado en REACHING" pasaría a significar 3 segundos de video real.

Subir `ANALYSIS_FRAME_STRIDE` a 1 procesa todos los frames: máxima
fidelidad de la máquina de estados y del dwell time, bastante más lento en
CPU sin GPU.

---

# Módulo 3 — Trayectoria, Transporte In-Process y Backend Local

Este módulo captura la posición continua de cada persona (la base del
heatmap), desacopla la entrada del pipeline ("solo video limpio") y da un
transporte de eventos sin red hacia el dashboard.

## 5.1 Captura de trayectoria continua (`PositionSample`)

Los eventos de interacción (`InteractionEvent`) son **discretos** (se
disparan cuando alguien toma un producto). Para un heatmap de
"dónde circula y dónde no la gente" se necesitan **muestras continuas**:

- `trajectory.py` (`TrajectoryCapture`) registra, por cada frame procesado
  y por cada persona activa: `track_id`, `frame_index`, timestamp original
  (traducido por la `FrameSource`, sin duplicar `frame_mapping.py`), la
  posición del pie — el **bottom-center del bbox** como proxy razonable —
  y el flag `is_employee` vigente en ese instante.
- Se emite como su propio esquema ligero `PositionSample`
  (`schemas.py`), **sin sobrecargar** `InteractionEvent`, por el **mismo**
  `EventPublisher` — el receptor no necesita dos transportes distintos.
- La frecuencia se ajusta con `TRAJECTORY_SAMPLE_EVERY_N_FRAMES` en
  `config.py` (por defecto 1 = todos los frames).

## 5.2 Fuentes de frames: video limpio y cámara en vivo

`app/core/ingestion/frame_source.py` define la interfaz `FrameSource`:

- `VideoFileFrameSource(video_path)` — comportamiento original: video
  limpio + `frame_mapping.json` sidecar; traduce timestamps al video
  original. `pipeline.run()` y `pipeline.run_video(path)` lo usan tal cual.
- `LiveFrameSource` — **stub para Team 1** (webcam/RTSP): sin video
  original que mapear, timestamps wall-clock que pasan sin cambios.

El pipeline no tiene ninguna rama "si es archivo vs si es cámara" dentro
del bucle: solo consume `FrameSource.next_frame()`.

## 5.3 Transporte in-process (señales Qt)

`app/core/detection/event_publisher.py`:

- `EventPublisher.publish(event)` acepta **cualquier modelo Pydantic**
  (no solo `InteractionEvent`) — un solo bus para eventos, muestras y
  registros de dwell.
- `InProcessPublisher`: emite `event_emitted = Signal(dict)` con
  `event.model_dump()`; cualquier widget se conecta directamente (las
  conexiones entre hilos se ponen en cola solas).
- `DetectionPipelineWorker` (`pipeline_worker.py`) corre el pipeline en un
  `QThread` (mismo patrón que `workers.py` del Módulo 1), así el stream
  frecuente de `PositionSample` nunca bloquea la UI. Puede interrumpirse
  en caliente vía `requestInterruption()` sin que quien lo pide tenga que
  esperar a que el hilo termine.
- Los modos `file` y `stdout` siguen intactos para debug/logging.
- **Explícitamente fuera de alcance del MVP**: un transporte de red
  (WebSocket o MQTT) es trabajo futuro razonable si esto corre en varias
  máquinas — documentado en `docs/event_schema.md`.

## 5.4 Edición de zonas (ROI) en la UI

`app/ui/zone_editor_tab.py` (pestaña "2. Edición de Zonas (ROI)"):

- Carga un video y usa la utilidad `extract_thumbnail` del Módulo 1 como
  frame de referencia (a resolución completa).
- **Dos roles de zona**, seleccionables antes de dibujar (combo "Rol de
  la zona"): `product` (góndola, dwell time de cliente — se dibuja en
  azul) y `staff` (personal de la tienda, aparte de las de góndola — se
  dibuja en ámbar). El color de los puntos en construcción cambia según
  el rol activo, para que sea obvio para cuál de los dos se está dibujando.
- Cada click agrega un vértice del polígono; los vértices se guardan en
  coordenadas del frame **original** (no del lienzo escalado).
- **Edición in-place**: seleccionar una zona ya guardada de la lista
  carga sus puntos en el lienzo para modificarlos; "Guardar zona"
  sobreescribe el mismo `zone_id.json` en vez de crear uno nuevo.
- Se guarda con el **`ZoneManager` existente** (`app/core/detection/zone.py`)
  → `data/zones/<video_id>/<zone_id>.json`, sin inventar un formato nuevo
  (ver `docs/zone_schema.md`). `ZoneManager.normalize_video_id()` unifica
  el video crudo y su versión `_clean` bajo el mismo `video_id` — evita
  crear dos carpetas de zonas distintas para lo que en realidad es la
  misma sesión.

## 5.5 Backend local (SQLite + heatmap)

`app/core/backend/`:

- `event_store.py` — `EventStore`: tablas `events`, `position_samples` y
  `dwell_records` en SQLite local (`data/scapder_events.db`,
  `EVENT_STORE_DB_PATH` en `config.py`); `connect_store_to_publisher()`
  suscribe el almacén a la señal de `InProcessPublisher` — persistencia
  automática sin red. Expone también las consultas agregadas que consume
  el Dashboard (`get_summary`, `get_zone_breakdown`, `get_timeline`,
  `get_recent_events`, `get_position_samples`).
- `heatmap.py` — `build_density_grid()`: convierte `PositionSample`
  acumuladas en una cuadrícula 2D (`numpy` + `cv2.GaussianBlur`, no
  conteos crudos) lista para pintar.
- `evaluation.py` — precision/recall/F1 de los eventos predichos contra
  un ground truth manual (usado por `scripts/evaluate_pipeline.py` y
  resumido en el Dashboard).
- `demo_seed.py` — genera una sesión sintética (eventos + dwell +
  trayectorias) **estructuralmente idéntica** a la real, solo para que el
  Dashboard sea demostrable antes de correr el pipeline completo; nunca
  se activa automáticamente (botón explícito, marcado como demo en la UI).

---

# Módulo 4 — Dashboard de Métricas

`app/ui/dashboard_tab.py` (pestaña "3. Dashboard de Métricas"). A
diferencia del resto de la UI, este tab lee directamente del `EventStore`
real (SQLite) — no hay datos mockeados en el código del widget.

## 6.1 Qué muestra el dashboard

- **KPIs**: interacciones totales, tasa de toma neta (`taken` vs.
  `returned`), dwell promedio, % de interacción de personal y zonas
  activas — cada uno con una mini serie de tendencia.
- **Timeline**: `taken`/`returned` agrupados en buckets de 30s
  (`EventStore.get_timeline`).
- **Desempeño por zona**: barras `taken`/`returned` + dwell promedio por
  zona de producto, con nombre real (leído de `ZoneManager`).
- **Mapa de calor de circulación de clientes**: construido con
  `build_density_grid` a partir de `PositionSample`, dibujado sobre el
  contorno real de cada zona (sólido = producto, punteado = personal). Se
  relee del disco en cada refresco (~3s), así una edición de zona en la
  pestaña 2 se refleja sin pasos extra. Un botón en la barra superior lo
  abre a tamaño completo.
- **Feed de eventos recientes**: últimos 15 eventos, con track, zona,
  acción y timestamp.
- **Panel de precisión del pipeline**: precision/recall/F1 (ver `evaluation.py`).

## 6.2 Por qué el personal no cuenta en el mapa de calor

`StaffZoneTracker` marca a un track como `is_employee=True` de forma
**sticky**: una vez que alguien pisa la zona de personal, todas sus
muestras de posición durante el resto de la sesión llevan ese flag —
incluidas las que genera reponiendo una góndola, es decir, exactamente
donde también camina un cliente.

Si esas muestras se contaran igual que las de un cliente, un empleado
parado horas en el mismo punto (caja, mostrador, reponiendo un estante)
generaría una mancha de calor artificial que no representa interés real
de cliente — el dato quedaría sesgado. Por eso:

- `EventStore.get_position_samples(exclude_employees=True)` — **default**
  — descarta esas muestras antes de construir la cuadrícula de densidad.
- La zona de personal se sigue dibujando sobre el heatmap (contorno
  punteado ámbar), pero solo como referencia geométrica de dónde está esa
  zona — no aporta densidad.
- Se puede pedir explícitamente `exclude_employees=False` (por ejemplo,
  para un análisis interno de circulación de personal) sin tocar el resto
  del pipeline.

## 6.3 Sesión de demostración

El botón _"Cargar sesión de demostración"_ siembra (`demo_seed.py`)
eventos, dwell records y trayectorias sintéticas — usando las zonas
**reales** ya guardadas para esa sesión — para poder enseñar el tablero
antes de haber corrido ningún análisis. Solo está disponible si la sesión
no tiene todavía eventos de un análisis real.

Todo lo que se siembra queda marcado con `is_demo = 1` en la base, y eso
cambia dos cosas frente a la versión anterior:

- Mientras haya filas sembradas, el dashboard muestra una **banda ámbar
  permanente** que dice cuántos de los eventos mostrados son sintéticos.
  Antes, sembrar la demo hacía desaparecer el aviso y los números pasaban
  a presentarse como si vinieran de un video — que es exactamente lo que
  no puede pasar delante de un evaluador.
- El botón _"Borrar datos de demo"_ elimina **solo** esas filas. Los datos
  de un análisis real conviven en la misma base sin que la demo los toque.

## 6.4 Sesiones: cada análisis, sus propios números

Las tres tablas (`events`, `position_samples`, `dwell_records`) guardan el
`video_id` de la corrida que las generó, y todas las consultas agregadas
lo aceptan como filtro. El selector "Sesión" del dashboard filtra de
verdad: KPIs, timeline, ranking, tabla de eventos y mapa de calor
corresponden al video seleccionado.

Antes, ese selector solo cambiaba qué polígonos se dibujaban encima del
heatmap: los totales sumaban todos los videos analizados alguna vez, en
un mismo número.

Detalles de implementación que importan al correrlo:

- **Migración automática**: una base creada por la versión anterior gana
  las columnas nuevas con `ALTER TABLE` al abrirla, sin perder filas. Las
  antiguas quedan con `video_id` vacío.
- **Escritura por lotes**: `EventStore` hace commit cada 50 escrituras en
  vez de una por fila. El pipeline publica una `PositionSample` por
  persona y por frame; con commit por fila, el disco se volvía el cuello
  de botella del análisis. `flush()` cierra el lote pendiente al terminar.
- **Modo WAL**: el dashboard lee la misma base que el análisis está
  escribiendo. Sin WAL, cada escritura bloqueaba a los lectores.
- **Índices** sobre `(video_id, timestamp)` y `(video_id, zone_id)`: el
  dashboard refresca cada 3 segundos y antes hacía un scan completo.
- **Resolución del frame**: el mapa de calor lee `output_resolution` del
  reporte `.json` de la limpieza en vez de asumir 1280x720 — con un video
  4K, las muestras y los polígonos quedaban en escalas distintas y el
  heatmap aparecía desalineado respecto a las zonas.

---

## Cámara en vivo

La aplicación analiza tanto un video ya limpiado como una **cámara en
directo**: webcam local, cámara IP por RTSP, o MJPEG por HTTP (que es lo
que sirven las apps que convierten un móvil en cámara IP).

En la pestaña 1, con la fuente en **IP CAMERA**, el campo acepta una
dirección (`rtsp://…`, `http://…`) o el número de una webcam local — `0`
es la integrada. Al conectar, la aplicación captura un frame de
referencia, propone zonas sobre él y salta a la pestaña 2, igual que con
un archivo.

### Qué cambia respecto a un archivo

| | Archivo | Cámara en vivo |
|---|---|---|
| Timestamp | Segundo del video **original**, vía `frame_mapping` | Segundos desde que se conectó (reloj monótono) |
| Fin | El video se acaba | No termina: hay que **detenerlo** |
| Progreso | Porcentaje real | Barra indeterminada + fotogramas procesados |
| Submuestreo | 1 de cada `ANALYSIS_FRAME_STRIDE` | No aplica: el búfer está en 1 y cada lectura da el frame más reciente |

El botón de análisis de la pestaña 2 alterna entre **Analizar en vivo** y
**Detener análisis**. Sin esa parada explícita no habría forma de llegar
a los resultados: el stream no se acaba solo.

**Se pierde la trazabilidad al original.** Es la contrapartida honesta de
analizar en directo: no existe una grabación a la que volver, así que los
eventos quedan referidos al reloj de la sesión y no a un minuto concreto
de un archivo. Conviene decirlo al enseñarlo, porque la trazabilidad es
uno de los puntos fuertes del modo con archivo.

### Detalles que hacen que funcione en la práctica

- **RTSP sobre TCP.** Por UDP, que es el default, el Wi-Fi pierde
  paquetes y la imagen llega troceada o no llega.
- **Búfer de captura en 1.** OpenCV acumula frames mientras el pipeline
  procesa; sin bajarlo, el análisis se va quedando cada vez más atrás del
  tiempo real.
- **Una lectura fallida no corta la sesión.** Una cámara por Wi-Fi falla
  frames sueltos y sigue viva: se reintenta ~2 segundos antes de dar el
  stream por muerto.
- **El frame de referencia descarta los primeros cuadros.** Una webcam
  entrega los primeros con la exposición todavía ajustándose, y un frame
  oscuro es el peor punto de partida para dibujar zonas.
- **FPS con red de seguridad.** Muchas cámaras RTSP reportan 0 fps;
  propagarlo rompería la máquina de estados, cuyos umbrales están en
  frames.

### El aislamiento de red es el problema número uno

En una red universitaria o de oficina, el **aislamiento de clientes**
suele estar activo y bloquea el tráfico entre dispositivos conectados al
mismo Wi-Fi, así que el PC no ve al móvil por más que ambos estén
"conectados". La solución que siempre funciona: activar el **punto de
acceso del móvil** y conectar el portátil a él. Conviene comprobar el
stream en VLC antes de tocar la aplicación: si ahí se ve, el problema
nunca va a ser de red.

---

## Experiencia de usuario y accesibilidad

La interfaz se auditó midiendo, no a ojo: se calcularon las razones de
contraste WCAG de cada par de colores y se pasaron los colores de serie
del dashboard por un validador de paletas para daltonismo.

### Tour guiado

Al primer arranque se abre solo un recorrido de nueve pasos
(`app/ui/tour.py`). No es un diálogo con texto: oscurece la ventana y
**recorta un hueco iluminado sobre el elemento del que habla**, así que
enseña la interfaz real. Se repite cuando se quiera desde el botón **?**
de la esquina superior derecha o con **F1**, se navega con flechas y se
sale con Escape. Que ya se vio queda guardado en las preferencias del
usuario, no en el repositorio.

### Tres temas, todos validados

Desde el botón de accesibilidad (esquina superior derecha):

| Tema | Para qué | Texto principal |
|---|---|---|
| Oscuro | Interiores con poca luz | 16.3:1 |
| Claro | Salas iluminadas y proyección | 15.7:1 |
| Alto contraste | Baja visión (objetivo AAA) | 21:1 |

El tamaño de letra se ajusta en cuatro pasos (90% a 150%) y **los
controles crecen con ella**: si solo creciera el texto, el área en la que
se puede hacer click se quedaría igual de pequeña. Tema y tamaño se
aplican en vivo, sin reiniciar, y persisten entre sesiones vía
`QSettings` (`app/utils/settings.py`).

`scripts/check_theme_contrast.py` imprime la tabla completa de contrastes
y `tests/test_theme.py` **falla** si alguien baja un color por debajo de
su mínimo. Si al tocar un color el test se pone rojo, el color está mal.

### Lo que se corrigió

- **Recuadros sueltos alrededor de cada etiqueta.** Qt propaga el borde de
  un panel a sus hijos: cada título y cada campo aparecía dentro de su
  propia caja. Una regla de la hoja de estilos lo elimina.
- **No había indicador de foco.** La hoja de estilos anulaba el nativo sin
  poner otro, así que navegar con Tab era imposible de seguir (WCAG 2.4.7).
- **Contrastes por debajo de AA**: el texto atenuado estaba en 2.6:1, los
  bordes de panel en 1.3:1 (de ahí que todo se viera como una masa oscura)
  y los errores en 4.4:1.
- **El lienzo de zonas era solo de ratón.** Ahora las flechas mueven un
  cursor, Enter fija un vértice y Retroceso deshace.
- **Botones de solo ícono sin nombre accesible**, invisibles para un lector
  de pantalla.
- **La pantalla de inicio empezaba en la única función que no existe**:
  arrancaba en "IP CAMERA" con "CONNECT STREAM" como botón principal,
  mientras la limpieza de video quedaba en dos botones pequeños y grises.
- **Los metadatos del video se calculaban y no se mostraban nunca**: el
  widget existía pero no estaba en ningún layout.
- **El análisis no daba señales de vida.** Ahora hay barra de progreso con
  "fotograma X de Y".
- **Jerga técnica en la interfaz**: "PositionSample vacío",
  "InteractionEvent.action agrupado por zone_id", "Sesión (video_id)".

### Gráficos

El amarillo de marca significaba cinco cosas a la vez (botón primario,
pestaña activa, etiqueta del sistema, serie "tomado" y color de dibujo del
ROI). Las series se movieron a su propio par de colores, validado: la
separación entre ambos supera ΔE 23 en protanopia y deuteranopia, y cada
uno mantiene más de 5:1 contra el fondo de la tarjeta.

Además: las barras llevan etiquetas con los valores (sin eje ni números,
una barra solo dice "más que la otra"), la serie temporal tiene eje de
tiempo en minutos del video, el mapa de calor tiene escala de intensidad,
y las cifras de los KPI usan una fuente de ancho fijo para no bailar en
cada refresco.

---

## 7. Seguridad en la carga de archivos

La app acepta videos de una fuente que, por definición, no es confiable
(un archivo que sube o selecciona la persona usuaria). `app/utils/security.py`
y `app/core/ingestion/video_loader.py` cierran los vectores más directos
de abuso — no reemplazan un sandbox real, pero evitan que un archivo
malicioso o corrupto crashee o cuelgue la app:

| Riesgo | Mitigación |
|---|---|
| Un script/ejecutable renombrado a `.mp4` (la extensión no prueba nada) | `has_valid_video_signature()`: valida los primeros bytes del archivo contra la firma real del contenedor (`ftyp` para mp4/mov, `RIFF...AVI ` para avi, EBML para mkv, GUID ASF para wmv) **antes** de pasarlo a OpenCV |
| Contenedor corrupto o deliberadamente malformado que cuelga la lectura | `run_with_timeout()`: corre la apertura + primer frame (y la extracción de miniatura) en un hilo aparte con un límite de tiempo (`VIDEO_LOAD_TIMEOUT_SEC`, 20s por defecto) — la UI nunca se congela esperando indefinidamente |
| Header manipulado reportando una resolución o cantidad de frames absurda (posible intento de agotar memoria más adelante) | `MAX_VIDEO_WIDTH`/`MAX_VIDEO_HEIGHT` (8K) y `MAX_VIDEO_FRAME_COUNT` en `config.py`: se rechaza el archivo si el header reporta valores fuera de todo rango razonable |
| Archivo vacío, carpeta, symlink roto o dispositivo en vez de un archivo real | `path.is_file()` + chequeo explícito de tamaño `> 0` antes de intentar abrir nada |
| Video/carpeta que pesa demasiado o dura demasiado (agotamiento de disco/tiempo de proceso) | `MAX_VIDEO_SIZE_MB` / `MAX_VIDEO_DURATION_SEC` (ya existían, documentados en [3.2](#32-cómo-limitar-duración-y-peso-de-los-videos-cargados)) |
| Un nombre de archivo que termina usado como nombre de carpeta (`data/zones/<video_id>/`) con caracteres inesperados | `sanitize_filename_component()`: colapsa separadores de directorio, caracteres reservados de Windows (`* ? " < > \| :`) y de control a `_`, y neutraliza secuencias `..` — sin destruir acentos/ñ de nombres reales, solo bloquea lo peligroso |

`load_video()` aplica las validaciones **de la más barata a la más
costosa**: existencia → tipo de archivo → extensión → tamaño → firma de
contenedor, y solo al final invoca a OpenCV (con timeout). Un archivo
obviamente inválido nunca llega a la parte que podría colgarse.

Estos límites son valores de `app/utils/config.py`, igual que los del
Módulo 1 — cambiarlos no requiere tocar ningún otro archivo.

---

## 8. Contratos de datos documentados

| Contrato | Archivo | Generado por |
|----------|---------|--------------|
| Eventos del bus (`InteractionEvent`, `PositionSample`, `DwellRecord`) | [`docs/event_schema.md`](docs/event_schema.md) | `scripts/generate_schema_docs.py` |
| Zonas (`Zone`, `ZoneSignal`, formato de archivo) | [`docs/zone_schema.md`](docs/zone_schema.md) | `scripts/generate_schema_docs.py` |

Los `.md` se **generan desde el código real** (los modelos Pydantic de
`app/core/detection/schemas.py` y `zone.py` son la fuente de verdad):
si el esquema cambia, se regeneran con
`python -m scripts.generate_schema_docs` — nunca se editan a mano.

---

## 9. Privacidad por diseño

### Módulo 1

- Ni `video_loader.py` ni `video_cleaner.py` hacen reconocimiento facial,
  ni guardan ningún dato biométrico — solo metadatos técnicos (resolución,
  fps, duración, peso) y frames de imagen para preview **local**.
- Las miniaturas se guardan en `data/logs/`, que conviene excluir de
  cualquier respaldo o repositorio si en el futuro contienen rostros
  reconocibles (por ahora son solo para revisión visual del prototipo).
- Esta capa base no envía nada a internet: todo el procesamiento es local.

### Módulos 2, 3 y 4

- **Sin reconocimiento facial**: el sistema solo calcula bounding boxes de
  cuerpo completo y coordenadas numéricas de articulaciones (muñeca, codo,
  hombro). No entrena ni usa modelos de identidad facial.
- **Sin biometría**: no se guardan características biométricas (gait, altura,
  forma corporal específica de la persona).
- **Sin almacenamiento de imágenes**: los keypoints y las muestras de
  trayectoria son coordenadas (x, y, confidence) — no se guardan crops de
  imagen, no se archivan rostros ni siluetas.
- **Track IDs efímeros**: los identificadores de persona se generan
  dinámicamente durante la ejecución y se descartan al cerrar el video. No
  persisten entre sesiones ni se pueden usar para re-identificar a la misma
  persona en otro video (no hay base de datos de identidades).
- **Personal vs. cliente sin identidad**: `is_employee` es un flag
  booleano por track efímero (basado en si pisó una zona de personal), no
  una identidad de empleado — no hay padrón de empleados ni registro de
  quién es quién.
- **Timestamps trazables al original**: los eventos y las muestras de
  posición se pueden ubicar exactamente en el video original, útil para
  auditoría y revisión manual en caso de disputa o error del sistema.

---

## 10. Sugerencias para continuar el desarrollo

El proyecto está pensado para que cada punto siguiente sea una pestaña
nueva en `app/ui/main_window.py` y un módulo nuevo en `app/core/`, sin
reescribir lo ya construido.

### Corto plazo (siguiente iteración)

- ~~**Conectar el pipeline al Dashboard**~~ — **hecho**. El botón
  "Iniciar análisis" de la pestaña 2 conecta el `InProcessPublisher` a un
  `EventStore` (`connect_store_to_publisher`) y al terminar salta al
  dashboard. Antes ese publisher no tenía ningún slot conectado: todo lo
  que producía el pipeline se descartaba y el dashboard solo podía mostrar
  datos sembrados.
- ~~**Filtrar el dashboard por sesión**~~ — **hecho**, ver
  [6.4](#64-sesiones-cada-análisis-sus-propios-números).
- ~~**"ROI Auto-Suggest"**~~ — **hecho** (primera versión heurística), ver
  [4.5](#45-sugerencia-automática-de-zonas-auto-roi). Mejorable con un
  modelo entrenado o de vocabulario abierto.
- **Normalizar los finales de línea del repo**: el árbol de trabajo está
  en CRLF y el índice en LF, con `core.autocrlf` sin configurar, así que
  `git status` marca los ~66 archivos como modificados (mismo número de
  líneas insertadas que borradas). Conviene arreglarlo con
  `* text=auto eol=lf` en `.gitattributes` + `git add --renormalize .`
  **cuando todas las ramas estén integradas**: el commit toca el repo
  entero y volvería conflictivo cualquier merge pendiente.
- ~~**Implementar la cámara en vivo**~~ — **hecho**. `LiveFrameSource`
  acepta webcam local, RTSP y MJPEG por HTTP; ver
  [Cámara en vivo](#cámara-en-vivo). Lo que sigue pendiente es la
  reconexión automática si la cámara se cae durante un análisis largo.
- **(Obsoleto) Implementar la cámara en vivo (Team 1)**: reemplazar el stub
  `LiveFrameSource` por `cv2.VideoCapture` de webcam/RTSP con timestamps
  wall-clock — el resto del pipeline no cambia.
- **Distinción real pick-up vs put-back**: hoy la máquina de estados
  **alterna** `taken`/`returned` por track+zona (heurístico, sin
  detección de producto). Para distinguirlo con certeza se podría:
  - Detectar el movimiento de la mano (ascendente = tomar, descendente = devolver).
  - Usar una red clasificadora pequeña entrenada con anotaciones locales.
  - Combinar con información de carrito / zona de compra cercana.

### Mediano plazo

- **Mejora de robustez en pose bajo oclusión**: si el estante ocluye
  parcialmente al brazo, puede que los keypoints fallen. Se podría:
  - Usar modelos de pose más robustos (YOLOv11-pose-large, MediaPipe).
  - Implementar predicción de keypoints ocultos usando interpolación temporal.
- **Multizona simultánea**: hoy cada persona puede interactuar con una zona a
  la vez (por diseño del `state_machine`). Para permitir que una persona
  tenga eventos simultáneos en dos estantes (ej: comparar precios), se
  necesaría revisar la lógica de estado.
- **Persistencia de resultados consolidada**: el reporte de limpieza de cada
  video (incluido el mapeo frame-a-frame contra el original) ya se guarda
  automáticamente como `.json` junto al video limpio en `data/processed/`,
  y los eventos ya viven en SQLite. Lo que sigue pendiente es un
  **registro histórico consolidado** por sesión (qué video, cuándo, con
  qué configuración de `config.py`), para auditar y comparar corridas.
- **Mejorar el auto-ROI con un modelo**: la versión actual
  ([4.5](#45-sugerencia-automática-de-zonas-auto-roi)) es un heurístico de
  visión clásica reforzado con clases COCO de producto. Un modelo de
  vocabulario abierto (YOLO-World con el prompt "shelf") o uno ligero
  entrenado con anotaciones propias daría sugerencias bastante mejores; se
  dejó fuera del MVP por la dependencia pesada y la descarga de pesos, que
  van en contra del criterio de viabilidad edge.
- **Filtro de personal configurable en la UI**: el Dashboard ya soporta
  `exclude_employees=False` a nivel de `EventStore`; falta exponer un
  toggle visual para alternarlo sin editar código, útil para un análisis
  interno de circulación de personal.

### Largo plazo

- **Análisis de patrones**: con un histórico de eventos, detectar patrones
  anómalos (ej: misma persona, mismo producto, en segundos — posible hurto o
  problema de reabastecimiento).
- **Motor de recomendación** (deseable según el reto): empezar con
  reglas simples ("zona fría + alta tasa de rechazo → sugerir
  reubicación") antes de un modelo predictivo; es más rápido de validar
  y ya cumple el criterio de "accionabilidad de insights".
- **Optimización edge con OpenVINO**: una vez el pipeline de detección
  funcione con YOLO en PyTorch, exportar el modelo a formato OpenVINO
  para que corra en tiempo real en hardware modesto (criterio de
  evaluación explícito del reto: "viabilidad edge").
- **Exportar reportes**: un botón para exportar el dashboard final a PDF
  o Excel, útil para presentar resultados a un equipo de retail que no
  va a abrir la app directamente.

### Recomendación de orden de implementación

1. Detección + tracking (sin esto no hay nada más que construir) — **hecho**.
2. Zonificación manual, con roles producto/personal y edición in-place —
   **hecho** (pestaña 2).
3. Captura de trayectoria continua, dwell time y detección de personal —
   **hecho** (Módulo 2/3).
4. Dashboard de heatmap + KPIs + eventos (primer valor demostrable con
   datos reales) — **hecho** (Módulo 4).
5. Seguridad en la carga de archivos — **hecho** (sección 7).
6. Flujo encadenado carga → zonas → análisis → dashboard, con frame de
   referencia y ROI automáticas — **hecho**
   ([sección 1](#el-flujo-de-la-app-las-tres-pestañas-son-un-solo-camino),
   [4.5](#45-sugerencia-automática-de-zonas-auto-roi)).
7. Eventos de interacción pick-up vs put-back con certeza (más allá del
   heurístico de alternancia actual).
8. Cámara en vivo (webcam/RTSP) sobre la `FrameSource` ya existente.
9. Motor de recomendación basado en reglas.
10. Optimización edge (OpenVINO) como paso final de "productización".
