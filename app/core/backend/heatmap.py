
"""
Agregación de datos para mapas de calor (Team 3) — STUB.

Convierte `PositionSample` acumulados (de la trayectoria continua del
pipeline) en una cuadrícula 2D de densidad de presencia, con blur
gaussiano aplicado antes de devolverla — lista para renderizar un
heatmap en el dashboard (Team 4).

TODO(Team 3):
- ponderación por dwell time (muestras con tiempos largos = mayor peso)
- proyección de coordenadas de píxel a coordenadas de layout real
- exportar a imagen (cv2.applyColorMap) para el dashboard
"""
import cv2
import numpy as np

from app.core.detection.schemas import PositionSample


def build_density_grid(
    samples: list[PositionSample],
    frame_size: tuple[int, int],
    grid_size: tuple[int, int] = (64, 48),
    sigma: float = 1.0,
) -> np.ndarray:
    """
    Construye una cuadrícula 2D de densidad de presencia a partir de
    muestras de posición (foot_position en píxeles del frame).

    Args:
        samples: muestras acumuladas de la trayectoria.
        frame_size: (ancho, alto) del frame de referencia.
        grid_size: (columnas, filas) de la cuadrícula de salida.
        sigma: desviación estándar del blur gaussiano (0 o None = sin blur).

    Returns:
        np.ndarray 2D (filas x columnas) con densidades suavizadas.
    """
    frame_w, frame_h = frame_size
    cols, rows = grid_size
    grid = np.zeros((rows, cols), dtype=np.float32)

    for sample in samples:
        foot_x, foot_y = sample.foot_position
        # Coordenadas de píxel -> celda de la cuadrícula (clip a los límites)
        cell_x = min(max(int(foot_x / frame_w * cols), 0), cols - 1)
        cell_y = min(max(int(foot_y / frame_h * rows), 0), rows - 1)
        grid[cell_y, cell_x] += 1.0

    if sigma:
        # Blur gaussiano: convierte conteos puntuales en densidad continua.
        # ksize (0,0) hace que OpenCV derive el kernel automáticamente de sigma.
        grid = cv2.GaussianBlur(grid, (0, 0), sigmaX=sigma, sigmaY=sigma)

    return grid
