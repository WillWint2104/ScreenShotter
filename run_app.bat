@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" .venv\Scripts\pythonw.exe launch.py
) else if exist ".venv\Scripts\python.exe" (
    start "" .venv\Scripts\python.exe launch.py
) else (
    start "" pythonw launch.py
)
