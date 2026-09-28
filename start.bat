@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "OFFLINE_ARG="
set "INGEST_DATA=0"

:parse_args
if "%~1"=="" goto args_ok
if /I "%~1"=="--offline" (
    set "OFFLINE_ARG=--offline"
    shift
    goto parse_args
)
if /I "%~1"=="--ingest" (
    set "INGEST_DATA=1"
    shift
    goto parse_args
)
echo Usage: start.bat [--offline] [--ingest]
exit /b 2

:args_ok
if "%INGEST_DATA%"=="1" if defined OFFLINE_ARG (
    echo --ingest requires access to the official NCBI PubMed API and cannot be combined with --offline.
    exit /b 2
)
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
if "%INGEST_DATA%"=="0" goto project_setup
if not exist "PubMed_Phrases.tar.gz" (
    echo PubMed_Phrases.tar.gz is required for --ingest but was not found in the project root.
    exit /b 1
)
if not defined PUBMED_INGEST_LIMIT set "PUBMED_INGEST_LIMIT=100000"
echo Building the real PubMed corpus from phrase PMIDs and official NCBI records...
"%PYTHON%" scripts\ingest_pubmed_phrases.py --limit "%PUBMED_INGEST_LIMIT%" --output data\raw\pubmed_sample.csv
if errorlevel 1 goto failed

:project_setup
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
