@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Sabbora Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="Sabbora Discovery" dir=in action=allow protocol=UDP localport=47001 profile=any
echo Sabbora discovery port 47001 (UDP) is now open.
pause
