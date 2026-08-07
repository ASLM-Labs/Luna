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

echo [1/21] Package import ve syntax kontrolu...
"%PYTHON%" scripts\verify_syntax.py
if errorlevel 1 exit /b 10

echo [2/21] Pytest...
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
"%PYTHON%" -m pytest -q -p no:cacheprovider --basetemp=".pytest_tmp"
set "PYTEST_EXIT=%ERRORLEVEL%"
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
if not "%PYTEST_EXIT%"=="0" exit /b 11

echo [3/21] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/21] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/21] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/21] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/21] Faz 3 planning ve replan dogrulamasi...
"%PYTHON%" scripts\verify_phase3.py
if errorlevel 1 exit /b 16

echo [8/21] Faz 4 model ve tool dogrulamasi...
"%PYTHON%" scripts\verify_phase4.py
if errorlevel 1 exit /b 17

echo [9/21] Faz 5 workspace, shell ve rollback dogrulamasi...
"%PYTHON%" scripts\verify_phase5.py
if errorlevel 1 exit /b 18

echo [10/21] Faz 6 observation, audit ve evidence dogrulamasi...
"%PYTHON%" scripts\verify_phase6.py
if errorlevel 1 exit /b 19

echo [11/21] Faz 7 verifier ve completion gate dogrulamasi...
"%PYTHON%" scripts\verify_phase7.py
if errorlevel 1 exit /b 20

echo [12/21] Faz 8 checkpoint ve continuity dogrulamasi...
"%PYTHON%" scripts\verify_phase8.py
if errorlevel 1 exit /b 21

echo [13/21] Faz 9 dogrulanmis hafiza dogrulamasi...
"%PYTHON%" scripts\verify_phase9.py
if errorlevel 1 exit /b 22

echo [14/21] Faz 10 kimlik, raporlama ve ozerklik dogrulamasi...
"%PYTHON%" scripts\verify_phase10.py
if errorlevel 1 exit /b 23

echo [15/21] Faz 11 eval ve kabul sinavi dogrulamasi...
"%PYTHON%" scripts\verify_phase11.py
if errorlevel 1 exit /b 24

echo [16/21] Faz 12A runtime kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase12a.py
if errorlevel 1 exit /b 25

echo [17/21] Faz 12B layered context composer dogrulamasi...
"%PYTHON%" scripts\verify_phase12b.py
if errorlevel 1 exit /b 26

echo [18/21] Faz 12C action selection dogrulamasi...
"%PYTHON%" scripts\verify_phase12c.py
if errorlevel 1 exit /b 27

echo [19/21] Faz 12D failure recovery ve isolation dogrulamasi...
"%PYTHON%" scripts\verify_phase12d.py
if errorlevel 1 exit /b 28

echo [20/21] Faz 12E single policy-agent loop dogrulamasi...
"%PYTHON%" scripts\verify_phase12e.py
if errorlevel 1 exit /b 29

echo [21/21] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 30
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 31
"%PYTHON%" -m luna list-tools >nul
if errorlevel 1 exit /b 32
"%PYTHON%" -m luna tool-smoke "phase11" >nul
if errorlevel 1 exit /b 33
"%PYTHON%" -m luna workspace-smoke >nul
if errorlevel 1 exit /b 34
"%PYTHON%" -m luna process-smoke >nul
if errorlevel 1 exit /b 35
"%PYTHON%" -m luna audit-smoke >nul
if errorlevel 1 exit /b 36
"%PYTHON%" -m luna verify-smoke >nul
if errorlevel 1 exit /b 37
"%PYTHON%" -m luna checkpoint-smoke >nul
if errorlevel 1 exit /b 38
"%PYTHON%" -m luna memory-smoke >nul
if errorlevel 1 exit /b 39
"%PYTHON%" -m luna phase10-smoke >nul
if errorlevel 1 exit /b 40
"%PYTHON%" -m luna phase11-smoke >nul
if errorlevel 1 exit /b 41
"%PYTHON%" -m luna phase12a-smoke >nul
if errorlevel 1 exit /b 42
"%PYTHON%" -m luna phase12b-smoke >nul
if errorlevel 1 exit /b 43
"%PYTHON%" -m luna phase12c-smoke >nul
if errorlevel 1 exit /b 44
"%PYTHON%" -m luna phase12d-smoke >nul
if errorlevel 1 exit /b 45
"%PYTHON%" -m luna phase12e-smoke >nul
if errorlevel 1 exit /b 46

echo.
echo [PASS] Luna 0.1 Phase 12E single policy-agent loop gate passed.
exit /b 0
