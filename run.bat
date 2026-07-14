@echo off
rem Double-click to launch Corvid (no console window). Pass --dev for a throwaway data dir.
start "" pythonw "%~dp0run.py" %*
