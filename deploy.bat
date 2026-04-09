@echo off
echo O'zgarishlar Github'ga yuborilmoqda...
git add .
git commit -m "Fix: resolve 500 error - complete migration and dual payment support"
git push origin main

echo.
echo Server o'zgarishlarni qabul qilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && source venv/bin/activate && python migrate.py && systemctl restart islomcrm && echo 'SERVER RESTARTED OK'"

echo.
echo Barcha jarayonlar yakunlandi!
pause
