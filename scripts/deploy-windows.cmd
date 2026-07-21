@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-windows.ps1"
set "deploy_exit_code=%ERRORLEVEL%"

echo.
if "%deploy_exit_code%"=="0" (
    echo [AdCraft] Deployment command ended. Review the messages above before closing.
) else (
    echo [AdCraft] Deployment stopped with exit code %deploy_exit_code%. Review the messages above.
)
echo.
pause
exit /b %deploy_exit_code%
