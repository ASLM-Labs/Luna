@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] .venv bulunamadi. Once scripts\bootstrap.bat calistir.
  exit /b 3
)

echo [1/7] Package import ve compile kontrolu...
"%PYTHON%" -m compileall -q src tests
if errorlevel 1 exit /b 10

echo [2/7] Pytest...
"%PYTHON%" -m pytest -q
if errorlevel 1 exit /b 11

echo [3/7] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/7] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/7] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/7] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/7] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 16
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 17
"%PYTHON%" -m luna resolve-intent "README.md dosyasini incele" >nul
if errorlevel 1 exit /b 18

echo.
echo [PASS] Luna 0.1 Faz 2 intent ve context kapisi gecti.
exit /b 0
