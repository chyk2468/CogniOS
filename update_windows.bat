@echo off
setlocal
title Update CogniOS Local Deployment

pushd "%~dp0" >nul

echo =========================================
echo Updating CogniOS Local Deployment
echo =========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [!] Git was not found on PATH.
  echo     Install Git for Windows, then run this script again.
  goto :fail
)

echo [+] Pulling latest code...
git pull --ff-only
if errorlevel 1 goto :fail

echo.
if exist ".venv\Scripts\python.exe" (
  echo [+] Updating dependencies in .venv...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
) else if exist "venv\Scripts\python.exe" (
  echo [+] Updating dependencies in venv...
  venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo =========================================
echo Update completed successfully.
echo =========================================
goto :done

:fail
echo.
echo Update failed. Check the message above and try again.

:done
popd >nul
pause
