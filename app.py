from flask import Flask, redirect, url_for
import os
from dotenv import load_dotenv
from extensions import db, login_manager, bcrypt
from models import User

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///islomcrm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
    admin_phone = os.getenv('ADMIN_PHONE', '+998999998877') # Failsafe default just in case .env misses it
    admin_pin = os.getenv('ADMIN_PIN', '121415')
    
    if admin_phone and admin_pin:
        admin_user = User.query.filter_by(phone=admin_phone).first()
        if not admin_user:
            hashed_pin = bcrypt.generate_password_hash(admin_pin).decode('utf-8')
            new_admin = User(phone=admin_phone, pin_hash=hashed_pin, role='admin')
            db.session.add(new_admin)
            db.session.commit()
            print(f"Admin user seeded: {admin_phone}")

# Import blueprints
from auth.routes import auth_bp
from admin.routes import admin_bp
from user.routes import user_bp

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(user_bp, url_prefix='/user')

@app.route('/')
def index():
    # Redirect to user portal by default or show a landing page
    return redirect(url_for('user.dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
