# Requerimientos de software (SRS)

## Scapder Vision — Retail Space CV Analytics MVP

**Document standard reference:** IEEE 830-1998 / IEEE 29148-2018 (SRS structure)
**Version:** 0.1 (draft — team to fill in Status column)
**Ultima actualización:** 31 - Agosto - 2026

> **Como usar este documento:** Este se supone que debe ser editado, no solo leído. Todos
> Los requerimientos tienen una columna `Status`. Actualicen el estado del la tarea para que le equipo pueda saber como va el trabajo y quien trabaja en que.
> Statuses: `no empezado` / `En progreso` / `Hecho` / `Bloqueado`.
> Prioridades siguen el patron MoSCoW: **debe (most)** (core del MVP, no negociables),
> **debería (Should)** (Construir si lo no negociable ya esta listo), **Podría (Could)** (realizar si se esta sobra tiempo)

---

## 1. Introducción

### 1.1 Proposito

Este documento especifica los requisitos funcionales y no funcionales de
Scapder Vision, una aplicación de escritorio que utiliza modelos locales de visión artificial
para detectar y analizar las interacciones de los clientes con productos de venta minorista (recoger,
devolver, tiempo de permanencia) a través de una o más cámaras, y presenta los resultados
en un panel de control en tiempo real que incluye un mapa de calor del movimiento de los compradores.

Su propósito es proporcionar a todo el equipo (no solo a quien escribió un módulo determinado) una única fuente de información actualizada sobre lo que debe existir, lo que ya existe y lo que está explícitamente fuera del alcance del proyecto. Sustituye la dependencia de ramas de Git o actualizaciones verbales para conocer el estado del proyecto.

### 1.2 Alcance

Scapder Vision es una **aplicación de escritorio PySide6 (Qt) de un solo proceso**. Sus funciones son:

- Ingerir vídeo, ya sea desde un archivo subido o (de destino) desde una transmisión de cámara en directo.
- Detectar personas y su postura, realizar un seguimiento a través de los fotogramas y determinar
  si interactúan con las zonas de producto definidas (ROI).
- Agregar datos de interacción y movimiento.
- Mostrar esta información en un panel de control en tiempo real, incluyendo un mapa de calor.

### 1.3 Definiciones, acrónimos y abreviaciones

| Term            | Meaning                                                                                                                      |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| ROI / Zone      | Una región poligonal definida en la cámara, que representa un estante o área de producto.                                    |
| Track ID        | Identificador asignado por cámara y por sesión a una persona detectada por el sistema de seguimiento.                        |
| Global ID       | Identidad entre cámaras (re-ID), si se implementa — ver 3.1.2 (Podría)                                                       |
| Event           | Un evento discreto emitido por el proceso de detección (por ejemplo, `taken`, `put_back`).                                   |
| Position Sample | Un registro continuo de posición por fotograma utilizado para construir el mapa de calor                                     |
| Frame Mapping   | Registro JSON producido por el limpiador de vídeo, que relaciona el índice del fotograma limpiado con el fotograma/timestamp |
| MVP             | Producto mínimo viable: la versión más pequeña que demuestra el valor central de principio a fin                             |

### 1.4 Referencias

- Documentación Ultralytics YOLOv8/YOLOv11
- doucmentacion de OpenVINO (model conversion/inference)
- Torchreid / OSNet (re-ID)
- Discuciones previos de equipo sobre la arquitectura (interno — consulte `MIGRATION.md` y
  `docs/event_schema.md` una vez generados.)

### 1.5 Generalidades

La sección 2 ofrece una descripción general del producto. La sección 3 enumera los requisitos concretos y verificables, agrupados por equipo responsable. La sección 4 enumera las restricciones y los elementos excluidos explícitamente. La sección 5 es el apéndice (glosario ya mencionado, además de la justificación de la clasificación del MVP).

---

## 2. Descripción general

### 2.1 Perspectiva del producto

Aplicación de escritorio única, con cuatro subsistemas propios que se comunican **en el mismo proceso** (señales/ranuras de Qt; este MVP no utiliza transporte de red):

```
[Camera/Video Input] → [Pipeline de detección] → [Backend/Almacenamiento + agregados] → [Dashboard UI]
      (Team 1)               (Team 2)                          (Team 3)                    (Team 4)
```

### 2.2 funciones del producto (resumen — De forma detallada en punto 3)

