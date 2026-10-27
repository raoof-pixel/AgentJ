@echo off
title AgentJ - install
cd /d "%~dp0"
echo.
echo  === Installing AgentJ ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  Python is not installed.
  echo  Install Python 3.12 from https://www.python.org/downloads/
  echo  and TICK "Add python.exe to PATH" during setup. Then run this again.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo  AgentJ needs Python 3.11 or newer. Install Python 3.12 from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo  Creating virtual environment...
  %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
echo  Installing browser-use (the Chrome agent)...
pip install -r requirements.txt
if errorlevel 1 (
  echo  Install failed - check your internet connection and run install.bat again.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo  === Done! ===
echo  1. Double-click start.bat to open the dashboard.
echo  2. Open Settings and paste your free Gemini API key.
echo  3. For Chrome tasks, double-click start-jarvis-chrome.bat first.
echo.
pause
