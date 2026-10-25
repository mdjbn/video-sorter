@echo off
REM 一键启动（Windows）
setlocal
cd /d "%~dp0"

if not exist "server\.venv\Scripts\python.exe" (
  echo 创建 Python 虚拟环境 server\.venv
  python -m venv server\.venv || goto :err
  server\.venv\Scripts\python.exe -m pip install -q --upgrade pip
  server\.venv\Scripts\python.exe -m pip install -q -r server\requirements.txt || goto :err
)

if not exist "web\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo 未找到 npm，跳过网页端构建；服务端会显示一个提示页。
  ) else (
    echo 构建网页端...
    pushd web
    call npm install --no-audit --no-fund
    call npm run build
    popd
  )
)

cd server
server\.venv\Scripts\python.exe -m videosorter --web-dir "..\web\dist" %*
goto :eof

:err
echo 启动失败，请检查上面的错误信息。
pause
