@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -Sta -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
set "BILI_NOTES_EXIT_CODE=%ERRORLEVEL%"

if not "%BILI_NOTES_EXIT_CODE%"=="0" (
    echo.
    echo [启动失败] 错误信息已保留在上方，请截图后再按任意键关闭。
    pause >nul
)

exit /b %BILI_NOTES_EXIT_CODE%
