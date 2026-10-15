@echo off
cd /d "%~dp0"
py -3 observatory.py "%~dp0samples\self-build.jsonl"
if errorlevel 1 pause
