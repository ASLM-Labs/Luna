@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON=.venv\Scripts\python.exe"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%PYTHON%" (
  echo [ERROR] .venv bulunamadi. Once scripts\bootstrap.bat calistir.
  exit /b 3
)

echo [1/17] Package import ve syntax kontrolu...
"%PYTHON%" scripts\verify_syntax.py
if errorlevel 1 exit /b 10

echo [2/17] Pytest...
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
"%PYTHON%" -m pytest -q -p no:cacheprovider --basetemp=".pytest_tmp"
set "PYTEST_EXIT=%ERRORLEVEL%"
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
if not "%PYTEST_EXIT%"=="0" exit /b 11

echo [3/17] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/17] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/17] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/17] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/17] Faz 3 planning ve replan dogrulamasi...
"%PYTHON%" scripts\verify_phase3.py
if errorlevel 1 exit /b 16

echo [8/17] Faz 4 model ve tool dogrulamasi...
"%PYTHON%" scripts\verify_phase4.py
if errorlevel 1 exit /b 17

echo [9/17] Faz 5 workspace, shell ve rollback dogrulamasi...
"%PYTHON%" scripts\verify_phase5.py
if errorlevel 1 exit /b 18

echo [10/17] Faz 6 observation, audit ve evidence dogrulamasi...
"%PYTHON%" scripts\verify_phase6.py
if errorlevel 1 exit /b 19

echo [11/17] Faz 7 verifier ve completion gate dogrulamasi...
"%PYTHON%" scripts\verify_phase7.py
if errorlevel 1 exit /b 20

echo [12/17] Faz 8 checkpoint ve continuity dogrulamasi...
"%PYTHON%" scripts\verify_phase8.py
if errorlevel 1 exit /b 21

echo [13/17] Faz 9 dogrulanmis hafiza dogrulamasi...
"%PYTHON%" scripts\verify_phase9.py
if errorlevel 1 exit /b 22

echo [14/17] Faz 10 kimlik, raporlama ve ozerklik dogrulamasi...
"%PYTHON%" scripts\verify_phase10.py
if errorlevel 1 exit /b 23

echo [15/17] Faz 11 eval ve kabul sinavi dogrulamasi...
"%PYTHON%" scripts\verify_phase11.py
if errorlevel 1 exit /b 24

echo [16/17] Faz 12A runtime kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase12a.py
if errorlevel 1 exit /b 25

echo [17/17] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 26
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 27
"%PYTHON%" -m luna list-tools >nul
if errorlevel 1 exit /b 28
"%PYTHON%" -m luna tool-smoke "phase11" >nul
if errorlevel 1 exit /b 29
"%PYTHON%" -m luna workspace-smoke >nul
if errorlevel 1 exit /b 30
"%PYTHON%" -m luna process-smoke >nul
if errorlevel 1 exit /b 31
"%PYTHON%" -m luna audit-smoke >nul
if errorlevel 1 exit /b 32
"%PYTHON%" -m luna verify-smoke >nul
if errorlevel 1 exit /b 33
"%PYTHON%" -m luna checkpoint-smoke >nul
if errorlevel 1 exit /b 34
"%PYTHON%" -m luna memory-smoke >nul
if errorlevel 1 exit /b 35
"%PYTHON%" -m luna phase10-smoke >nul
if errorlevel 1 exit /b 36
"%PYTHON%" -m luna phase11-smoke >nul
if errorlevel 1 exit /b 37
"%PYTHON%" -m luna phase12a-smoke >nul
if errorlevel 1 exit /b 38

echo.
echo [PASS] Luna 0.1 Phase 12A runtime contracts gate passed.
exit /b 0
