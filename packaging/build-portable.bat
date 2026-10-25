@echo off
rem Windows 免安装（绿色版）：把后端 + 网页端 + ffmpeg 打成一个可直接双击的目录。
rem 需要：Python 3.10+、Node 18+；打包机与目标机同为 64 位 Windows。
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo [1/4] 构建网页端
pushd web
call npm install || goto :err
call npm run build || goto :err
popd

echo [2/4] 安装打包依赖
python -m venv server\.venv || goto :err
server\.venv\Scripts\python -m pip install -q -r server\requirements.txt || goto :err
server\.venv\Scripts\python -m pip install -q pyinstaller || goto :err

echo [3/4] PyInstaller 打包后端（含 webdist）
server\.venv\Scripts\pyinstaller server\videosorter.spec --distpath dist\portable --workpath build\pyi --noconfirm || goto :err
xcopy /E /I /Y web\dist dist\portable\videosorter-server\webdist >nul

echo [4/4] 收尾
copy /Y packaging\portable-启动.bat dist\portable\videosorter-server\启动.bat >nul
if not exist dist\portable\videosorter-server\tools mkdir dist\portable\videosorter-server\tools
if exist server\tools\ffmpeg.exe  copy /Y server\tools\ffmpeg.exe  dist\portable\videosorter-server\tools\ >nul
if exist server\tools\ffprobe.exe copy /Y server\tools\ffprobe.exe dist\portable\videosorter-server\tools\ >nul
echo.
echo 完成：dist\portable\videosorter-server\  双击「启动.bat」即可用浏览器打开 http://127.0.0.1:8080
exit /b 0

:err
echo.
echo 构建失败（上一条命令返回了错误）。
exit /b 1
