@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  CogniOS — starting local dev environment
echo  ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Python venv not found at %~dp0.venv
    echo.
    echo Run the one-time bootstrap first:
    echo   bash packaging/setup_dev_env.sh
    echo   ^(Git Bash or WSL on Windows^)
    echo.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm not found. Install Node.js 20+ and add it to PATH.
    echo.
    pause
    exit /b 1
)

if not exist "surfaces\gui\node_modules" (
    echo Installing frontend dependencies...
    pushd surfaces\gui
    call npm install
    if errorlevel 1 (
        echo ERROR: npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

REM Stop stale CogniOS dev processes blocking ports 8765 / 1420
call :kill_port 8765
call :kill_port 1420

echo Starting CogniOS Server...
start "CogniOS Server" /D "%~dp0" cmd /k "title CogniOS Server && .venv\Scripts\python.exe -m cogniwork.server.run --cwd . --port 8765"
echo Waiting for server...
ping 127.0.0.1 -n 6 >nul

echo Starting CogniOS Frontend...
start "CogniOS Frontend" /D "%~dp0surfaces\gui" cmd /k "title CogniOS Frontend && npm run dev"

echo.
echo CogniOS is starting:
echo   Server:  http://127.0.0.1:8765
echo   UI:      http://localhost:1420
echo.
echo Two command windows should open — keep them running while you use CogniOS.
echo Close those windows to stop the app.
echo.
pause
exit /b 0

:kill_port
set "PORT=%~1"
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%PORT% "') do (
    set "FOUND=1"
    echo   Stopping stale process on port %PORT% ^(PID %%P^)...
    taskkill /F /PID %%P >nul 2>&1
)
if defined FOUND ping 127.0.0.1 -n 2 >nul
exit /b 0
