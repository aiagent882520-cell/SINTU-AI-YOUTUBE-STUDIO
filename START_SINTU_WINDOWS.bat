@echo off
setlocal
cd /d "%~dp0"
title SINTU AI YOUTUBE STUDIO

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11 or newer is required. Install Python from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Update Python and run this file again.
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
set "HOST=127.0.0.1"
if /i "%SINTU_ALLOW_LAN%"=="true" (
  set "HOST=0.0.0.0"
  echo.
  echo LAN mode enabled. Open the PC IPv4 address on another device on the same Wi-Fi:
  ipconfig | findstr /i "IPv4"
  echo Allow Python through Windows Firewall only on your trusted private network.
)
echo.
echo SINTU AI YOUTUBE STUDIO is starting on port 8000.
echo Keep this window open while using the studio.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn app.main:app --host %HOST% --port 8000
goto end

:failed
echo.
echo Setup failed. Check the message above and try again.
pause

:end
endlocal
