@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

call "%~dp0check.bat"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [DONE] Luna kalite kapisi basariyla tamamlandi.
) else (
    echo [ERROR] Luna kalite kapisi %EXIT_CODE% cikis koduyla durdu.
)

echo.
echo Pencereyi kapatmak icin bir tusa basin...
pause >nul

exit /b %EXIT_CODE%
