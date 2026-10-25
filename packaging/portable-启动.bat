@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:8080
videosorter-server.exe --host 127.0.0.1 --port 8080 --web-dir webdist
pause
