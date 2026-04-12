from flask import Flask, redirect, url_for, session, render_template, request, jsonify
from datetime import timedelta
import os
from dotenv import load_dotenv
from extensions import db, login_manager, bcrypt
from models import User, Transaction, Driver, PaymentSettings
import random
import requests
import datetime
import traceback

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
# Database configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Check if running on VPS (based on path or ENV)
if os.path.exists('/var/www/db/islomcrm.db'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////var/www/db/islomcrm.db'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, "instance", "islomcrm.db")}'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

# Initialize extensions
db.init_app(app)
login_manager.init_app(app)
bcrypt.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create database and seed admin
with app.app_context():
    db.create_all()
    admin_phone = os.getenv('ADMIN_PHONE')
    admin_pin = os.getenv('ADMIN_PIN')
    
    if admin_phone and admin_pin:
        try:
            admin_user = User.query.filter_by(phone=admin_phone).first()
            if not admin_user:
                hashed_pin = bcrypt.generate_password_hash(admin_pin).decode('utf-8')
                new_admin = User(phone=admin_phone, pin_hash=hashed_pin, role='admin')
                db.session.add(new_admin)
                db.session.commit()
                print(f"Admin user seeded: {admin_phone}")
        except Exception as e:
            db.session.rollback()
            print(f"Admin seeding skipped or failed: {e}")

# Import blueprints
from auth.routes import auth_bp
from admin.routes import admin_bp
from user.routes import user_bp
from payments.payme import payme_bp
from payments.click import click_bp

@app.errorhandler(500)
def handle_500(e):
    import traceback
    error_msg = traceback.format_exc()
    with open('error.log', 'a') as f:
        f.write(f"\n{'-'*50}\n{datetime.datetime.now()}\n{error_msg}\n")
    return "Internal Server Error. Please check error.log on server.", 500

@app.route('/debug-errors')
def debug_errors():
    if not os.path.exists('error.log'):
        return "error.log not found."
    with open('error.log', 'r') as f:
        lines = f.readlines()
        return "<pre>" + "".join(lines[-100:]) + "</pre>"

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(payme_bp, url_prefix='/payments')
app.register_blueprint(click_bp, url_prefix='/payments')

# -------------------------------------------------------------
# Background Sync Daemon (Real-time caching architecture)
# -------------------------------------------------------------
import threading
import time
from services import sync_user_drivers

def sync_daemon():
    while True:
        try:
            with app.app_context():
                # 1. Sync Yandex Drivers
                users = User.query.filter_by(yandex_keys_active=True).all()
                for u in users:
                    success, msg = sync_user_drivers(app, u)
                    print(f"Daemon Sync User {u.id}: {msg}")
                
                # 2. Cleanup old Pending transactions (Older than 24 hours)
                threshold = datetime.datetime.now() - datetime.timedelta(hours=24)
                old_pending = Transaction.query.filter(
                    Transaction.status == 'pending',
                    Transaction.created_at < threshold
                ).all()
                
                if old_pending:
                    for t in old_pending:
                        t.status = 'failed'
                        print(f"Daemon: Cancelled old pending transaction {t.id}")
                    db.session.commit()
        except Exception as e:
            print(f"Daemon Sync Error: {str(e)}")
        
        # Kutish: 15 daqiqa (15 * 60 = 900 soniya)
        time.sleep(900)

daemon_thread = threading.Thread(target=sync_daemon, daemon=True)
daemon_thread.start()
# -------------------------------------------------------------

@app.context_processor
def override_url_for():
    return dict(url_for=dated_url_for)

def dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename', None)
        if filename:
            file_path = os.path.join(app.root_path, endpoint, filename)
            try:
                values['q'] = int(os.stat(file_path).st_mtime)
            except OSError:
                pass
    return url_for(endpoint, **values)

@app.before_request
def manage_sessions():
    session.permanent = True
    # Mini App path is /m/..., everything else is Main Site
    if not request.path.startswith('/m/') and not request.path.startswith('/static/'):
        now = datetime.datetime.now()
        last_active_str = session.get('_portal_last_active')
        if last_active_str:
            try:
                last_active = datetime.datetime.fromisoformat(last_active_str)
                if (now - last_active).total_seconds() > 1800: # 30 minutes
                    # Clear session if inactive on main site
                    session.clear()
                    session.permanent = True
            except: pass
        session['_portal_last_active'] = now.isoformat()

@app.route('/m/<code>/<slug>')
def mini_app_landing(code, slug):
    # Public route for Mini App entry (Secured and Robust)
    from flask import render_template, abort
    import re
    
    # 1. Basic format validation to prevent SQL injection or weird characters
    if not re.match(r'^[A-Z0-9]{4}$', code) or not re.match(r'^[a-z0-9\-]{1,100}$', slug):
        abort(404)
        
    try:
        org = User.query.filter_by(org_link_code=code, org_slug=slug).first_or_404()
        
        # Check for existing session
        if session.get('m_driver_phone') and session.get('m_org_id') == code:
            return redirect(url_for('m_driver_dashboard', code=code, slug=slug))
            
        return render_template('mini_app/landing.html', org=org)
    except Exception as e:
        print(f"Mini App Error: {e}")
        # Log to error.log
        with open('error.log', 'a') as f:
            f.write(f"\n{datetime.datetime.now()} - Mini App Error: {str(e)}\n")
        abort(404) # Show generic 404 for security

# --- Mini App API Endpoints ---


def get_eskiz_token():
    email = os.getenv('ESKIZ_EMAIL', 'info@islomcrm.uz')
    password = os.getenv('ESKIZ_PASSWORD', 'K283HAGS738HS')
    try:
        res = requests.post('https://notify.eskiz.uz/api/auth/login', data={'email': email, 'password': password}, timeout=5)
        return res.json().get('data', {}).get('token')
    except: return None

@app.route('/m/<code>/<slug>/check-driver', methods=['POST'])
def m_check_driver(code, slug):
    data = request.get_json()
    phone = data.get('phone', '').strip()
    
    org = User.query.filter_by(org_link_code=code, org_slug=slug).first()
    if not org:
        return jsonify({'status': 'error', 'message': 'Tashkilot topilmadi'}), 404
        
    # 1. Driver existence check
    # We check in the Driver model linked to this Org
    from services import _find_driver_by_phone
    driver = _find_driver_by_phone(phone, org.id)
    if not driver:
        return jsonify({'status': 'error', 'message': 'Haydovchi topilmadi. Avval ro\'yxatdan o\'ting'}), 404

    # 2. Balance check
    settings = PaymentSettings.query.first()
    sms_price = settings.sms_price if settings else 100.0
    
    if org.balance < sms_price:
        return jsonify({'status': 'error', 'message': 'Xatolik yuz berdi, tashkilotingiz bilan bog\'laning'}), 402

    # 3. All good - Deduct balance and Log Transaction
    try:
        org.balance -= sms_price
        new_trans = Transaction(
            user_id=org.id,
            amount=-sms_price, # Negative as it's a deduction
            type='sms_fee',
            status='success',
            payer_phone=phone,
            created_at=datetime.datetime.now()
        )
        db.session.add(new_trans)
        
        # 4. Generate Code
        verify_code = str(random.randint(100000, 999999))
        session[f'm_code_{phone}'] = verify_code
        
        # 5. Send SMS
        token = get_eskiz_token()
        if not token:
            # Rollback deduction on internal error
            db.session.rollback()
            return jsonify({'status': 'error', 'message': 'SMS tizimida muammo. Keyinroq uruning'}), 500
            
        # Determine Template
        if org.sms_status == 'approved':
            message = f"{org.yandex_park_name or org.org_name} web ilovasidan ro'yxatdan o'tish uchun tasdiqlash kodi: {verify_code}"
            org.sms_count_custom = (org.sms_count_custom or 0) + 1
        else:
            message = f"IslomCRM web ilovasidan ro'yxatdan o'tish uchun tasdiqlash kodi: {verify_code} IslomCRM.uz"
            org.sms_count_platform = (org.sms_count_platform or 0) + 1
            
        requests.post('https://notify.eskiz.uz/api/message/sms/send', 
            headers={'Authorization': f'Bearer {token}'},
            data={
                'mobile_phone': phone.replace('+', ''),
                'message': message,
                'from': os.getenv('ESKIZ_ALPHA_NAME', '4546')
            }, timeout=10)
            
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'SMS yuborildi'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Tizimda xatolik: {str(e)}'}), 500

@app.route('/m/<code>/<slug>/verify-code', methods=['POST'])
def m_verify_code(code, slug):
    data = request.get_json()
    phone = data.get('phone', '').strip()
    user_code = data.get('code', '').strip()
    
    if user_code == session.get(f'm_code_{phone}'):
        # Login successful
        session[f'm_driver_phone'] = phone
        session[f'm_org_id'] = code
        session['m_org_slug'] = slug
        # Clear code
        session.pop(f'm_code_{phone}', None)
        return jsonify({'status': 'success', 'redirect': f'/m/{code}/{slug}/dashboard'})
    else:
        return jsonify({'status': 'error', 'message': 'Tasdiqlash kodi noto\'g\'ri'})

@app.route('/m/<code>/<slug>/dashboard')
def m_driver_dashboard(code, slug):
    phone = session.get('m_driver_phone')
    if not phone: return redirect(f'/m/{code}/{slug}')
    
    org = User.query.filter_by(org_link_code=code, org_slug=slug).first_or_404()
    from services import _find_driver_by_phone
    driver = _find_driver_by_phone(phone, org.id)
    
    if not driver:
        # Fallback if driver removed/invalid
        session.clear()
        return redirect(f'/m/{code}/{slug}')
        
    return render_template('mini_app/dashboard.html', org=org, driver=driver)

# --- Mini App Driver Topup Routes ---

@app.route('/m/topup/payme', methods=['POST'])
def m_topup_payme():
    phone = session.get('m_driver_phone')
    code = session.get('m_org_id')
    if not phone or not code:
        return jsonify({'status': 'error', 'message': 'Sessiya muddati tugagan'}), 401
    
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        return jsonify({'status': 'error', 'message': 'Noto\'g\'ri summa'}), 400
    
    amount = int(amount)
    org = User.query.filter_by(org_link_code=code).first_or_404()
    
    if not org.payme_merchant_id or not org.payme_secret_key:
        return jsonify({'status': 'error', 'message': 'Tashkilotda Payme sozlanmagan'}), 400
        
    # Payme setup
    merchant_id = org.payme_merchant_id
    secret_key = org.payme_secret_key
    is_test = org.is_payme_test_mode
    auth_key = org.payme_test_key if is_test and org.payme_test_key else secret_key
    
    api_url = "https://checkout.test.paycom.uz/api" if is_test else "https://checkout.paycom.uz/api"
    checkout_base = "https://checkout.test.paycom.uz" if is_test else "https://checkout.paycom.uz"
    
    headers = {
        "X-Auth": f"{merchant_id}:{auth_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "jsonrpc": "2.0",
        "method": "receipts.create",
        "params": {
            "amount": amount * 100,
            "account": {"phone": phone.replace('+', '')}
        },
        "id": int(os.urandom(4).hex(), 16)
    }
    
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=10)
        res_data = res.json()
        if "error" in res_data:
            return jsonify({'status': 'error', 'message': 'Payme API xatosi'}), 500
            
        receipt_id = res_data["result"]["receipt"]["_id"]
        
        # Create transaction
        new_trans = Transaction(
            user_id=org.id,
            amount=amount,
            type='driver_payment',
            status='pending',
            payme_trans_id=receipt_id,
            payer_phone=phone,
            yandex_sync_status='pending'
        )
        db.session.add(new_trans)
        db.session.commit()
        
        return jsonify({'status': 'success', 'redirect': f"{checkout_base}/{receipt_id}"})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/m/topup/click', methods=['POST'])
