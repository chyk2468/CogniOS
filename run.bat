@echo off
setlocal enabledelayedexpansion
title CogniOS AI - Local Launcher

:: Start Ollama model in a separate window
start "Ollama Gemma4" cmd /k "ollama run gemma4:e2b"

pushd "%~dp0" >nul

echo ===================================================
echo    CogniOS AI - Local Launcher
echo ===================================================
echo.

set "PYTHON_EXE="

:: Check virtual environment paths
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=py -3"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [!] Error: Python was not found on your system.
    echo      Please install Python 3.11 or higher from https://www.python.org/downloads/
    echo.
    pause
    popd >nul
    exit /b 1
)

echo [+] Using Python: %PYTHON_EXE%
echo [+] Starting CogniOS AI services...
echo.

:: Run setup if needed
if not exist ".env" (
    echo [+] Running first-time setup...
    "%PYTHON_EXE%" setup.py
    echo.
)

:: Wait 3 seconds for the server to spin up, then open the browser in the background
echo [+] Opening browser at http://127.0.0.1:7000/
start cmd /c "timeout /t 3 >nul & start http://127.0.0.1:7000/"

:: Launch CogniOS AI launcher
"%PYTHON_EXE%" launcher.py

if errorlevel 1 (
    echo.
    echo [!] Server exited with an error code.
    pause
)

popd >nul
endlocal