import sqlite3
import os
import re

# Try production DB first, then local
db_path = '/var/www/db/islomcrm.db'
if not os.path.exists(db_path):
    print(f"Baza {db_path} topilmadi. Mahalliy bazaga urinib ko'ramiz...")
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'islomcrm.db')

if not os.path.exists(db_path):
    print("Ma'lumotlar bazasi fayli topilmadi!")
    exit(1)

print(f"Ulanilayotgan baza: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()


def add_column(table, col_name, col_def):
    """Safely add a column if it doesn't already exist."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        print(f"  [+] {table}.{col_name} qo'shildi")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  [=] {table}.{col_name} allaqachon mavjud")
        else:
            print(f"  [!] {table}.{col_name} da xatolik: {e}")


print("\n--- users jadvalini yangilash ---")
add_column('users', 'yandex_park_name', 'VARCHAR(255)')
add_column('users', 'yandex_park_id',   'VARCHAR(255)')
add_column('users', 'yandex_client_id', 'VARCHAR(255)')
add_column('users', 'yandex_api_key',   'VARCHAR(255)')
add_column('users', 'yandex_keys_active', 'BOOLEAN DEFAULT 0')
add_column('users', 'balance',           'FLOAT DEFAULT 0.0')
add_column('users', 'stir',              'VARCHAR(9)')
add_column('users', 'org_name',          'VARCHAR(255)')
add_column('users', 'director',          'VARCHAR(255)')
add_column('users', 'ifut',              'VARCHAR(10)')
add_column('users', 'email',             'VARCHAR(120)')
add_column('users', 'org_phone',         'VARCHAR(20)')
add_column('users', 'address',           'TEXT')
add_column('users', 'is_verified',       'BOOLEAN DEFAULT 0')
add_column('users', 'last_ip',           'VARCHAR(45)')
add_column('users', 'failed_attempts',   'INTEGER DEFAULT 0')
add_column('users', 'is_blocked',        'BOOLEAN DEFAULT 0')
add_column('users', 'org_slug',          'VARCHAR(100)')
add_column('users', 'payme_merchant_id', 'VARCHAR(100)')
add_column('users', 'payme_secret_key',  'VARCHAR(255)')
add_column('users', 'payme_test_key',    'VARCHAR(255)')
add_column('users', 'is_payme_test_mode', 'BOOLEAN DEFAULT 1')


print("\n--- payment_settings jadvalini tekshirish ---")
cursor.execute("""
CREATE TABLE IF NOT EXISTS payment_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payme_merchant_id VARCHAR(100),
    payme_secret_key VARCHAR(255),
    payme_test_key VARCHAR(255),
    is_test_mode BOOLEAN DEFAULT 1,
    min_topup_amount INTEGER DEFAULT 1000,
    max_topup_amount INTEGER DEFAULT 10000000,
    payme_account_field VARCHAR(50) DEFAULT 'phone'
)
""")
print("  [=] payment_settings jadvali mavjud yoki yaratildi")


print("\n--- transactions jadvalini tekshirish ---")
cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount FLOAT NOT NULL,
    type VARCHAR(20),
    status VARCHAR(20) DEFAULT 'pending',
    payme_trans_id VARCHAR(100) UNIQUE,
    created_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")
print("  [=] transactions jadvali mavjud yoki yaratildi")


print("\n--- drivers jadvalini tekshirish ---")
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
print("  [=] drivers jadvali mavjud yoki yaratildi")


# Auto-generate org_slug from yandex_park_name if missing
print("\n--- org_slug ni to'ldirish ---")
cursor.execute("SELECT id, yandex_park_name FROM users WHERE org_slug IS NULL AND yandex_park_name IS NOT NULL")
rows = cursor.fetchall()
for uid, name in rows:
    if name:
        slug = re.sub(r'[^a-z0-9]', '-', name.lower()).strip('-')
        # Check uniqueness
        existing = cursor.execute("SELECT id FROM users WHERE org_slug = ?", (slug,)).fetchone()
        if existing:
            import random
            slug = f"{slug}-{random.randint(100, 999)}"
        cursor.execute("UPDATE users SET org_slug = ? WHERE id = ?", (slug, uid))
        print(f"  [+] User {uid} -> org_slug: {slug}")

if not rows:
    print("  [=] Barchasi allaqachon to'liq")


conn.commit()
conn.close()
print("\nMigratsiya muvaffaqiyatli yakunlandi!")
