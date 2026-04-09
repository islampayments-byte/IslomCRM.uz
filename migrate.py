import sqlite3
import os

db_path = '/var/www/db/islomcrm.db'

# Fallback for local testing if the production DB doesn't exist
if not os.path.exists(db_path):
    print(f"Baza {db_path} topilmadi. Mahalliy (local) bazaga urinib ko'ramiz...")
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'islomcrm.db')

if not os.path.exists(db_path):
    print("Ma'lumotlar bazasi fayli umuman topilmadi!")
    exit(1)

print(f"Ulanilayotgan baza: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columns_to_add = [
    "yandex_park_name VARCHAR(255)",
    "yandex_park_id VARCHAR(255)",
    "yandex_client_id VARCHAR(255)",
    "yandex_api_key VARCHAR(255)",
    "yandex_keys_active BOOLEAN DEFAULT 0"
]

for col in columns_to_add:
    col_name = col.split(' ')[0]
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col}")
        print(f"Ustun tushirildi: {col_name}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Ustun allaqachon mavjud: {col_name}")
        else:
            print(f"Xatolik: {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN org_slug VARCHAR(100)")
    cursor.execute("ALTER TABLE users ADD COLUMN payme_merchant_id VARCHAR(100)")
    cursor.execute("ALTER TABLE users ADD COLUMN payme_secret_key VARCHAR(255)")
    cursor.execute("ALTER TABLE users ADD COLUMN payme_test_key VARCHAR(255)")
    cursor.execute("ALTER TABLE users ADD COLUMN is_payme_test_mode BOOLEAN DEFAULT 1")
    print("Yangi ustunlar (org_slug, payme test/prod) muvaffaqiyatli qo'shildi.")
except Exception as e:
    if "duplicate column name" in str(e).lower():
        print("Ustunlar allaqachon mavjud, davom etamiz...")
    else:
        print(f"Xatolik: {e}")

# org_slug ni mavjud yandex_park_name dan to'ldirish (agar bo'sh bo'lsa)
try:
    cursor.execute("SELECT id, yandex_park_name FROM users WHERE org_slug IS NULL AND yandex_park_name IS NOT NULL")
    users_to_update = cursor.fetchall()
    for uid, name in users_to_update:
        if name:
            import re
            slug = re.sub(r'[^a-z0-9]', '-', name.lower()).strip('-')
            cursor.execute("UPDATE users SET org_slug = ? WHERE id = ?", (slug, uid))
    print("Mavjud foydalanuvchilar uchun org_slug identifikatorlari yaratildi.")
except Exception as e:
    print(f"Slug yaratishda xato: {e}")

try:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        yandex_driver_id VARCHAR(100) NOT NULL,
        first_name VARCHAR(100),
        last_name VARCHAR(100),
        phone VARCHAR(50),
        status VARCHAR(50) DEFAULT 'working',
        created_at DATETIME,
        last_sync DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    print("Drivers jadvali muvaffaqiyatli tekshirildi/yaratildi.")
except Exception as e:
    print(f"Xatolik drivers jadvalini tuzishda: {e}")

conn.commit()
conn.close()
print("Migratsiya muvaffaqiyatli yakunlandi!")
