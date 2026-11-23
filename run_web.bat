@echo off
cd /d "%~dp0"

set PORT=5500
set URL=http://127.0.0.1:%PORT%/web/index.html

rem This server needs the project venv (joblib, scikit-learn, etc.).
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe not found. Create the venv and install dependencies first.
  echo For a no-install option, use run_static.bat instead.
  pause
  exit /b 1
)

rem If a server is already listening on this port, just open the page.
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo Server already running on port %PORT%. Opening the page only.
  start "" "%URL%"
  exit /b 0
)

echo Starting Python web + API server: %URL%
rem Open the browser after a short delay.
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" "%URL%""
".venv\Scripts\python.exe" prediction_api.py --port %PORT%
pause
