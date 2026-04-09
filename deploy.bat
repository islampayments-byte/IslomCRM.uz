@echo off
echo O'zgarishlar Github'ga yuborilmoqda...
git add .
git commit -m "Added Yandex Fleet API key management feature"
git push origin main

echo.
echo Server o'zgarishlarni qabul qilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && source venv/bin/activate && python migrate.py && systemctl restart islomcrm"

echo.
echo Barcha jaryonlar yakunlandi! Yandex Integratsiyasi ulandi va baza yangilandi.
pause
