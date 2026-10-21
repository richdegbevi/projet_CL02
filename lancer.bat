@echo off
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
python interface_cl02.py
