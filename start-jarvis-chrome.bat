@echo off
rem Opens a separate "Jarvis" Chrome window that AgentJ can control.
rem It is real Chrome with its own profile (saved in data\chrome-profile):
rem log in to YouTube, Google Search Console, etc. ONCE in this window and it stays logged in.
rem Your normal Chrome is not touched and can stay open.
cd /d "%~dp0"

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo  Could not find Google Chrome. Install it from https://www.google.com/chrome/
  pause
  exit /b 1
)

if not exist "data\chrome-profile" mkdir "data\chrome-profile"
start "" "%CHROME%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="%~dp0data\chrome-profile" --no-first-run --no-default-browser-check
echo  Jarvis Chrome is open. Keep it open while AgentJ runs Chrome tasks.
timeout /t 3 >nul
