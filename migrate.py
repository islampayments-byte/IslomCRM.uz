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

conn.commit()
conn.close()
print("Migratsiya muvaffaqiyatli yakunlandi!")
