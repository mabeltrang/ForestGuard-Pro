@echo off
cd /d "%~dp0"

echo === ForestGuard Pro (Streamlit Version) ===
echo Cerrando instancias anteriores del servidor...

REM Mata cualquier proceso previo usando el puerto 8501
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
)

timeout /t 1 /nobreak >nul

echo Iniciando aplicación Streamlit...
echo.
echo NO CIERRES ESTA VENTANA MIENTRAS USAS LA HERRAMIENTA
echo.

REM Iniciar el servidor de Streamlit
.\venv\Scripts\streamlit run app.py

pause
