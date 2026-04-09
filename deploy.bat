@echo off
echo Vaqt sozlamalari (O'zbekiston vaqti) tizimga kiritildi...
git add .
git commit -m "Configure all timestamps to use local time (Uzbekistan timezone)"
git push origin main

echo.
echo Server vaqt mintaqasi O'zbekistonga (Asia/Tashkent) o'zgartirilmoqda va kod yangilanmoqda...
ssh root@45.138.158.217 "timedatectl set-timezone Asia/Tashkent && cd /var/www/islomcrm && git pull origin main && systemctl restart islomcrm"

echo.
echo Keraksiz fayllar o'chirilmoqda...
del deploy.bat

echo.
echo Barcha jaryonlar yakunlandi! Endi hammasi siz xohlagandek O'zbekiston vaqti bo'yicha ishlaydi.
pause
