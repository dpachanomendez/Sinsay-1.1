@echo off
echo ================================================
echo Instalando Google Cloud TTS como respaldo
echo ================================================
echo.

echo Activando entorno virtual...
call venv\Scripts\activate.bat

echo.
echo Instalando dependencias de Google Cloud TTS...
pip install google-cloud-texttospeech google-api-core google-auth

echo.
echo ================================================
echo Instalacion completada!
echo ================================================
echo.
echo La API Key ya esta configurada en app.py
echo Reinicia la aplicacion con: python app.py
echo.
pause
