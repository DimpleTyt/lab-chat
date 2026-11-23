@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 not found. Install it or run from another folder.
  pause
  exit /b 1
)
python -X utf8 "%~dp0labchat-offline.py" %*
if errorlevel 1 pause
