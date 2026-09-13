"""
Almacén local de eventos (Team 3).

Suscribe al bus in-process (`InProcessPublisher`) y persiste
`InteractionEvent`, `PositionSample` y `DwellRecord` en una base SQLite
local. Es la única fuente de datos del Dashboard (pestaña 3).

Dos conceptos que atraviesan todo el módulo:

- **Sesión** (`video_id`): cada corrida del pipeline analiza un video. Sin
  esa columna, el dashboard mezclaba en un solo total los eventos de todos
  los videos analizados alguna vez, y el selector de sesión no filtraba
  nada. `set_session()` la fija antes de arrancar el análisis y todas las
  consultas aceptan un `video_id` opcional para acotarse a ella.

- **Demo** (`is_demo`): las filas sembradas por `demo_seed` para poder
  enseñar el dashboard antes de correr el pipeline quedan marcadas. Sin
  esta marca, en cuanto se sembraba la demo los datos sintéticos pasaban a
  ser indistinguibles de los reales y el dashboard los presentaba como si
  vinieran de un análisis — justo lo que no puede pasar delante de un
  evaluador.
"""
from pathlib import Path
from typing import List, Optional
import sqlite3

from app.core.detection.schemas import InteractionEvent, PositionSample, DwellRecord
from app.core.detection.event_publisher import InProcessPublisher
from app.utils.config import EVENT_STORE_DB_PATH

# Cada cuántas escrituras se hace commit. El pipeline publica una
# PositionSample por persona y por frame: con commit por fila, una sesión
# de dos minutos son decenas de miles de fsync y el disco se vuelve el
# cuello de botella del análisis. `flush()` cierra el lote pendiente.
COMMIT_EVERY = 50


