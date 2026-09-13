@echo off
IF NOT EXIST .venv (
    echo Creando entorno virtual con uv...
    uv venv
)

call .venv\Scripts\activate
echo Instalando dependencias...
uv pip install -r requirements.txt

echo Iniciando Scapder Vision...
python -m app.main