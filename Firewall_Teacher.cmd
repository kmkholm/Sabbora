@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Sabbora Teacher" >nul 2>&1
netsh advfirewall firewall add rule name="Sabbora Teacher" dir=in action=allow protocol=TCP localport=47000-47019,47080-47099 profile=any
echo Sabbora teacher ports 47000-47019 and 47080-47099 (TCP) are now open.
pause
