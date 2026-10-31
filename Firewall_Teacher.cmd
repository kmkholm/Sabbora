@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Sabbora Teacher" >nul 2>&1
netsh advfirewall firewall add rule name="Sabbora Teacher" dir=in action=allow protocol=TCP localport=47000-47019 profile=any
echo Sabbora teacher port 47000-47019 (TCP) is now open.
pause