def m_topup_click():
    phone = session.get('m_driver_phone')
    code = session.get('m_org_id')
    if not phone or not code:
        return jsonify({'status': 'error', 'message': 'Sessiya muddati tugagan'}), 401
    
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        return jsonify({'status': 'error', 'message': 'Noto\'g\'ri summa'}), 400
    
    amount = int(amount)
    org = User.query.filter_by(org_link_code=code).first_or_404()
    
    if not org.click_service_id or not org.click_merchant_id:
        return jsonify({'status': 'error', 'message': 'Tashkilotda Click sozlanmagan'}), 400
        
    # Create pending transaction
    new_trans = Transaction(
        user_id=org.id,
        amount=amount,
        type='driver_payment',
        status='pending',
        payer_phone=phone,
        yandex_sync_status='pending'
    )
    db.session.add(new_trans)
    db.session.commit()
    
    click_url = (
        f"https://my.click.uz/services/pay?"
        f"service_id={org.click_service_id}&"
        f"merchant_id={org.click_merchant_id}&"
        f"amount={amount}&"
        f"transaction_param={new_trans.id}"
    )
    
    return jsonify({'status': 'success', 'redirect': click_url})


@app.route('/m/logout')
def m_logout():
    code = session.get('m_org_id')
    slug = session.get('m_org_slug') # We should probably store slug too
    session.clear()
    if code and slug:
        return redirect(f'/m/{code}/{slug}')
    return redirect('/')

