@echo off
REM Wrapper used by Windows Task Scheduler. Logs every run to checker.log.
cd /d "%~dp0"
echo. >> checker.log
echo ===== %DATE% %TIME% ===== >> checker.log
python checker.py >> checker.log 2>&1
