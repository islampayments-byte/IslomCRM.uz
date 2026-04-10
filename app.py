from flask import Flask, redirect, url_for, session
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

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
def make_session_permanent():
    session.permanent = True

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
from flask import request, jsonify

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
        # Clear code
        session.pop(f'm_code_{phone}', None)
        return jsonify({'status': 'success', 'redirect': f'/m/{code}/{slug}/dashboard'})
    else:
        return jsonify({'status': 'error', 'message': 'Tasdiqlash kodi noto\'g\'ri'})

@app.route('/m/<code>/<slug>/dashboard')
def m_driver_dashboard(code, slug):
    # Dummy dashboard for now
    phone = session.get('m_driver_phone')
    if not phone: return redirect(f'/m/{code}/{slug}')
    return f"<h1>Salom, {phone}! Siz tizimga kirdingiz.</h1><p>Tez kunda bu yerda sizning balansingiz ko'rinadi.</p>"

@app.route('/')
def index():
    # Redirect to user portal by default or show a landing page
    return redirect(url_for('user.dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