@app.route('/')
def index():
    # Redirect to user portal by default or show a landing page
    return redirect(url_for('user.dashboard'))


# --- Telegram Bot Webhook ---
@app.route('/bot/webhook/<token>', methods=['POST'])
def bot_webhook(token):
    from bot_handlers import process_bot_update
    org = User.query.filter_by(tg_bot_token=token).first()
    if not org:
        return "Invalid token", 404
        
    try:
        update_json = request.get_json()
        process_bot_update(token, update_json, org, app.app_context())
        return "OK", 200
    except Exception as e:
        print(f"Bot Webhook Error: {e}")
        return str(e), 500

# --- Mini App Telegram Linkage ---
@app.route('/m/link-telegram', methods=['POST'])
def m_link_telegram():
    import logging
    try:
        phone = session.get('m_driver_phone')
        code = session.get('m_org_id')
        data = request.get_json()
        tg_id = data.get('telegram_id') if data else None
        
        # LOGGING FOR DEBUGGING
        log_msg = f"Linkage Request: phone={phone}, code={code}, tg_id={tg_id}"
        with open('error.log', 'a') as f:
            f.write(f"\n{datetime.datetime.now()} - {log_msg}\n")
            
        if not phone or not code:
            return jsonify({'status': 'error', 'message': 'Session expired or missing'}), 401
            
        if not tg_id:
            return jsonify({'status': 'error', 'message': 'No telegram_id provided'}), 400
            
        org = User.query.filter_by(org_link_code=code).first()
        if not org:
            return jsonify({'status': 'error', 'message': 'Org not found'}), 404
            
        from services import _find_driver_by_phone
        driver = _find_driver_by_phone(phone, org.id)
        if driver:
            # Check if this telegram_id is already used by ANOTHER driver (to prevent hijacking)
            existing = Driver.query.filter_by(telegram_id=str(tg_id)).first()
            if not existing or existing.id == driver.id:
                driver.telegram_id = str(tg_id)
                db.session.commit()
                with open('error.log', 'a') as f:
                    f.write(f"{datetime.datetime.now()} - Success: Linked {phone} to TG {tg_id}\n")
                return jsonify({'status': 'success'})
        
        return jsonify({'status': 'error', 'message': 'Driver not found'})
    except Exception as e:
        with open('error.log', 'a') as f:
            f.write(f"{datetime.datetime.now()} - Linkage EXCEPTION: {str(e)}\n")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
