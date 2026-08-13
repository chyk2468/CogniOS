@echo off
echo Starting OpenWorker Server...
start "OpenWorker Server" cmd /k ".venv\Scripts\openworker-server.exe --cwd . --port 8765"

echo Waiting for the server to initialize and generate the authentication token...
timeout /t 5 /nobreak >nul

echo Starting OpenWorker Frontend...
cd surfaces\gui
start "OpenWorker Frontend" cmd /k "npm run dev"
cd ..\..
