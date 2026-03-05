@echo off
cd /d C:\Users\Sahil\HyperLiquid
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\run.py >> logs\scheduler.log 2>&1
