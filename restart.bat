@echo off
setlocal
set "ROOT=%~dp0"
set "BPORT=8000"
set "FPORT=5173"
set "MODE=live"
if /I "%~1"=="mock" set "MODE=mock"

echo === restarting kbqa: backend=:%BPORT% frontend=:%FPORT% mode=%MODE% ===

call :stop %BPORT%
call :stop %FPORT%

if /I "%MODE%"=="mock" (
  set "ENV_FILE="
  set "LLM_BASE_URL="
  set "LLM_API_KEY="
  set "LLM_MODEL="
)

echo [backend] starting (port %BPORT%) ...
start "kbqa-backend" /min cmd /c "cd /d %ROOT%starter && .venv\Scripts\python.exe -m uvicorn kbqa.server:app --host 127.0.0.1 --port %BPORT%"

echo [frontend] starting (port %FPORT%) ...
start "kbqa-frontend" /min cmd /c "cd /d %ROOT%frontend && set VITE_API_TARGET=http://127.0.0.1:%BPORT% && npm run dev -- --port %FPORT% --host 127.0.0.1 --strictPort"

echo.
echo   backend   http://127.0.0.1:%BPORT%/api/health
echo   frontend  http://127.0.0.1:%FPORT%
echo.
echo   restart.bat         live mode (reads .env)
echo   restart.bat mock    force local mock mode (no API key needed)
echo.
echo give the backend a few seconds to warm up before first request.
endlocal
exit /b 0

:stop
for /f "tokens=5" %%a in ('netstat -ano ^| findstr LISTENING ^| findstr /C:":%~1 "') do (
  echo [stop] killing PID %%a on port %~1
  taskkill /F /PID %%a >nul 2>nul
)
exit /b 0
