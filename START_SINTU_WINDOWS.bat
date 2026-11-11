@echo off
setlocal
cd /d "%~dp0"
title SINTU AI STUDIO

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10 or newer is required. Install Python from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is required. Update Python and run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the local Python environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto failed
)

call ".venv\Scripts\activate.bat"
echo Installing or updating SINTU dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo Preparing secure local login...
where ffmpeg >nul 2>nul
if errorlevel 1 echo WARNING: FFmpeg not found. MP4 export requires FFmpeg on PATH.
where ollama >nul 2>nul
if errorlevel 1 echo NOTE: Install Ollama and run ollama pull qwen2.5:3b for free local AI.
where blender >nul 2>nul
if errorlevel 1 echo NOTE: Install Blender and add blender to PATH for local 3D rendering.
echo Paid APIs remain locked until revenue and explicit approval.
python scripts\bootstrap_local.py
if errorlevel 1 goto failed

echo.
echo SINTU AI STUDIO is starting at http://127.0.0.1:8000
echo Keep this window open while using the studio.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto end

:failed
echo.
echo Setup failed. Check the message above and try again.
pause

:end
endlocal
