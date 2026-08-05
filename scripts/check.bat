@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] .venv bulunamadi. Once scripts\bootstrap.bat calistir.
  exit /b 3
)
echo [1/5] Package import ve compile kontrolu...
"%PYTHON%" -m compileall -q src tests
if errorlevel 1 exit /b 10
echo [2/5] Pytest...
"%PYTHON%" -m pytest -q
if errorlevel 1 exit /b 11
echo [3/5] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12
echo [4/5] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13
echo [5/5] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 14
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 15
echo [PASS] Luna 0.1 Faz 0 kalite kapisi gecti.
exit /b 0
