"""
Publicador de eventos.

Define el punto de extensión para enviar eventos al exterior (Team 3).
Soporta tres modos:

- `"file"` / `"stdout"`: salida local (jsonl) / consola, útiles para debug y logging.
- `"inprocess"`: transporte en el mismo proceso vía señales Qt (Signals/slots),
  para que backend y dashboard se suscriban sin red. Es el transporte del MVP.

Nota de arquitectura: si en el futuro el sistema corriera en varias
máquinas/dispositivos edge, un transporte de red (WebSocket o MQTT) sería
razonable — ver `docs/event_schema.md`. Queda explícitamente fuera de
alcance del MVP.
"""
from abc import ABC, ABCMeta, abstractmethod
import json
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel
from PySide6.QtCore import QObject, Signal

from app.utils.config import EVENT_PUBLISHER_MODE, EVENTS_LOCAL_LOG_PATH


class _QObjectABCMeta(type(QObject), ABCMeta):
    """Metaclasa combinada: permite heredar de QObject y de una ABC a la vez."""
    pass


class EventPublisher(ABC):
    """Interfaz base para el publicador de eventos.

    El bus transporta cualquier modelo Pydantic (InteractionEvent,
    PositionSample, ...), no solo un tipo — así el dashboard puede
    suscribirse a todos los flujos con el mismo mecanismo.
    """

    @abstractmethod
    def publish(self, event: BaseModel) -> None:
        """Publica el evento (modelo Pydantic) por el transporte del publicador."""
        pass


class LocalEventPublisher(EventPublisher):
    """
    Publicador local que escribe los eventos en consola o archivo según la configuración.

    Para extender el pipeline e integrar la comunicación con Team 3 en el futuro,
    se debe crear otra subclase implementando 'publish', sin alterar el resto de
    la lógica de detección.
    """

    def __init__(self, mode: str = EVENT_PUBLISHER_MODE, log_dir: str = EVENTS_LOCAL_LOG_PATH):
        self.mode = mode
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Generar nombre único para la sesión actual
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.log_dir / f"events_session_{timestamp_str}.jsonl"

    def publish(self, event: BaseModel) -> None:
        """Publica el evento serializado a stdout o archivo local jsonl."""
        event_data = event.model_dump()
        event_str = json.dumps(event_data)

        if self.mode == "stdout":
            print(f"[EVENT] {event_str}")
        elif self.mode == "file":
            # Escribir una nueva línea en el archivo de sesión
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(event_str + "\n")
        else:
            # Modo desconocido (placeholder), se imprime igual para no perder datos
            print(f"[EVENT - {self.mode}] {event_str}")


class InProcessPublisher(QObject, EventPublisher, metaclass=_QObjectABCMeta):
    """
    Publicador dentro del mismo proceso: emite una señal Qt por evento.

    Cualquier widget/worker puede conectarse a `event_emitted` y recibir
    el payload como dict (`model_dump()`). Las conexiones Qt->slot de un
    hilo distinto se ponen en cola automáticamente, así el pipeline puede
    correr en un QThread sin bloquear la UI (ver `pipeline_worker.py`).
    """

    event_emitted = Signal(dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    def publish(self, event: BaseModel) -> None:
        """Emite el evento serializado como dict a través de la señal Qt."""
        self.event_emitted.emit(event.model_dump())