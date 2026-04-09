from flask import Flask, redirect, url_for, session
from datetime import timedelta
import os
from dotenv import load_dotenv
from extensions import db, login_manager, bcrypt
from models import User

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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

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

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(payme_bp, url_prefix='/payments')

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
                users = User.query.filter_by(yandex_keys_active=True).all()
                for u in users:
                    success, msg = sync_user_drivers(app, u)
                    print(f"Daemon Sync User {u.id}: {msg}")
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

@app.route('/')
def index():
    # Redirect to user portal by default or show a landing page
    return redirect(url_for('user.dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
