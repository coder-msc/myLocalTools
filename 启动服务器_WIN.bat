@echo off
chcp 936 >nul
title 接口调试工具箱 DevToolbox - 启动器
cd /d "%~dp0"

echo ============================================
echo    接口调试工具箱 DevToolbox
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

set PORT=6868

echo [1/4] 正在停止占用端口 %PORT% 的旧服务（含僵死进程）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    echo        - 结束旧进程 PID %%a
    taskkill /PID %%a /F >nul 2>&1
)
echo        清理完成

echo [2/4] 等待端口释放...
set WAIT=0
:waitlp
netstat -ano | findstr ":%PORT% " | findstr LISTENING >nul 2>&1
if %errorlevel% neq 0 goto portfree
set /a WAIT+=1
if %WAIT% geq 10 (
    echo [警告] 端口仍被占用，将尝试继续启动
    goto startserver
)
ping -n 2 127.0.0.1 >nul
goto waitlp
:portfree
echo        端口已释放

:startserver
echo [3/4] 启动服务器进程...
start "DevToolbox 服务器 (端口 %PORT%)" /D "%~dp0" cmd /k python server.py

echo [4/4] 等待服务就绪（健康检查，最多 15 秒）...
set TRIES=0
:readylp
set /a TRIES+=1
if %TRIES% gtr 15 goto readyfail
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://localhost:%PORT%/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 goto readydone
ping -n 2 127.0.0.1 >nul
goto readylp

:readydone
echo.
echo ============================================
echo   启动成功！
echo   本机访问:   http://localhost:%PORT%/
echo   局域网访问: 用本机 IP 替换 localhost
echo ============================================
start "" "http://localhost:%PORT%/"
echo.
echo 关闭服务器：关闭弹出的 DevToolbox 服务器窗口即可。
ping -n 5 127.0.0.1 >nul
exit /b 0

:readyfail
echo.
echo [错误] 服务在 15 秒内未响应 HTTP 请求。
echo 请查看弹出的 DevToolbox 服务器窗口中的报错信息。
echo.
pause
exit /b 1
