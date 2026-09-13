"""
Mapeo y traducción de timestamps entre el video limpio y el original.
"""
from typing import List, Dict

def translate_to_original_timestamp(clean_frame_index: int, frame_mapping: List[Dict]) -> float:
    """
    Traduce el índice de frame del video limpio al timestamp (segundos) del video original.
    Si el índice no existe exactamente, interpola o usa el frame más cercano.
    """
    if not frame_mapping:
        return 0.0

    # Crear mapeo rápido
    mapping = {item["clean_frame"]: item["original_timestamp_sec"] for item in frame_mapping}

    if clean_frame_index in mapping:
        return float(mapping[clean_frame_index])

    # Si no se encuentra exactamente, buscar el más cercano
    closest_item = min(frame_mapping, key=lambda x: abs(x["clean_frame"] - clean_frame_index))
    return float(closest_item["original_timestamp_sec"])
