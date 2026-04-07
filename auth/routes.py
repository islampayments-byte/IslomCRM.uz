from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
import os
from models import User
from extensions import db, bcrypt
import re
import requests
from bs4 import BeautifulSoup
import random
import json
from flask import session

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

    # Admin yashirin kirish yo'li (frontend dan daxlsiz yuboriladi)
    if phone == 'admin_shortcut':
        phone = os.getenv('ADMIN_PHONE')

    # Ulanish manzilini aniqlash (Nginx orqali haqiqiy IP ni olish)
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    user = User.query.filter_by(phone=phone).first()
    if not user:
        return jsonify({'status': 'error', 'message': 'Foydalanuvchi topilmadi'}), 404

    # IP manzilni yangilash
    user.last_ip = user_ip

    # Bloklanganligini tekshirish
    if user.is_blocked:
        db.session.commit()
        return jsonify({'status': 'error', 'message': 'Hisobingiz bloklangan. Admin bilan bog\'laning'}), 403

    if user.check_pin(pin, bcrypt):
        # Muvaffaqiyatli bo'lsa urinishlarni nolga tushirish
        user.failed_attempts = 0
        db.session.commit()
        
        login_user(user)
        redirect_url = url_for('admin.dashboard') if user.role == 'admin' else url_for('user.dashboard')
        return jsonify({'status': 'success', 'redirect': redirect_url})
    else:
        # Xato bo'lsa urinishlarni oshirish
        user.failed_attempts += 1
        message = 'Noto\'g\'ri PIN kod'
        
        if user.failed_attempts >= 3:
            user.is_blocked = True
            message = 'Hisobingiz 3 marta xato terilgani uchun bloklandi'
        
        db.session.commit()
        return jsonify({'status': 'error', 'message': message})

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

