@echo off
REM Step 2 Auto Monitor - Run in separate window with real-time output
cd /d %~dp0\..
echo ======================================================================
echo   Step 2: Data Import - Real-time Output Window
echo ======================================================================
echo.
python -u scripts\step2_run_import.py
echo.
echo ======================================================================
echo   Process Completed
echo ======================================================================
pause
