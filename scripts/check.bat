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

echo [1/34] Package import ve syntax kontrolu...
"%PYTHON%" scripts\verify_syntax.py
if errorlevel 1 exit /b 10

echo [2/34] Pytest...
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
"%PYTHON%" -m pytest -q -p no:cacheprovider --basetemp=".pytest_tmp"
set "PYTEST_EXIT=%ERRORLEVEL%"
if exist ".pytest_tmp" rmdir /s /q ".pytest_tmp"
if not "%PYTEST_EXIT%"=="0" exit /b 11

echo [3/34] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/34] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/34] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/34] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/34] Faz 3 planning ve replan dogrulamasi...
"%PYTHON%" scripts\verify_phase3.py
if errorlevel 1 exit /b 16

echo [8/34] Faz 4 model ve tool dogrulamasi...
"%PYTHON%" scripts\verify_phase4.py
if errorlevel 1 exit /b 17

echo [9/34] Faz 5 workspace, shell ve rollback dogrulamasi...
"%PYTHON%" scripts\verify_phase5.py
if errorlevel 1 exit /b 18

echo [10/34] Faz 6 observation, audit ve evidence dogrulamasi...
"%PYTHON%" scripts\verify_phase6.py
if errorlevel 1 exit /b 19

echo [11/34] Faz 7 verifier ve completion gate dogrulamasi...
"%PYTHON%" scripts\verify_phase7.py
if errorlevel 1 exit /b 20

echo [12/34] Faz 8 checkpoint ve continuity dogrulamasi...
"%PYTHON%" scripts\verify_phase8.py
if errorlevel 1 exit /b 21

echo [13/34] Faz 9 dogrulanmis hafiza dogrulamasi...
"%PYTHON%" scripts\verify_phase9.py
if errorlevel 1 exit /b 22

echo [14/34] Faz 10 kimlik, raporlama ve ozerklik dogrulamasi...
"%PYTHON%" scripts\verify_phase10.py
if errorlevel 1 exit /b 23

echo [15/34] Faz 11 eval ve kabul sinavi dogrulamasi...
"%PYTHON%" scripts\verify_phase11.py
if errorlevel 1 exit /b 24

echo [16/34] Faz 12A runtime kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase12a.py
if errorlevel 1 exit /b 25

echo [17/34] Faz 12B layered context composer dogrulamasi...
"%PYTHON%" scripts\verify_phase12b.py
if errorlevel 1 exit /b 26

echo [18/34] Faz 12C action selection dogrulamasi...
"%PYTHON%" scripts\verify_phase12c.py
if errorlevel 1 exit /b 27

echo [19/34] Faz 12D failure recovery ve isolation dogrulamasi...
"%PYTHON%" scripts\verify_phase12d.py
if errorlevel 1 exit /b 28

echo [20/34] Faz 12E single policy-agent loop dogrulamasi...
"%PYTHON%" scripts\verify_phase12e.py
if errorlevel 1 exit /b 29

echo [21/34] Faz 12F verification, evidence ve learning dogrulamasi...
"%PYTHON%" scripts\verify_phase12f.py
if errorlevel 1 exit /b 30

echo [22/34] Faz 12G runtime E2E ve behavior conformance dogrulamasi...
"%PYTHON%" scripts\verify_phase12g.py
if errorlevel 1 exit /b 31

echo [23/34] Faz 13 real-model compatibility ve controlled rollout dogrulamasi...
"%PYTHON%" scripts\verify_phase13.py
if errorlevel 1 exit /b 32

echo [24/34] Faz 14 research gateway ve evidence RAG dogrulamasi...
"%PYTHON%" scripts\verify_phase14.py
if errorlevel 1 exit /b 33

echo [25/34] Faz 15 resource manager, queue, scheduler ve notifications dogrulamasi...
"%PYTHON%" scripts\verify_phase15.py
if errorlevel 1 exit /b 34

echo [26/34] Faz 16 desktop product shell dogrulamasi...
"%PYTHON%" scripts\verify_phase16.py
if errorlevel 1 exit /b 35

echo [27/34] Faz 17 Discord gateway dogrulamasi...
"%PYTHON%" scripts\verify_phase17.py
if errorlevel 1 exit /b 36

