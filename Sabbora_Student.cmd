@echo off
rem Run from source. Uses the "tawfik" conda env when present, otherwise pythonw on PATH.
set "PYW=pythonw"
if exist "C:\ProgramData\anaconda3\envs\tawfik\pythonw.exe" set "PYW=C:\ProgramData\anaconda3\envs\tawfik\pythonw.exe"
start "" "%PYW%" "%~dp0run_student.py" %*
