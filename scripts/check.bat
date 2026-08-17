@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON=.venv\Scripts\python.exe"
set "PYTEST_BASETEMP=.pytest_gate_tmp"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%PYTHON%" (
  echo [ERROR] .venv bulunamadi. Once scripts\bootstrap.bat calistir.
  exit /b 3
)

echo [1/47] Package import ve syntax kontrolu...
"%PYTHON%" scripts\verify_syntax.py
if errorlevel 1 exit /b 10

echo [2/47] Pytest...
if exist "%PYTEST_BASETEMP%" rmdir /s /q "%PYTEST_BASETEMP%"
"%PYTHON%" -m pytest -q -p no:cacheprovider --basetemp="%PYTEST_BASETEMP%"
set "PYTEST_EXIT=%ERRORLEVEL%"
if exist "%PYTEST_BASETEMP%" rmdir /s /q "%PYTEST_BASETEMP%"
if not "%PYTEST_EXIT%"=="0" exit /b 11

echo [3/47] Ruff...
"%PYTHON%" -m ruff check .
if errorlevel 1 exit /b 12

echo [4/47] mypy strict...
"%PYTHON%" -m mypy src
if errorlevel 1 exit /b 13

echo [5/47] Faz 1 kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase1.py
if errorlevel 1 exit /b 14

echo [6/47] Faz 2 intent ve context dogrulamasi...
"%PYTHON%" scripts\verify_phase2.py
if errorlevel 1 exit /b 15

echo [7/47] Faz 3 planning ve replan dogrulamasi...
"%PYTHON%" scripts\verify_phase3.py
if errorlevel 1 exit /b 16

echo [8/47] Faz 4 model ve tool dogrulamasi...
"%PYTHON%" scripts\verify_phase4.py
if errorlevel 1 exit /b 17

echo [9/47] Faz 5 workspace, shell ve rollback dogrulamasi...
"%PYTHON%" scripts\verify_phase5.py
if errorlevel 1 exit /b 18

echo [10/47] Faz 6 observation, audit ve evidence dogrulamasi...
"%PYTHON%" scripts\verify_phase6.py
if errorlevel 1 exit /b 19

echo [11/47] Faz 7 verifier ve completion gate dogrulamasi...
"%PYTHON%" scripts\verify_phase7.py
if errorlevel 1 exit /b 20

echo [12/47] Faz 8 checkpoint ve continuity dogrulamasi...
"%PYTHON%" scripts\verify_phase8.py
if errorlevel 1 exit /b 21

echo [13/47] Faz 9 dogrulanmis hafiza dogrulamasi...
"%PYTHON%" scripts\verify_phase9.py
if errorlevel 1 exit /b 22

echo [14/47] Faz 10 kimlik, raporlama ve ozerklik dogrulamasi...
"%PYTHON%" scripts\verify_phase10.py
if errorlevel 1 exit /b 23

echo [15/47] Faz 11 eval ve kabul sinavi dogrulamasi...
"%PYTHON%" scripts\verify_phase11.py
if errorlevel 1 exit /b 24

echo [16/47] Faz 12A runtime kontrat dogrulamasi...
"%PYTHON%" scripts\verify_phase12a.py
if errorlevel 1 exit /b 25

echo [17/47] Faz 12B layered context composer dogrulamasi...
"%PYTHON%" scripts\verify_phase12b.py
if errorlevel 1 exit /b 26

echo [18/47] Faz 12C action selection dogrulamasi...
"%PYTHON%" scripts\verify_phase12c.py
if errorlevel 1 exit /b 27

echo [19/47] Faz 12D failure recovery ve isolation dogrulamasi...
"%PYTHON%" scripts\verify_phase12d.py
if errorlevel 1 exit /b 28

echo [20/47] Faz 12E single policy-agent loop dogrulamasi...
"%PYTHON%" scripts\verify_phase12e.py
if errorlevel 1 exit /b 29

echo [21/47] Faz 12F verification, evidence ve learning dogrulamasi...
"%PYTHON%" scripts\verify_phase12f.py
if errorlevel 1 exit /b 30

echo [22/47] Faz 12G runtime E2E ve behavior conformance dogrulamasi...
"%PYTHON%" scripts\verify_phase12g.py
if errorlevel 1 exit /b 31

echo [23/47] Faz 13 real-model compatibility ve controlled rollout dogrulamasi...
"%PYTHON%" scripts\verify_phase13.py
if errorlevel 1 exit /b 32

echo [24/47] Faz 14 research gateway ve evidence RAG dogrulamasi...
"%PYTHON%" scripts\verify_phase14.py
if errorlevel 1 exit /b 33

echo [25/47] Faz 15 resource manager, queue, scheduler ve notifications dogrulamasi...
"%PYTHON%" scripts\verify_phase15.py
if errorlevel 1 exit /b 34

echo [26/47] Faz 16 desktop product shell dogrulamasi...
"%PYTHON%" scripts\verify_phase16.py
if errorlevel 1 exit /b 35

echo [27/47] Faz 17 Discord gateway dogrulamasi...
"%PYTHON%" scripts\verify_phase17.py
if errorlevel 1 exit /b 36

echo [28/47] Faz 18 Voice Gateway dogrulamasi...
"%PYTHON%" scripts\verify_phase18.py
if errorlevel 1 exit /b 37

