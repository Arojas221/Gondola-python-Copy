"""
Utilidades de seguridad para el ingreso de archivos (Team 1) y para
cualquier lugar que derive nombres de carpeta/archivo a partir de datos
que en última instancia vienen de fuera del código (el nombre de un video
subido por el usuario).

Contexto: la app acepta videos de fuentes no confiables (usuario final,
posiblemente un archivo bajado de internet o compartido por otra
persona). Nada de esto reemplaza un sandbox real, pero cierra los
vectores más directos:

- un archivo renombrado a .mp4 que en realidad es un script/ejecutable
  (`has_valid_video_signature`),
- un contenedor corrupto/malformado que cuelga a OpenCV leyendo el
  primer frame, congelando la UI indefinidamente (`run_with_timeout`),
- un nombre de archivo que termina siendo usado como nombre de carpeta
  (`data/zones/<video_id>/`) con caracteres fuera de lo esperado
  (`sanitize_filename_component`).
"""
import re
import threading
from pathlib import Path
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

# Lista de BLOQUEO (no de permitidos): separadores de directorio en Windows
# y POSIX, caracteres reservados de Windows (* ? " < > |, dos puntos fuera
# de la unidad C:\), y todos los caracteres de control. Deliberadamente NO
# se restringe a ASCII — nombres reales con tildes/ñ ("Cámara Piso 2") no
# deberían mutilarse para quedar "seguros".
_DANGEROUS_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def sanitize_filename_component(name: str, fallback: str = "video") -> str:
    """
    Reduce `name` a un componente de ruta seguro — pensado para nombres
    derivados de un archivo subido (video_id, nombre de miniatura) antes
    de usarlos como parte de una ruta en disco.

    Colapsa separadores de directorio, caracteres reservados de Windows y
    caracteres de control a "_", y limpia puntos/espacios sueltos en los
    bordes para que no puedan formar ".." (path traversal) ni nombres
    "ocultos" al estilo Unix. Si el resultado queda vacío, usa `fallback`.
    """
    cleaned = _DANGEROUS_CHARS_RE.sub("_", name)
    cleaned = cleaned.strip(" ._")
    cleaned = cleaned.replace("..", "_")
    return cleaned or fallback


def run_with_timeout(func: Callable[[], T], timeout_sec: float, timeout_message: str) -> T:
    """
    Corre `func` (sin argumentos) en un hilo aparte y espera como máximo
    `timeout_sec` segundos.

    OpenCV puede colgarse leyendo un contenedor de video corrupto o
    deliberadamente malformado. Python no puede matar un hilo a la fuerza,
    así que esto no cancela el trabajo colgado — pero sí evita que quien
    llama (típicamente la UI) se quede esperando para siempre: pasado el
    timeout, se levanta `TimeoutError` y el hilo bloqueado queda huérfano
    (`daemon=True`, no impide cerrar la app).
    """
    result: dict = {}

    def _target():
        try:
            result["value"] = func()
        except BaseException as exc:  # noqa: BLE001 - se re-lanza tal cual en el hilo llamador
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout_sec)
    if thread.is_alive():
        raise TimeoutError(timeout_message)
    if "error" in result:
        raise result["error"]
    return result["value"]


# --------------------------------------------------- firmas de archivo --
# La extensión de un archivo no prueba nada por sí sola — un atacante
# puede renombrar cualquier cosa a "clip.mp4". Estas funciones validan el
# encabezado real contra el contenedor que la extensión dice ser.

def _is_iso_bmff(header: bytes) -> bool:
    """mp4/mov/m4v: caja 'ftyp' en el offset 4."""
    return header[4:8] == b"ftyp"


def _is_avi(header: bytes) -> bool:
    return header[0:4] == b"RIFF" and header[8:12] == b"AVI "


def _is_matroska(header: bytes) -> bool:
    return header[0:4] == b"\x1a\x45\xdf\xa3"  # EBML (mkv/webm)


def _is_asf(header: bytes) -> bool:
    """wmv: GUID de encabezado ASF."""
    return header[0:16] == bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")


_SIGNATURE_CHECKS: dict[str, Callable[[bytes], bool]] = {
    ".mp4": _is_iso_bmff,
    ".mov": _is_iso_bmff,
    ".avi": _is_avi,
    ".mkv": _is_matroska,
    ".wmv": _is_asf,
}


def has_valid_video_signature(path: str | Path, header: Optional[bytes] = None) -> bool:
    """
    True si los primeros bytes del archivo coinciden con el contenedor que
    su extensión dice ser. Una extensión sin validador conocido en este
    módulo pasa por defecto (defensa adicional, no la única barrera —
    `load_video` igualmente valida que OpenCV pueda decodificar un frame).
    """
    suffix = Path(path).suffix.lower()
    check = _SIGNATURE_CHECKS.get(suffix)
    if check is None:
        return True

    if header is None:
        with open(path, "rb") as f:
            header = f.read(32)

    if len(header) < 12:
        return False
    try:
        return check(header)
    except Exception:  # noqa: BLE001 - un encabezado raro no debe tumbar la validación
        return False
