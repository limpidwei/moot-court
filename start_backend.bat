@echo off
cd /d C:\Users\86186\moot-court
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