1. Aceptar entrada de vídeo (carga de archivos; la cámara en directo es un objetivo, aún no se ha hecho).
2. Detecta personas, su postura y síguelas con cada cámara.
3. Detectar la interacción con zonas de producto definidas y clasificar la acción.
4. Registrar datos de posición continuos para la generación de mapas de calor
5. Almacenar y agregar datos de eventos y posición
6. Visualización de un panel de control en tiempo real: vista de vídeo, estadísticas de interacción por zona, mapa de calor.

### 2.3 Características del usuario

Los usuarios principales de este MVP son **los jueces del hackathon y el propio equipo** durante la demostración/prueba, no el personal de ventas. Se asume que no se proporciona capacitación; el panel de control debe ser intuitivo y fácil de usar.

### 2.4 Limites generales

- Debe ejecutarse en un único portátil sin GPU dedicada como objetivo base.
  (OpenVINO es la herramienta principal para cumplir con este requisito; consulte la sección NFR-PERF).
- Debe ser una única aplicación Qt; no requiere servidor web ni panel de control independientes.
- Plazo total de 2 semanas; equipo de 8 personas dividido en 4 parejas.

### 2.5 Dependencias y suposiciones

- El equipo dispone o puede obtener grabaciones de muestra similares a las de una tienda minorista para realizar pruebas.
- Ultralytics, OpenVINO y torchreid se pueden instalar en el entorno de desarrollo del equipo
  sin problemas de licencia.
- Las definiciones de ROI/zonas se crean una sola vez por configuración de demostración, no se modifican dinámicamente
  durante una ejecución en vivo.

---

## 3. requerimientos específicos

Cada requerimiento: **ID | Descripción | Prioridad | Quien realiza | Status**

### 3.1 Requerimientos funcionales

#### 3.1.1 Ingestión

| ID        | Descripción                                                                                                                                                                         | Prioridad | Status            |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------------- |
| FR-ING-01 | El sistema aceptará un archivo de vídeo subido y producirá una versión limpia y validada (existente: `video_loader.py`, `video_cleaner.py`).                                        | Debe      | Hecho (verificar) |
| FR-ING-02 | El sistema generará un registro de mapeo de fotogramas (fotograma limpio → fotograma/marca de tiempo original) junto con el vídeo limpio.                                           | Debe      | Hecho (verificar) |
| FR-ING-03 | El sistema deberá exponer una interfaz `FrameSource` común para que el proceso de detección no necesite saber si los fotogramas provienen de un archivo o de una cámara en directo. | Debe | Hecho |
| FR-ING-04 | El sistema deberá admitir al menos una fuente de cámara en directo (cámara web USB) como alternativa a la carga de archivos. | Debería | En progreso |
| FR-ING-05 | El sistema deberá admitir cámaras IP RTSP como fuente de transmisión en directo. | Podría | No empezado |
| FR-ING-06 | El sistema deberá admitir más de una fuente de cámara simultánea. | Podría | No empezado |
| FR-ING-07 | El sistema deberá gestionar la desconexión/reconexión de la cámara sin fallar. | Debería | No empezado |

#### 3.1.2 Pipeline de detección

| ID        | Descripción                                                                                                                                                                          | Prioridad | Status            |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------- | ----------------- |
| FR-DET-01 | El sistema deberá detectar personas en cada fotograma procesado (YOLO).                                                                                                              | Debe      | Hecho (verificar) |
| FR-DET-02 | El sistema deberá estimar los puntos clave de la postura por persona detectada.                                                                                                      | Debe      | Hecho (verificar) |
| FR-DET-03 | El sistema deberá realizar un seguimiento de las personas detectadas a través de los fotogramas con un identificador de seguimiento estable por cámara.                              | Debe      | Hecho (verificar) |
| FR-DET-04 | El sistema deberá admitir zonas poligonales definidas por el usuario (ROI) que representen áreas de producto.                                                                        | Debe      | Hecho (verificar) |
| FR-DET-05 | El sistema deberá detectar cuando la mano/punto clave de una persona rastreada entre en una zona.                                                                                    | Debe      | Hecho (verificar) |
| FR-DET-06 | El sistema clasificará la interacción mediante una máquina de estados (inactivo → alcanzar → sostener → devolver / tomar objeto).                                                    | Debe      | Hecho (verificar) |
| FR-DET-07 | El sistema emitirá un `InteractionEvent` estructurado para cada interacción clasificada.                                                                                             | Debe      | Hecho (verificar) |
| FR-DET-08 | El sistema registrará una `PositionSample` continua por fotograma (posición + marca de tiempo) por persona rastreada, para la generación de mapas de calor.                          | **Debe**  | Hecho        |
| FR-DET-09 | El sistema publicará eventos y muestras de posición a través de un publicador en proceso (basado en señales Qt), no mediante transporte de red.                                      | Debe      | Hecho        |
| FR-DET-10 | El sistema deberá admitir la exportación de modelos de detección/pose al formato OpenVINO para una inferencia de CPU más rápida.                                                     | Debería   | No empezado   |
| FR-DET-11 | El sistema deberá admitir la reidentificación entre cámaras (misma persona, cámara diferente) mediante incrustaciones de apariencia.                                                 | Podría    | No empezado   |
| FR-DET-12 | El sistema deberá admitir la exportación OpenVINO para el modelo de re-ID.                                                                                                           | Podría    | No empezado   |
| FR-DET-13 | El sistema deberá admitir la omisión de fotogramas / inferencia selectiva de modelos pesados ​​(solo ejecutar pose/re-ID cerca de una zona) para reducir el tiempo de procesamiento. | Debería   | No empezado   |

