@echo off
set PYTHONPATH=C:\Users\Sahil\HyperLiquid\src
set PYTHONIOENCODING=utf-8
echo [%date% %time%] Starting whale discovery >> C:\Users\Sahil\HyperLiquid\logs\discover.log
C:\Users\Sahil\HyperLiquid\.venv\Scripts\python.exe -m hyperwhale discover --min-av=500000 --max=2500 >> C:\Users\Sahil\HyperLiquid\logs\discover.log 2>&1
echo [%date% %time%] Discovery finished >> C:\Users\Sahil\HyperLiquid\logs\discover.log
