@echo off
echo ================================================
echo   IslomCRM Deploy - Serverni yangilash
echo ================================================
echo.

echo [1/3] O'zgarishlar Github'ga yuborilmoqda...
git add -A
git commit -m "Deploy: update server"
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo [XATO] Git push muvaffaqiyatsiz bo'ldi!
    pause
    exit /b 1
)

echo.
echo [2/3] Server o'zgarishlarni qabul qilmoqda va migrate ishlatilmoqda...
ssh root@45.138.158.217 "cd /var/www/islomcrm && git pull origin main && source venv/bin/activate && python migrate.py && systemctl restart islomcrm && sleep 2 && systemctl is-active islomcrm && echo '=== DEPLOY MUVAFFAQIYATLI ==='"

if %errorlevel% neq 0 (
    echo.
    echo [XATO] SSH deploy muvaffaqiyatsiz bo'ldi!
    pause
    exit /b 1
)

echo.
echo [3/3] Barcha jarayonlar yakunlandi!
echo ================================================
pause
