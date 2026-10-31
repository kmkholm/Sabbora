@echo off
setlocal
cd /d "%~dp0"
rem Needs Python with: pip install pyqt5 pillow qtawesome pyinstaller
set "PY=python"
if exist "C:\ProgramData\anaconda3\envs\tawfik\python.exe" set "PY=C:\ProgramData\anaconda3\envs\tawfik\python.exe"
if exist "C:\ProgramData\anaconda3\envs\tawfik\Library\bin" set "PATH=C:\ProgramData\anaconda3\envs\tawfik;C:\ProgramData\anaconda3\envs\tawfik\Library\bin;%PATH%"
echo === Sabbora: building SabboraTeacher.exe and SabboraStudent.exe ===
"%PY%" tools\make_icon.py || goto :fail
set "OPTS=--noconfirm --clean --onefile --windowed --icon assets\sabbora.ico --collect-data qtawesome --hidden-import qtpy --exclude-module PySide6 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module shiboken6 --exclude-module numpy --exclude-module scipy --exclude-module pandas --exclude-module matplotlib --exclude-module torch --exclude-module tkinter --exclude-module PyQt5.QtWebEngineWidgets --exclude-module PyQt5.QtWebEngineCore"
"%PY%" -m PyInstaller %OPTS% --name SabboraTeacher run_teacher.py || goto :fail
"%PY%" -m PyInstaller %OPTS% --name SabboraStudent run_student.py || goto :fail
echo.
echo Done: dist\SabboraTeacher.exe  and  dist\SabboraStudent.exe
explorer dist
exit /b 0
:fail
echo BUILD FAILED
pause
exit /b 1