#### 3.1.3 Backend / Data / QA

| ID        | Descripción                                                                                                                                                                                                                                              | Prioridad | Status      |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| FR-BAK-01 | El sistema deberá guardar los registros de `InteractionEvent` en una base de datos local (SQLite). | Debe | Hecho       |
| FR-BAK-02 | El sistema deberá guardar los registros `PositionSample` en una base de datos local. | Debe | En progreso |
| FR-BAK-03 | El sistema agregará los registros `PositionSample` en una cuadrícula de densidad 2D adecuada para la representación de mapas de calor, con suavizado aplicado. | **Debe**  | En progreso |
| FR-BAK-04 | El sistema deberá exponer una capa de acceso a datos en proceso que el panel de control podrá consultar para obtener información sobre eventos en tiempo real, cuadrícula de mapa de calor, tiempo de permanencia y recuentos de interacciones por zona. | Debe | En progreso |
| FR-BAK-05 | El sistema deberá proporcionar un generador de datos simulados/falsos que coincida con el esquema real, para el desarrollo de paneles de control independientemente de una canalización en funcionamiento. | Debería | No empezado |
| FR-BAK-06 | Control de calidad: los casos de prueba deberán cubrir los casos extremos de ROI/máquina de estados (alcance sin toma, personas superpuestas en una zona). | Debería | No empezado |
| FR-BAK-07 | Control de calidad: una prueba de extremo a extremo debe abarcar toda la cadena (entrada → detección → backend → panel de control). | Debe | No empezado |
| FR-BAK-08 | Control de calidad: se realizará una prueba de estabilidad/carga que ejecutará el proceso completo de forma continua para comprobar si hay fugas de memoria o fallos antes de la demostración. | Debería | No empezado |

#### 3.1.4 Dashboard / UI

| ID         | Descripción                                                                                                                                                             | Prioridad | Status      |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| FR-DASH-01 | El sistema mostrará una vista de video en vivo o cargada dentro de la aplicación Qt. | Debe | En progreso |
| FR-DASH-02 | El sistema mostrará un mapa de calor de la densidad de movimiento/permanencia, actualizándose en tiempo real. | **Debe**  | En progreso |
| FR-DASH-03 | El sistema mostrará el número de interacciones y las estadísticas por zona. | Debe | No empezado |
| FR-DASH-04 | El sistema deberá proporcionar una interfaz de usuario para dibujar y guardar zonas poligonales en un marco de referencia. | Debe | Hecho       |
| FR-DASH-05 | El sistema permitirá filtrar el panel de control por cámara y/o intervalo de tiempo. | Debería | No empezado |
| FR-DASH-06 | El sistema deberá distinguir visualmente los tipos de acciones (por ejemplo, codificar con colores el artículo tomado frente al artículo devuelto) en la vista de zona. | Debería | No empezado |
| FR-DASH-07 | La aplicación deberá poder empaquetarse como un archivo `.exe` independiente. | Podría | No empezado |

### 3.2 Requerimientos de interfaces externas

| ID    | Descripción                                                                                                                                                                                       | Prioridad | Status      |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| IF-01 | El esquema `InteractionEvent` deberá definirse una sola vez (Pydantic, `schemas.py`) y documentarse en `docs/event_schema.md`, generado a partir del código, no escrito manualmente por separado. | Debe | Hecho       |
| IF-02 | El esquema `PositionSample` deberá añadirse a `schemas.py` y documentarse junto con `InteractionEvent`. | Debe | Hecho       |
| IF-03 | El esquema de `Zone` se documentará en `docs/zone_schema.md`, generado a partir de `zone.py`. | Debe | Hecho       |
| IF-04 | El formato de configuración de la cámara (origen, ID, zonas) deberá documentarse y compartirse entre el Equipo 1 y el Equipo 2. | Debe | Hecho       |

