@echo off
echo O'zgarishlar Github'ga yuborilmoqda...
git add .
git commit -m "Add advanced VPS metrics: Network, Swap, DB Size, Load Avg, Security logs"
git push origin main

echo.
echo Server o'zgarishlarni qabul qilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && systemctl restart islomcrm"

echo.
echo Barcha jaryonlar yakunlandi! Brauzerni yangilab (Ctrl+R) admin panelni tekshiring.
pause
