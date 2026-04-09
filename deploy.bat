@echo off
echo O'zgarishlar Github'ga yuborilmoqda...
git add .
git commit -m "Enhance VPS Management UI to professional design"
git push origin main

echo Server o'zgarishlari amalga oshirilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && systemctl restart islomcrm"

echo Keraksiz fayllar o'chirilmoqda...
del run_git.py
del run_vps.py
del .deploy.py
del run_git2.py
del deploy.bat

echo Barcha jarayonlar tugadi! Oynani yopishingiz mumkin.
pause
