import requests
import os
import sqlite3

# Database path (production path on VPS)
PROD_DB = '/var/www/db/islomcrm.db'
LOCAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'islomcrm.db')

db_path = PROD_DB if os.path.exists(PROD_DB) else LOCAL_DB

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Find all bots with tokens
cursor.execute("SELECT tg_bot_token, tg_bot_username FROM users WHERE tg_bot_token IS NOT NULL")
bots = cursor.fetchall()

print(f"Found {len(bots)} bots to configure.")

for token, username in bots:
    webhook_url = f"https://islomcrm.uz/bot/webhook/{token}"
    set_webhook_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
    
    try:
        resp = requests.get(set_webhook_url, timeout=10)
        data = resp.json()
        status = "SUCCESS" if data.get('ok') else "FAILED"
        print(f"Bot @{username} ({token[:10]}...): {status} -> {data.get('description', '')}")
    except Exception as e:
        print(f"Bot @{username} Error: {e}")

conn.close()
print("Bot webhook maintenance completed.")
