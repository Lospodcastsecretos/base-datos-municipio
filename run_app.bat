@echo off
echo Activando entorno virtual...
call venv\Scripts\activate.bat

echo.
echo Iniciando Sistema de Base de Datos Municipal...
echo.
echo Recuerda que debes tener configurada tu GOOGLE_API_KEY en un archivo .env
echo.

streamlit run app.py
pause
