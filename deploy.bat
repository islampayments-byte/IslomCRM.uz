@echo off
echo O'zgarishlar Github'ga yuborilmoqda...
git add .
git commit -m "Admin paneldagi barcha sahifalar Premium darajadagi dizaynga o'tkazildi"
git push origin main

echo.
echo Server o'zgarishlari amalga oshirilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && systemctl restart islomcrm"

echo.
echo Keraksiz fayllar o'chirilmoqda...
del deploy.bat

echo.
echo Barcha jarayonlar muvaffaqiyatli tugadi! Oynani yopishingiz mumkin.
pause
