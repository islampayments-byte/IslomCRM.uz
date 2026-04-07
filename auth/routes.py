from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import User
from extensions import db, bcrypt
import re

auth_bp = Blueprint('auth', __name__, template_folder='../templates')

@auth_bp.route('/login', methods=['GET'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))
    return render_template('auth/login.html')

@auth_bp.route('/check_phone', methods=['POST'])
def check_phone():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    
    # Simple validation for +998...
    if not re.match(r'^\+998\d{9}$', phone):
        return jsonify({'status': 'error', 'message': 'Noto\'g\'ri telefon raqami formati. Namuna: +998901234567'}), 400

    user = User.query.filter_by(phone=phone).first()
    if user:
        return jsonify({'status': 'exists', 'message': 'PIN kodni kiriting'})
    else:
        return jsonify({'status': 'not_found', 'message': 'Foydalanuvchi topilmadi. Ro\'yxatdan o\'ting'})

@auth_bp.route('/verify_pin', methods=['POST'])
def verify_pin():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    pin = data.get('pin', '').strip()

    user = User.query.filter_by(phone=phone).first()
    if not user:
        return jsonify({'status': 'error', 'message': 'Foydalanuvchi topilmadi'}), 404

    if user.check_pin(pin, bcrypt):
        login_user(user)
        redirect_url = url_for('admin.dashboard') if user.role == 'admin' else url_for('user.dashboard')
        return jsonify({'status': 'success', 'redirect': redirect_url})
    else:
        return jsonify({'status': 'error', 'message': 'Noto\'g\'ri PIN kod'})

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))
        
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        pin = request.form.get('pin', '').strip()
        
        if not re.match(r'^\+998\d{9}$', phone):
            flash('Noto\'g\'ri telefon raqami formati', 'danger')
            return redirect(url_for('auth.register'))
            
        if len(pin) != 6 or not pin.isdigit():
            flash('PIN kod 6 ta raqamdan iborat bo\'lishi shart', 'danger')
            return redirect(url_for('auth.register'))

        existing_user = User.query.filter_by(phone=phone).first()
        if existing_user:
            flash('Bu raqam orqali avval ro\'yxatdan o\'tilgan', 'warning')
            return redirect(url_for('auth.login'))

        hashed_pin = bcrypt.generate_password_hash(pin).decode('utf-8')
        new_user = User(phone=phone, pin_hash=hashed_pin)
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('user.dashboard'))

    return render_template('auth/register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
