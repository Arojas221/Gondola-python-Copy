# Frontend — Scapder Vision

Interfaz de escritorio (PySide6/Qt) con dos pestañas.

## Pestaña 1 — Carga y Limpieza de Video

**Columna izquierda — Archivos recientemente analizados**
- Lista de videos cargados, con selección múltiple.
- **Limpiar sel.**: limpia (quita frames negros/congelados) los videos
  seleccionados en la lista.
- **Limpiar todos**: limpia todos los videos cargados.
- **Cortar video**: abre un diálogo para elegir un rango de inicio/fin
  sobre el video seleccionado.
- Barra de progreso: avanza durante la limpieza de video.
- Área de log: muestra mensajes de carga, limpieza y corte.

**Columna derecha — Subir nuevo video**
- Vista previa grande del video seleccionado en la lista (miniatura).
- Selector de tipo de fuente: **IP CAMERA** o **FILE UPLOAD**.
  - En modo **IP CAMERA**: aparece un campo para escribir la URL RTSP
    y un botón **CONNECT STREAM**.
  - En modo **FILE UPLOAD**: aparece un botón para buscar un archivo
    de video en el equipo, y un botón **SUBIR ARCHIVO** para abrir el
    explorador de archivos y cargarlo(s) a la lista.

**Barra superior e inferior (compartidas con la pestaña 2)**
- Header: nombre de la fuente activa y un botón de configuración
  (ícono de engranaje) — **este botón está en espera, todavía no abre
  ninguna pantalla ni acción**.
- Footer: versión del motor y métricas "FPS / CPU" — **estas métricas
  no se están actualizando todavía, siempre muestran "--"**.

## Pestaña 2 — Edición de Zonas (ROI)

**Panel izquierdo**
- Nombre del video cargado y fecha.
- Dos botones de vista (íconos): alternan entre dos paneles de
  contenido dentro del mismo espacio.

**Lienzo central**
- Botón **Cargar video**: elige un video y muestra su frame de
  referencia sobre el lienzo.
- Click sobre el frame: agrega un punto (vértice) al polígono que se
  está dibujando.
- **Deshacer punto**: quita el último punto agregado.
- **Limpiar puntos**: borra todos los puntos del polígono actual.

**Panel derecho — Regiones de interés activas**
- Lista de zonas: muestra primero el polígono que se está dibujando
  (sin guardar) y luego las zonas ya guardadas para el video actual,
  cada una con su número de nodos, área y tipo.
- Click sobre una zona guardada: la resalta sobre el lienzo.
- Campo **Nombre**: nombre de la zona a guardar.
- Selector **Tipo**: "Góndola / producto (dwell time)" o "Personal
  (excluida de métricas)".
- **Cancelar**: limpia el polígono en construcción.
- **Guardar zona**: guarda la zona dibujada (mínimo 3 puntos, con
  nombre) para el video cargado.
- Área de log: mensajes de carga y guardado.

**Barra superior e inferior**: igual que en la Pestaña 1 (mismo
botón de configuración en espera, mismas métricas FPS/CPU sin
actualizar).