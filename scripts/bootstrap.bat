@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python 3.12 bulunamadi.
    exit /b 3
  )
  set "PYTHON=py -3.12"
)
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Luna gelistirme ortami olusturuluyor...
  %PYTHON% -m venv .venv
  if errorlevel 1 exit /b 4
)
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools
if errorlevel 1 exit /b 5
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 exit /b 6
echo [PASS] Kurulum tamamlandi.
echo Sonraki komut: scripts\check.bat
