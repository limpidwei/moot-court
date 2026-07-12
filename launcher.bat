@echo off
setlocal EnableDelayedExpansion

set PYTHON_PATH=py
set PROJECT_DIR=%~dp0
set FRONTEND_DIR=%PROJECT_DIR%frontend-next

:menu
cls
echo ========================================
echo        Moot Court Launcher
echo ========================================

tasklist /FI "WINDOWTITLE eq MootCourt-Backend*" 2>nul | findstr cmd >nul 2>&1
if %errorlevel% equ 0 (
    set BACKEND_STATUS=Running
) else (
    set BACKEND_STATUS=Stopped
)

tasklist /FI "WINDOWTITLE eq MootCourt-Frontend*" 2>nul | findstr cmd >nul 2>&1
if %errorlevel% equ 0 (
    set FRONTEND_STATUS=Running
) else (
    set FRONTEND_STATUS=Stopped
)

echo  Backend : !BACKEND_STATUS!
echo  Frontend: !FRONTEND_STATUS!
echo ========================================
echo  [1] Start Backend  (http://127.0.0.1:8000)
echo  [2] Start Frontend (http://localhost:3000)
echo  [3] Stop Backend
echo  [4] Stop Frontend
echo  [5] Stop all and exit
echo ========================================
set /p choice=Select:

if "%choice%"=="1" goto start_backend
if "%choice%"=="2" goto start_frontend
if "%choice%"=="3" goto stop_backend
if "%choice%"=="4" goto stop_frontend
if "%choice%"=="5" goto stop_all_exit

goto menu

:start_backend
if "!BACKEND_STATUS!"=="Running" (
    echo Backend already running.
    pause
    goto menu
)

:: Auto-detect Python: py launcher -> python command -> known path
set PYTHON_EXE=%PYTHON_PATH%
where %PYTHON_EXE% >nul 2>nul
if %errorlevel% equ 0 goto python_ok

where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON_EXE=python
    goto python_ok
)

set PYTHON_EXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe
if exist "%PYTHON_EXE%" goto python_ok

echo [Error] Python not found. Tried: py, python, %LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe
pause
goto menu

:python_ok

netstat -ano | findstr "LISTENING" | findstr ":8000" >nul 2>&1
if %errorlevel% equ 0 (
    echo [Info] Port 8000 in use, backend may already be running.
    echo Visit http://127.0.0.1:8000
    pause
    goto menu
)

start "MootCourt-Backend" cmd /k "cd /d %PROJECT_DIR% && %PYTHON_EXE% -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 && pause"
echo Backend started.
timeout /t 2 >nul
goto menu

:start_frontend
if "!FRONTEND_STATUS!"=="Running" (
    echo Frontend already running.
    start http://localhost:3000
    pause
    goto menu
)

where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [Error] npm not found. Install Node.js first.
    pause
    goto menu
)

if not exist "%FRONTEND_DIR%\node_modules\.bin\next.cmd" (
    echo [Info] Missing deps, running npm install...
    cd /d "%FRONTEND_DIR%"
    call npm install
    if %errorlevel% neq 0 (
        echo [Error] npm install failed.
        pause
        goto menu
    )
)

netstat -ano | findstr "LISTENING" | findstr ":3000" >nul 2>&1
if %errorlevel% equ 0 (
    echo [Info] Port 3000 in use, frontend already running.
    start http://localhost:3000
    pause
    goto menu
)

echo Starting frontend...
start "MootCourt-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"
timeout /t 3 >nul
start http://localhost:3000
echo Frontend started.
timeout /t 2 >nul
goto menu

:stop_backend
taskkill /FI "WINDOWTITLE eq MootCourt-Backend*" /F >nul 2>&1
echo Backend stopped.
timeout /t 1 >nul
goto menu

:stop_frontend
taskkill /FI "WINDOWTITLE eq MootCourt-Frontend*" /F >nul 2>&1
echo Frontend stopped.
timeout /t 1 >nul
goto menu

:stop_all_exit
taskkill /FI "WINDOWTITLE eq MootCourt-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq MootCourt-Frontend*" /F >nul 2>&1
echo All stopped.
pause
exit
