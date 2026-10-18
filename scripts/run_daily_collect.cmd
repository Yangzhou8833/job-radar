@echo off
rem Daily collection (stage A, no LLM) for Windows Task Scheduler. See README "Run it every day".
rem Set PYTHON below if python is not on the PATH of the scheduled task.
cd /d "%~dp0.."
if "%PYTHON%"=="" set "PYTHON=python"
set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
set PYTHONIOENCODING=utf-8
if not exist data\runs mkdir data\runs
echo ==== %DATE% %TIME% start >> data\runs\scheduler_stdout.txt
"%PYTHON%" -X utf8 radar.py collect --ensure-today >> data\runs\scheduler_stdout.txt 2>&1
echo ==== %DATE% %TIME% exit %ERRORLEVEL% >> data\runs\scheduler_stdout.txt