### 3.3 Requerimientos de performances

| ID          | Descripción                                                                                                                                                                                                            | Prioridad | Status       |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------ |
| NFR-PERF-01 | En hardware exclusivamente de CPU con modelos exportados desde OpenVINO, la canalización procesará el vídeo a una velocidad adecuada para un clip de demostración en directo (2-5 min) en tiempo muy inferior al real. | Debe | No aplicable (aún no hay exportación OpenVINO) |
| NFR-PERF-02 | El sistema se someterá a pruebas de rendimiento (FPS y tiempo de procesamiento de un clip de prueba fijo) antes y después de la conversión a OpenVINO, registrándose los valores para el tono. | Debería | No empezado |
| NFR-PERF-03 | La interfaz de usuario deberá permanecer receptiva (no congelarse) mientras se ejecuta el proceso de detección, mediante subprocesos en segundo plano. | Debe | Hecho       |

### 3.4 Limitaciones de diseño

| ID    | Descripción                                                                                                                   |
| ----- | ----------------------------------------------------------------------------------------------------------------------------- |
| DC-01 | Aplicación Qt única: sin servidor web ni framework de panel de control independientes.                                        |
| DC-02 | Transporte de eventos dentro del proceso únicamente (señales Qt): este MVP no incluye capa de WebSocket/red.                  |
| DC-03 | Se prefieren los modelos de tamaño nano (YOLOv8n/v11n o equivalente) a las variantes más grandes por su viabilidad en la CPU. |

### 3.5 Requerimientos No Funcionales / de Privacidad

| ID          | Requirement                                                                                                                                     | Priority                       | Status                               |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------ |
| NFR-PRIV-01 | El sistema no realizará reconocimiento facial. | Debo | Hecho       |
| NFR-PRIV-02 | Cualquier incrustación de apariencia (si se implementa la re-ID) se mantendrá únicamente en la memoria, no se almacenará en el disco. | Debe (Si FR-DET-11 esta hecho) | Solo aplica si re-ID es implementado |
| NFR-PRIV-03 | Los datos de identidad/seguimiento no se conservarán más allá de una sesión (no se realizará un seguimiento a largo plazo durante varios días). | Debe | Hecho       |

---

## 4. Fuera de alcance

- Guardado de Identificación biometrica (por temas legales),
- Implementación en la nube / arquitectura multimáquina / transporte en red
- Aplicación mobile
- Mapa de calor unificado para toda la tienda que requiere calibración de homografía multicámara.
  (Solo mapas de calor de una sola cámara o por cámara, a menos que el tiempo lo permita; consulte el nivel FR-DET-11/12).
- Entrenamiento de modelos personalizados desde cero (solo modelos preentrenados, por cada 2,5)

---

## 5. Apéndices

### 5.1 Justificación de la clasificación del MVP

- **Debe** = canalización principal: una cámara, detección → interacción de zona → mapa de calor

→ panel de control. Si esto no funciona de forma fiable, nada más importa para la
demo.

- **Debería** = mejora/amplía la clasificación Imprescindible (múltiples cámaras sin re-ID,
  OpenVINO en YOLO, filtrado, cobertura de control de calidad). Implementar una vez que la clasificación Imprescindible sea estable.

- **Podría** = re-ID entre cámaras, OpenVINO en el modelo de re-ID, empaquetado `.exe`.

Intentar solo con días de antelación: una función de extensión defectuosa es peor para la
demo que no tenerla.

### 5.2 Punto de control semanal sugerido

Utilice este documento en una breve sincronización semanal (o a mitad de semana) del equipo: revise fila por fila,
actualice el estado y marque cualquier elemento como «Bloqueado» inmediatamente, en lugar de al
final del sprint. Este es el mecanismo diseñado para resolver el problema de las ramas que divergen y el estado real desconocido en el futuro.

### 5.3 Preguntas abiertas (añadir a medida que surjan)

- _Ej.: "¿Quién es el propietario de FR-DET-08 (captura de trayectoria)? — Confirmado: Equipo 2?"_
- _Ej.: "¿Ya tenemos grabaciones reales de la tienda o seguimos usando clips de prueba?"_