# --- STIR (INN) Search Logic (orginfo.uz) ---
@auth_bp.route('/check_stir', methods=['POST'])
def check_stir():
    data = request.get_json()
    stir = data.get('stir', '').strip()
    
    if len(stir) != 9 or not stir.isdigit():
        return jsonify({'status': 'error', 'message': 'STIR 9 ta raqamdan iborat bo\'lishi shart'}), 400

    # Check if STIR already exists in our DB
    if User.query.filter_by(stir=stir).first():
        return jsonify({'status': 'error', 'message': "Ushbu STIR orqali allaqachon ro'yxatdan o'tilgan"}), 400

    try:
        # Search on orginfo.uz
        base_url = "https://orginfo.uz"
        search_url = f"{base_url}/ru/search/all/?q={stir}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        session_req = requests.Session()
        response = session_req.get(search_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'status': 'error', 'message': 'STIR ma\'lumotlarini olishda xatolik yuz berdi'}), 500

        # If not redirected to an organization page, find the first result
        final_url = response.url
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if "/organization/" not in final_url:
            # Look for the first organization link in search results
            org_link = soup.find('a', href=re.compile(r'/organization/'))
            if not org_link:
                if "Ничего не найдено" in response.text or "0 организаций" in response.text:
                    return jsonify({'status': 'error', 'message': 'Bunday STIR raqamli tashkilot topilmadi'}), 404
                return jsonify({'status': 'error', 'message': 'Qidiruv natijalarini o\'qib bo\'lmadi'}), 500
            
            # Fetch the actual organization page
            org_url = base_url + org_link['href']
            response = session_req.get(org_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

        # Extract Info from Organization Page
        org_name = ""
        director = ""
        ifut = ""
        email = ""
        org_phone = ""
        address = ""
        
        # Name is usually in h1
        h1 = soup.find('h1')
        if h1:
            org_name = h1.text.strip()
            # Clean common prefixes
            org_name = re.sub(r'^(Общество с ограниченной ответственностью|OOO|ЧП|OK|MCHJ)\s+', '', org_name, flags=re.IGNORECASE)
            org_name = org_name.replace('\"', '').strip()

        # --- NEW JSON-LD PARSING (MOST RELIABLE) ---
        ld_json_scripts = soup.find_all('script', type='application/ld+json')
        for script in ld_json_scripts:
            try:
                ld_data = json.loads(script.get_text())
                if ld_data.get('@type') == 'Organization':
                    # Extract name
                    if not org_name:
                        org_name = ld_data.get('name', '')
                    
                    # Extract email
                    if not email:
                        email = ld_data.get('email', '')
                    
                    # Extract phone
                    if not org_phone:
                        org_phone = ld_data.get('telephone', '')
                    
                    # Extract address
                    if not address:
                        addr_obj = ld_data.get('address', {})
                        if isinstance(addr_obj, dict):
                            loc = addr_obj.get('addressLocality', '')
                            street = addr_obj.get('streetAddress', '')
                            address = f"{loc}, {street}".strip(', ')
                        elif isinstance(addr_obj, str):
                            address = addr_obj

                    # Extract Director
                    if not director:
                        emp = ld_data.get('employee', {})
                        if isinstance(emp, dict):
                            director = emp.get('name', '')
                        elif isinstance(emp, list) and len(emp) > 0:
                            director = emp[0].get('name', '')
            except Exception:
                continue

        # --- FALLBACK TO HTML SCRAPING ---
        def find_grid_value(label_text):
            label_el = soup.find(string=re.compile(label_text, re.IGNORECASE))
            if label_el:
                parent_row = label_el.find_parent('div', class_='row')
                if parent_row:
                    cols = parent_row.find_all('div', class_=re.compile(r'col-'))
                    if len(cols) >= 2:
                        val = cols[-1].get_text(separator=' ', strip=True)
                        if 'почта' in label_text.lower():
                            mail_link = parent_row.find('a', href=re.compile(r'mailto:'))
                            if mail_link: val = mail_link['href'].replace('mailto:', '')
                        return val
            return ""

        if not director: director = find_grid_value(r'Руководитель')
        if not ifut:
            ifut_raw = find_grid_value(r'ОКЭД')
            if ifut_raw: ifut = "".join(filter(str.isdigit, ifut_raw.split('-')[0]))
        if not email: email = find_grid_value(r'Электронная почта')
        if not org_phone: org_phone = find_grid_value(r'Номер телефона')
        if not address: address = find_grid_value(r'Адрес')

        # Clean strings
        def clean(s):
            if not s: return ""
            junk = ['понятно', 'пароль', 'сумма услуги', '0 uzs', '[email\u00a0protected]']
            if any(j in s.lower() for j in junk): return ""
            # Clean common prefixes from org_name if it was updated
            cleaned = s.replace('\"', '').strip()
            return cleaned

        org_name = clean(org_name)
        director = clean(director)
        email = clean(email)
        org_phone = clean(org_phone)
        address = clean(address)

        if not org_name:
            return jsonify({'status': 'error', 'message': 'Tashkilot nomi topilmadi'}), 404

        return jsonify({
            'status': 'success',
            'org_name': org_name,
            'stir': stir,
            'director': director,
            'ifut': ifut,
            'email': email,
            'org_phone': org_phone,
            'address': address
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Xatolik: {str(e)}'}), 500

# --- Eskiz SMS API Integration ---
def get_eskiz_token():
    email = os.getenv('ESKIZ_EMAIL')
    password = os.getenv('ESKIZ_PASSWORD')
    
    try:
        res = requests.post('https://notify.eskiz.uz/api/auth/login', data={
            'email': email,
            'password': password
        })
        return res.json().get('data', {}).get('token')
    except:
        return None

@auth_bp.route('/send_sms', methods=['POST'])
def send_sms():
    data = request.get_json()
    phone = data.get('phone', '').strip().replace('+', '') # Eskiz expects digits only
    
    # Generate 6-digit code
    code = str(random.randint(100000, 999999))
    session['registration_code'] = code
    session['registration_phone'] = '+' + phone
    
    # Eskiz API Call
    token = get_eskiz_token()
    if not token:
        return jsonify({'status': 'error', 'message': 'SMS xizmatiga ulanib bo\'lmadi'}), 500
        
    message = f"IslomCRM web ilovasidan ro'yxatdan o'tish uchun tasdiqlash kodi : {code} IslomCRM.uz"
    
    try:
        res = requests.post('https://notify.eskiz.uz/api/message/sms/send', 
            headers={'Authorization': f'Bearer {token}'},
            data={
                'mobile_phone': phone,
                'message': message,
                'from': os.getenv('ESKIZ_ALPHA_NAME', '4546')
            }
        )
        return jsonify({'status': 'success', 'message': 'SMS yuborildi'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@auth_bp.route('/complete_registration', methods=['POST'])
def complete_registration():
    data = request.get_json()
    code = data.get('code', '').strip()
    
    if code != session.get('registration_code'):
        return jsonify({'status': 'error', 'message': 'Tasdiqlash kodi noto\'g\'ri'}), 400
        
    # Extract data from request (sent from hidden fields or cumulative state)
    phone = data.get('phone', '').strip()
    pin = data.get('pin', '').strip()
    stir = data.get('stir', '').strip()
    org_name = data.get('org_name', '').strip()
    director = data.get('director', '').strip()
    ifut = data.get('ifut', '').strip()
    email = data.get('email', '').strip()
    org_phone = data.get('org_phone', '').strip()
    address = data.get('address', '').strip()
    
    hashed_pin = bcrypt.generate_password_hash(pin).decode('utf-8')
    
    new_user = User(
        phone=phone,
        pin_hash=hashed_pin,
        stir=stir,
        org_name=org_name,
        director=director,
        ifut=ifut,
        email=email,
        org_phone=org_phone,
        address=address,
        is_verified=True
    )
    
    try:
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        # Clear session
        session.pop('registration_code', None)
        session.pop('registration_phone', None)
        return jsonify({'status': 'success', 'redirect': url_for('user.dashboard')})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Bazaga saqlashda xatolik: {str(e)}'}), 500

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
