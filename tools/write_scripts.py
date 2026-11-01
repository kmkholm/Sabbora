"""Write the Windows .cmd helpers with CRLF line endings."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\ProgramData\anaconda3\envs\tawfik"

SCRIPTS = {
    "Sabbora_Teacher.cmd": rf"""@echo off
rem Run from source. Uses the "tawfik" conda env when present, otherwise pythonw on PATH.
set "PYW=pythonw"
if exist "{PY}\pythonw.exe" set "PYW={PY}\pythonw.exe"
start "" "%PYW%" "%~dp0run_teacher.py"
""",
    "Sabbora_Student.cmd": rf"""@echo off
rem Run from source. Uses the "tawfik" conda env when present, otherwise pythonw on PATH.
set "PYW=pythonw"
if exist "{PY}\pythonw.exe" set "PYW={PY}\pythonw.exe"
start "" "%PYW%" "%~dp0run_student.py" %*
""",
    "Build_EXE.cmd": rf"""@echo off
setlocal
cd /d "%~dp0"
rem Needs Python with: pip install pyqt5 pillow qtawesome pyinstaller
set "PY=python"
if exist "{PY}\python.exe" set "PY={PY}\python.exe"
if exist "{PY}\Library\bin" set "PATH={PY};{PY}\Library\bin;%PATH%"
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
""",
    "Firewall_Teacher.cmd": r"""@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Sabbora Teacher" >nul 2>&1
netsh advfirewall firewall add rule name="Sabbora Teacher" dir=in action=allow protocol=TCP localport=47000-47019,47080-47099 profile=any
echo Sabbora teacher ports 47000-47019 and 47080-47099 (TCP) are now open.
pause
""",
    "Firewall_Student.cmd": r"""@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Sabbora Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="Sabbora Discovery" dir=in action=allow protocol=UDP localport=47001 profile=any
echo Sabbora discovery port 47001 (UDP) is now open.
pause
""",
}

for name, text in SCRIPTS.items():
    with open(os.path.join(ROOT, name), "w", encoding="ascii", newline="\r\n") as f:
        f.write(text)
    print("wrote", name)
