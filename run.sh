#!/bin/bash
# Script de arranque rápido: crea el entorno virtual (si no existe),
# instala dependencias y lanza la aplicación.
set -e

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "Instalando dependencias..."
pip install -q -r requirements.txt

echo "Iniciando Scapder Vision..."
python -m app.main