echo [28/34] Faz 18 Voice Gateway dogrulamasi...
"%PYTHON%" scripts\verify_phase18.py
if errorlevel 1 exit /b 37

echo [29/34] Faz 19 trace/dataset governance ve cognitive quality foundation dogrulamasi...
"%PYTHON%" scripts\verify_phase19.py
if errorlevel 1 exit /b 38

echo [30/34] Faz 19B evaluation governance dogrulamasi...
"%PYTHON%" scripts\verify_phase19b.py
if errorlevel 1 exit /b 39

echo [31/34] Faz 19C learning integrity dogrulamasi...
"%PYTHON%" scripts\verify_phase19c.py
if errorlevel 1 exit /b 40

echo [32/34] Faz 19D controlled counterfactual analysis dogrulamasi...
"%PYTHON%" scripts\verify_phase19d.py
if errorlevel 1 exit /b 41

echo [33/34] Faz 19E small controlled SFT governance dogrulamasi...
"%PYTHON%" scripts\verify_phase19e.py
if errorlevel 1 exit /b 42

echo [34/34] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 31
"%PYTHON%" -m luna status
if errorlevel 1 exit /b 32
"%PYTHON%" -m luna list-tools >nul
if errorlevel 1 exit /b 33
"%PYTHON%" -m luna tool-smoke "phase11" >nul
if errorlevel 1 exit /b 34
"%PYTHON%" -m luna workspace-smoke >nul
if errorlevel 1 exit /b 35
"%PYTHON%" -m luna process-smoke >nul
if errorlevel 1 exit /b 36
"%PYTHON%" -m luna audit-smoke >nul
if errorlevel 1 exit /b 37
"%PYTHON%" -m luna verify-smoke >nul
if errorlevel 1 exit /b 38
"%PYTHON%" -m luna checkpoint-smoke >nul
if errorlevel 1 exit /b 39
"%PYTHON%" -m luna memory-smoke >nul
if errorlevel 1 exit /b 40
"%PYTHON%" -m luna phase10-smoke >nul
if errorlevel 1 exit /b 41
"%PYTHON%" -m luna phase11-smoke >nul
if errorlevel 1 exit /b 42
"%PYTHON%" -m luna phase12a-smoke >nul
if errorlevel 1 exit /b 43
"%PYTHON%" -m luna phase12b-smoke >nul
if errorlevel 1 exit /b 44
"%PYTHON%" -m luna phase12c-smoke >nul
if errorlevel 1 exit /b 45
"%PYTHON%" -m luna phase12d-smoke >nul
if errorlevel 1 exit /b 46
"%PYTHON%" -m luna phase12e-smoke >nul
if errorlevel 1 exit /b 47
"%PYTHON%" -m luna phase12f-smoke >nul
if errorlevel 1 exit /b 48
"%PYTHON%" -m luna phase12g-smoke >nul
if errorlevel 1 exit /b 49
"%PYTHON%" -m luna phase13-smoke >nul
if errorlevel 1 exit /b 50
"%PYTHON%" -m luna phase14-smoke >nul
if errorlevel 1 exit /b 51
"%PYTHON%" -m luna phase15-smoke >nul
if errorlevel 1 exit /b 52
"%PYTHON%" -m luna phase16-smoke >nul
if errorlevel 1 exit /b 53
"%PYTHON%" -m luna phase17-smoke >nul
if errorlevel 1 exit /b 54
"%PYTHON%" -m luna phase18-smoke >nul
if errorlevel 1 exit /b 55
"%PYTHON%" -m luna phase19-smoke >nul
if errorlevel 1 exit /b 56
"%PYTHON%" -m luna phase19b-smoke >nul
if errorlevel 1 exit /b 57
"%PYTHON%" -m luna phase19c-smoke >nul
if errorlevel 1 exit /b 58
"%PYTHON%" -m luna phase19d-smoke >nul
if errorlevel 1 exit /b 59
"%PYTHON%" -m luna phase19e-smoke >nul
if errorlevel 1 exit /b 60

echo.
echo [PASS] Luna 0.1 Phase 19E small controlled SFT governance gate passed.
exit /b 0
