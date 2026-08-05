@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] .venv bulunamadi. Once scripts\bootstrap.bat calistir.
  exit /b 3
)

echo [1/9] Package import ve compile kontrolu...
"%PYTHON%" -m compileall -q src tests
if errorlevel 1 exit /b 10

echo [2/9] Pytest...
"%PYTHON%" -m pytest -q
if errorlevel 1 exit /b 11

echo [3/9] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/9] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/9] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/9] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/9] Faz 3 planning ve replan dogrulamasi...
"%PYTHON%" scripts\verify_phase3.py
if errorlevel 1 exit /b 16

echo [8/9] Faz 4 model ve tool dogrulamasi...
"%PYTHON%" scripts\verify_phase4.py
if errorlevel 1 exit /b 17

echo [9/9] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 18
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 19
"%PYTHON%" -m luna list-tools >nul
if errorlevel 1 exit /b 20
"%PYTHON%" -m luna tool-smoke "phase4" >nul
if errorlevel 1 exit /b 21

echo.
echo [PASS] Luna 0.1 Faz 4 model ve tool kapisi gecti.
exit /b 0
