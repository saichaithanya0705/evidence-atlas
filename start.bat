@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "OFFLINE_ARG="

if "%~1"=="" goto args_ok
if /I "%~1"=="--offline" (
    if "%~2"=="" (
        set "OFFLINE_ARG=--offline"
        goto args_ok
    )
)
echo Usage: start.bat [--offline]
exit /b 2

:args_ok
if exist ".venv\Scripts\python.exe" goto venv_ready
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
    goto venv_ready
)
where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 is required. Install Python 3.10 or later and add it to PATH.
    exit /b 1
)
python -m venv .venv
if errorlevel 1 goto failed

:venv_ready
set "PYTHON=%CD%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PYTHONPATH=%CD%"

"%PYTHON%" -m pip --version >nul 2>nul
if not errorlevel 1 goto pip_ready
echo The existing virtual environment has no pip module. Repairing it with ensurepip...
"%PYTHON%" -m ensurepip --upgrade
if errorlevel 1 goto failed

:pip_ready
echo Updating pip and installing Python requirements...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto failed
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed

if exist .env goto env_ready
copy .env.example .env >nul
if errorlevel 1 goto failed
echo Created .env from .env.example. Edit NVIDIA_API_KEY and LLM_MODE for live NIM use.

:env_ready
echo Preparing model cache, dataset, indices, frontend, and local services...
"%PYTHON%" scripts\setup_project.py %OFFLINE_ARG%
if errorlevel 1 goto failed
exit /b 0

:failed
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="0" set "EXITCODE=1"
echo Setup or startup failed with exit code %EXITCODE%.
echo Review the error above and logs\backend.log or logs\frontend.log if services were started.
exit /b %EXITCODE%
