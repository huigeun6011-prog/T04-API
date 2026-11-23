@echo off
cd /d "%~dp0"

set PORT=5501
set URL=http://127.0.0.1:%PORT%/

rem Use the project venv if present, otherwise the system python (stdlib only is needed).
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

rem Generate public copies (weather, referenced XML) from data/raw. Needs Node; skip with a notice if missing.
where node >nul 2>nul
if %errorlevel%==0 (
  node scripts\sync_static_data.mjs
) else (
  echo [notice] node was not found. Skipping scripts\sync_static_data.mjs - weather and XML copies may be missing.
)

rem If a server is already listening on this port, just open the page.
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo Server already running on port %PORT%. Opening the page only.
  start "" "%URL%"
  exit /b 0
)

echo Starting static-web file server: %URL%
echo Python: %PY%
rem Open the browser after a short delay.
start "" cmd /c "timeout /t 2 /nobreak >nul & start "" "%URL%""
"%PY%" -m http.server %PORT% --bind 127.0.0.1 --directory static-web
pause