echo [29/47] Faz 19 trace/dataset governance ve cognitive quality foundation dogrulamasi...
"%PYTHON%" scripts\verify_phase19.py
if errorlevel 1 exit /b 38

echo [30/47] Faz 19B evaluation governance dogrulamasi...
"%PYTHON%" scripts\verify_phase19b.py
if errorlevel 1 exit /b 39

echo [31/47] Faz 19C learning integrity dogrulamasi...
"%PYTHON%" scripts\verify_phase19c.py
if errorlevel 1 exit /b 40

echo [32/47] Faz 19D controlled counterfactual analysis dogrulamasi...
"%PYTHON%" scripts\verify_phase19d.py
if errorlevel 1 exit /b 41

echo [33/47] Faz 19E small controlled SFT governance dogrulamasi...
"%PYTHON%" scripts\verify_phase19e.py
if errorlevel 1 exit /b 42

echo [34/47] Faz 19F improvement gate dogrulamasi...
"%PYTHON%" scripts\verify_phase19f.py
if errorlevel 1 exit /b 43

echo [35/47] C-002 capability lineage dogrulamasi...
"%PYTHON%" scripts\verify_c002.py
if errorlevel 1 exit /b 44

echo [36/47] C-001 adaptive knowledge retrieval dogrulamasi...
"%PYTHON%" scripts\verify_c001.py
if errorlevel 1 exit /b 45

echo [37/47] C-003 experience distillation dogrulamasi...
"%PYTHON%" scripts\verify_c003.py
if errorlevel 1 exit /b 46

echo [38/47] C-007 debugging capability transfer dogrulamasi...
"%PYTHON%" scripts\verify_c007.py
if errorlevel 1 exit /b 47

echo [39/47] Wave 1 A2/A1 context ve decision-state foundation dogrulamasi...
"%PYTHON%" scripts\verify_wave1.py
if errorlevel 1 exit /b 66

echo [40/47] Wave 2 local-judgment foundation dogrulamasi...
"%PYTHON%" scripts\verify_wave2.py
if errorlevel 1 exit /b 67

echo [41/47] R7-B working session continuity dogrulamasi...
"%PYTHON%" scripts\verify_r7b.py
if errorlevel 1 exit /b 68

echo [42/47] R7-C resume compatibility vector dogrulamasi...
"%PYTHON%" scripts\verify_r7c.py
if errorlevel 1 exit /b 69

echo [43/47] Luna Neural Runtime foundation dogrulamasi...
"%PYTHON%" scripts\verify_neural_runtime.py
if errorlevel 1 exit /b 70

echo [44/47] NR-2A native worker transport dogrulamasi...
"%PYTHON%" scripts\verify_neural_cli_transport.py
if errorlevel 1 exit /b 71

echo [45/47] NR-2B direct native worker dogrulamasi...
"%PYTHON%" scripts\verify_neural_native_transport.py
if errorlevel 1 exit /b 72

echo [46/47] Luna native bridge build governance dogrulamasi...
"%PYTHON%" scripts\verify_neural_native_bridge.py
if errorlevel 1 exit /b 73

echo [47/47] CLI smoke...
"%PYTHON%" -m luna --version
if errorlevel 1 exit /b 31
"%PYTHON%" -m luna status >nul
if errorlevel 1 exit /b 32
"%PYTHON%" -m luna list-tools >nul
if errorlevel 1 exit /b 33
"%PYTHON%" -m luna smoke list >nul
if errorlevel 1 exit /b 34
"%PYTHON%" -m luna smoke c001 >nul
if errorlevel 1 exit /b 35
"%PYTHON%" -m luna smoke phase12f >nul
if errorlevel 1 exit /b 36
"%PYTHON%" -m luna tool-smoke "phase11" >nul
if errorlevel 1 exit /b 37
"%PYTHON%" -m luna c007-smoke >nul
if errorlevel 1 exit /b 38
"%PYTHON%" -m luna capability-lineage C-002 >nul
if errorlevel 1 exit /b 39
"%PYTHON%" -m luna unknown-command >nul 2>nul
set "CLI_FAILURE_EXIT=%ERRORLEVEL%"
if not "%CLI_FAILURE_EXIT%"=="2" exit /b 40
set "SMOKE_ALL_OUTPUT=%TEMP%\luna_smoke_all_%RANDOM%_%RANDOM%.tmp"
"%PYTHON%" -m luna smoke all >"%SMOKE_ALL_OUTPUT%" 2>&1
set "SMOKE_ALL_EXIT=%ERRORLEVEL%"
if not "%SMOKE_ALL_EXIT%"=="0" (
  if exist "%SMOKE_ALL_OUTPUT%" type "%SMOKE_ALL_OUTPUT%"
  if exist "%SMOKE_ALL_OUTPUT%" del /q "%SMOKE_ALL_OUTPUT%"
  exit /b 41
)
if exist "%SMOKE_ALL_OUTPUT%" del /q "%SMOKE_ALL_OUTPUT%"

echo.
echo [PASS] Luna 0.1 Phase 19F + C-002/C-001/C-003/C-007 + Wave 1 A2/A1 + Wave 2 + R7-B/R7-C + Neural Runtime Foundation + NR-2A transport + NR-2B direct-native worker + Native Bridge build governance gate passed.
exit /b 0