class EventStore:
    """Persistencia local SQLite de eventos, muestras de posición y dwell time."""

    def __init__(self, db_path: str = EVENT_STORE_DB_PATH, check_same_thread: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=check_same_thread)
        self._conn.row_factory = sqlite3.Row
        # WAL: el dashboard lee la misma base que el análisis está
        # escribiendo. Sin WAL, cada escritura bloquea a los lectores y el
        # refresco del dashboard puede fallar con "database is locked".
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._session_video_id: str = ""
        self._session_is_demo: bool = False
        self._pending_writes = 0
        self._init_schema()

    # -------------------------------------------------------------- sesión --
    def set_session(self, video_id: str, is_demo: bool = False) -> None:
        """
        Fija la sesión con la que se etiquetan las filas que se inserten a
        partir de ahora.

        El `video_id` se estampa aquí y no dentro de los modelos Pydantic a
        propósito: qué video se está analizando es una propiedad de *esta
        corrida del almacén*, no del evento en sí. Así el pipeline de
        detección sigue siendo agnóstico de dónde se guardan sus eventos.
        """
        self._session_video_id = video_id or ""
        self._session_is_demo = bool(is_demo)

    @property
    def session_video_id(self) -> str:
        return self._session_video_id

    def _init_schema(self) -> None:
        """Crea las tablas y los índices si no existen, y migra las viejas."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id     TEXT PRIMARY KEY,
                track_id     INTEGER NOT NULL,
                zone_id      TEXT    NOT NULL,
                action       TEXT    NOT NULL,
                timestamp    REAL    NOT NULL,
                is_employee  INTEGER NOT NULL DEFAULT 0,
                video_id     TEXT    NOT NULL DEFAULT '',
                is_demo      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS position_samples (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id     INTEGER NOT NULL,
                frame_index  INTEGER NOT NULL,
                timestamp    REAL    NOT NULL,
                foot_x       REAL    NOT NULL,
                foot_y       REAL    NOT NULL,
                camera_id    TEXT    NOT NULL,
                is_employee  INTEGER NOT NULL DEFAULT 0,
                video_id     TEXT    NOT NULL DEFAULT '',
                is_demo      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS dwell_records (
                event_id         TEXT PRIMARY KEY,
                track_id         INTEGER NOT NULL,
                zone_id          TEXT    NOT NULL,
                entry_timestamp  REAL    NOT NULL,
                exit_timestamp   REAL    NOT NULL,
                duration_sec     REAL    NOT NULL,
                is_employee      INTEGER NOT NULL DEFAULT 0,
                video_id         TEXT    NOT NULL DEFAULT '',
                is_demo          INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self._migrate_columns()
        # Índices: el dashboard refresca cada pocos segundos y agrupa por
        # zona y por tiempo dentro de una sesión. Sin ellos, cada refresco
        # es un scan completo de la tabla de muestras.
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_events_session   ON events (video_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_zone      ON events (video_id, zone_id);
            CREATE INDEX IF NOT EXISTS idx_samples_session  ON position_samples (video_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_dwell_session    ON dwell_records (video_id, zone_id);
            """
        )
        self._conn.commit()

    def _migrate_columns(self) -> None:
        """
        Agrega `video_id`/`is_demo` a bases creadas antes de que existieran.

        Idempotente y sin destruir datos: las filas viejas quedan con
        `video_id = ''`, que el dashboard muestra como sesión "(sin
        clasificar)". Borrar y recrear la base sería más simple pero le
        haría perder al equipo cualquier corrida anterior.
        """
        for table in ("events", "position_samples", "dwell_records"):
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "video_id" not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN video_id TEXT NOT NULL DEFAULT ''")
            if "is_demo" not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")

    # ----------------------------------------------------------- inserción --
    def _after_write(self) -> None:
        """Commit por lotes: ver COMMIT_EVERY."""
        self._pending_writes += 1
        if self._pending_writes >= COMMIT_EVERY:
            self._conn.commit()
            self._pending_writes = 0

    def flush(self) -> None:
        """Confirma el lote pendiente. Llamar al terminar un análisis."""
        if self._pending_writes:
            self._conn.commit()
            self._pending_writes = 0

    def insert_event(self, event: InteractionEvent) -> None:
        """Guarda un evento de interacción en la sesión activa."""
        self._conn.execute(
            "INSERT OR REPLACE INTO events "
            "(event_id, track_id, zone_id, action, timestamp, is_employee, video_id, is_demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.track_id, event.zone_id, event.action, event.timestamp,
             int(event.is_employee), self._session_video_id, int(self._session_is_demo)),
        )
        self._after_write()

    def insert_position_sample(self, sample: PositionSample) -> None:
        """Guarda una muestra de posición en la sesión activa."""
        self.insert_position_samples([sample])

    def insert_position_samples(self, samples: List[PositionSample]) -> None:
        """Inserta varias muestras de posición en una sola sentencia."""
        if not samples:
            return
        rows = [
            (s.track_id, s.frame_index, s.original_timestamp_sec,
             s.foot_position[0], s.foot_position[1], s.camera_id,
             int(s.is_employee), self._session_video_id, int(self._session_is_demo))
            for s in samples
        ]
        self._conn.executemany(
            "INSERT INTO position_samples "
            "(track_id, frame_index, timestamp, foot_x, foot_y, camera_id, is_employee, video_id, is_demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._after_write()

    def insert_dwell_record(self, record: DwellRecord) -> None:
        """Guarda un registro de permanencia (dwell time) en la sesión activa."""
        self._conn.execute(
            "INSERT OR REPLACE INTO dwell_records "
            "(event_id, track_id, zone_id, entry_timestamp, exit_timestamp, duration_sec, "
            " is_employee, video_id, is_demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.event_id, record.track_id, record.zone_id, record.entry_timestamp,
             record.exit_timestamp, record.duration_sec, int(record.is_employee),
             self._session_video_id, int(self._session_is_demo)),
        )
        self._after_write()

    # ---------------------------------------------------------- bus sink ----
    def on_bus_message(self, payload: dict) -> None:
        """Sink del bus in-process: despacha el dict recibido al tipo correcto."""
        if "foot_position" in payload:
            self.insert_position_sample(PositionSample(**payload))
        elif "duration_sec" in payload:
            self.insert_dwell_record(DwellRecord(**payload))
        elif "action" in payload and "event_id" in payload:
            self.insert_event(InteractionEvent(**payload))
        else:
            print(f"[EventStore] Payload desconocido en el bus, ignorado: {sorted(payload)[:6]}")

    # ------------------------------------------------------------ filtros --
    @staticmethod
    def _session_clause(video_id: Optional[str], prefix: str = "WHERE") -> tuple:
        """
        Devuelve (fragmento_sql, params) para acotar una consulta a una sesión.

        Con `video_id=None` no filtra — así el dashboard puede seguir
        mostrando el acumulado de todas las sesiones si hace falta.
        """
        if video_id is None:
            return "", ()
        return f"{prefix} video_id = ?", (video_id,)

    def list_sessions(self) -> List[str]:
        """`video_id` de todas las sesiones con datos, más recientes primero."""
        rows = self._conn.execute(
            "SELECT video_id, MAX(timestamp) AS last_ts FROM events "
            "GROUP BY video_id ORDER BY last_ts DESC"
        ).fetchall()
        return [r["video_id"] for r in rows]

    def count_events(self, video_id: Optional[str] = None) -> int:
        clause, params = self._session_clause(video_id)
        return self._conn.execute(f"SELECT COUNT(*) FROM events {clause}", params).fetchone()[0]

    def count_position_samples(self, video_id: Optional[str] = None) -> int:
        clause, params = self._session_clause(video_id)
        return self._conn.execute(f"SELECT COUNT(*) FROM position_samples {clause}", params).fetchone()[0]

    def count_dwell_records(self, video_id: Optional[str] = None) -> int:
        clause, params = self._session_clause(video_id)
        return self._conn.execute(f"SELECT COUNT(*) FROM dwell_records {clause}", params).fetchone()[0]

    def count_demo_events(self, video_id: Optional[str] = None) -> int:
        """Cuántos eventos de la sesión son sintéticos (sembrados por demo_seed)."""
        clause, params = self._session_clause(video_id, prefix="AND")
        return self._conn.execute(
            f"SELECT COUNT(*) FROM events WHERE is_demo = 1 {clause}", params
        ).fetchone()[0]

    def count_real_events(self, video_id: Optional[str] = None) -> int:
        """Cuántos eventos de la sesión vienen de un análisis real del pipeline."""
        clause, params = self._session_clause(video_id, prefix="AND")
        return self._conn.execute(
            f"SELECT COUNT(*) FROM events WHERE is_demo = 0 {clause}", params
        ).fetchone()[0]

    def delete_demo_rows(self, video_id: Optional[str] = None) -> int:
        """
        Borra las filas sintéticas (las reales no se tocan).

        Devuelve cuántos eventos se eliminaron. Es lo que permite pasar de
        "así se vería el dashboard" a "esto es lo que midió el análisis"
        sin arrastrar los datos de ejemplo.
        """
        clause, params = self._session_clause(video_id, prefix="AND")
        deleted = 0
        for table in ("events", "position_samples", "dwell_records"):
            cursor = self._conn.execute(f"DELETE FROM {table} WHERE is_demo = 1 {clause}", params)
            if table == "events":
                deleted = cursor.rowcount
        self._conn.commit()
        self._pending_writes = 0
        return deleted

    # ------------------------------------------------- consultas agregadas --
    # Usadas por el dashboard (app/ui/dashboard_tab.py). Todas devuelven
    # tipos nativos de Python (dict/list), listos para pintar en la UI sin
    # que el widget tenga que saber nada de SQL.

    def get_summary(self, video_id: Optional[str] = None) -> dict:
        """Totales de la sesión: base de los KPIs del dashboard."""
        clause, params = self._session_clause(video_id, prefix="AND")

        def _count_events(extra_sql: str) -> int:
            return self._conn.execute(
                f"SELECT COUNT(*) FROM events WHERE {extra_sql} {clause}", params
            ).fetchone()[0]

        taken = _count_events("action = 'taken'")
        returned = _count_events("action = 'returned'")
        employee_events = _count_events("is_employee = 1")
        total_events = self.count_events(video_id)

        dwell_clause, dwell_params = self._session_clause(video_id)
        avg_dwell = self._conn.execute(
            f"SELECT AVG(duration_sec) FROM dwell_records {dwell_clause}", dwell_params
        ).fetchone()[0]
        active_zones = self._conn.execute(
            f"SELECT COUNT(DISTINCT zone_id) FROM events {dwell_clause}", dwell_params
        ).fetchone()[0]

        return {
            "total_events": total_events,
            "taken": taken,
            "returned": returned,
            "take_rate": round(taken / total_events, 4) if total_events else 0.0,
            "avg_dwell_sec": round(avg_dwell, 2) if avg_dwell is not None else 0.0,
            "employee_events": employee_events,
            "employee_share": round(employee_events / total_events, 4) if total_events else 0.0,
            "active_zones": active_zones,
        }

    def get_zone_breakdown(self, video_id: Optional[str] = None) -> list[dict]:
        """Conteo de `taken`/`returned` y dwell promedio, agrupado por zona."""
        clause, params = self._session_clause(video_id)
        rows = self._conn.execute(
            f"""
            SELECT
                zone_id,
                SUM(CASE WHEN action = 'taken' THEN 1 ELSE 0 END)    AS taken,
                SUM(CASE WHEN action = 'returned' THEN 1 ELSE 0 END) AS returned
            FROM events
            {clause}
            GROUP BY zone_id
            """,
            params,
        ).fetchall()
        dwell_by_zone = {
            r["zone_id"]: r["avg_dwell"]
            for r in self._conn.execute(
                f"SELECT zone_id, AVG(duration_sec) AS avg_dwell FROM dwell_records {clause} "
                f"GROUP BY zone_id",
                params,
            ).fetchall()
        }
        return [
            {
                "zone_id": r["zone_id"],
                "taken": r["taken"],
                "returned": r["returned"],
                "avg_dwell_sec": round(dwell_by_zone.get(r["zone_id"], 0.0) or 0.0, 2),
            }
            for r in rows
        ]

    def get_timeline(self, bucket_sec: float = 30.0, video_id: Optional[str] = None) -> list[dict]:
        """
        Serie temporal de `taken`/`returned`, agrupada en buckets de
        `bucket_sec` segundos desde el primer evento de la sesión.
        """
        clause, params = self._session_clause(video_id)
        rows = self._conn.execute(
            f"SELECT action, timestamp FROM events {clause} ORDER BY timestamp", params
        ).fetchall()
        if not rows:
            return []

        t0 = rows[0]["timestamp"]
        buckets: dict[int, dict] = {}
        for r in rows:
            idx = int((r["timestamp"] - t0) // bucket_sec)
            bucket = buckets.setdefault(idx, {"taken": 0, "returned": 0})
            if r["action"] in ("taken", "returned"):
                bucket[r["action"]] += 1

        return [
            {
                "bucket_start_sec": t0 + idx * bucket_sec,
                "taken": buckets.get(idx, {}).get("taken", 0),
                "returned": buckets.get(idx, {}).get("returned", 0),
            }
            for idx in range(max(buckets) + 1)
        ]

    def get_recent_events(self, limit: int = 15, video_id: Optional[str] = None) -> list[dict]:
        """Últimos eventos registrados, más recientes primero (feed en vivo)."""
        clause, params = self._session_clause(video_id)
        rows = self._conn.execute(
            f"SELECT event_id, track_id, zone_id, action, timestamp, is_employee, is_demo "
            f"FROM events {clause} ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_position_samples(
        self,
        limit: int = 6000,
        exclude_employees: bool = True,
        video_id: Optional[str] = None,
    ) -> list[PositionSample]:
        """
        Muestras de posición (pie de cada persona por frame) de la sesión —
        el insumo de `build_density_grid` para el mapa de calor.

        `exclude_employees=True` (default) descarta las muestras marcadas
        `is_employee`: el heatmap busca mostrar circulación de **clientes**,
        y un empleado parado horas en el mismo punto generaría ahí una
        mancha de calor que no refleja tráfico de cliente. La zona de
        personal se dibuja aparte sobre el heatmap para dar contexto.

        `limit` acota cuántas muestras se traen: una sesión larga acumula
        decenas de miles de filas y el heatmap no necesita más que unos
        miles de puntos para verse denso.
        """
        conditions = []
        params: list = []
        if exclude_employees:
            conditions.append("is_employee = 0")
        if video_id is not None:
            conditions.append("video_id = ?")
            params.append(video_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._conn.execute(
            f"SELECT track_id, frame_index, timestamp, foot_x, foot_y, camera_id, is_employee "
            f"FROM position_samples {where} ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [
            PositionSample(
                track_id=r["track_id"],
                frame_index=r["frame_index"],
                original_timestamp_sec=r["timestamp"],
                foot_position=(r["foot_x"], r["foot_y"]),
                camera_id=r["camera_id"],
                is_employee=bool(r["is_employee"]),
            )
            for r in rows
        ]

    def close(self) -> None:
        self.flush()
        self._conn.close()

    def __del__(self):
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 - conexión ya cerrada o en teardown
            pass


def connect_store_to_publisher(store: EventStore, publisher: InProcessPublisher) -> None:
    """
    Suscribe el almacén al bus in-process.

    Sin esta conexión el `InProcessPublisher` emite su señal sin ningún
    slot escuchando y todo lo que produce el pipeline (eventos de
    interacción, permanencias y muestras de posición) se descarta: el
    dashboard se queda vacío por más que el análisis haya corrido entero.
    """
    publisher.event_emitted.connect(store.on_bus_message)
