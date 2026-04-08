from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import User, PaymentSettings, Transaction
from extensions import db
import base64
import logging
import os

# Use the same log file as payme callback
LOG_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'payme_debug.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s')

user_bp = Blueprint('user', __name__, template_folder='../templates')

@user_bp.route('/')
@login_required
def dashboard():
    return render_template('user/dashboard.html')

@user_bp.route('/finance')
@login_required
def finance():
    settings = PaymentSettings.query.first()
    min_amount = settings.min_topup_amount if settings else 1000
    max_amount = settings.max_topup_amount if settings else 10000000
    return render_template('user/finance.html', min_amount=min_amount, max_amount=max_amount)

@user_bp.route('/topup/payme', methods=['POST'])
@login_required
def topup_payme():
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        flash("Iltimos, to'g'ri summa kiriting", "danger")
        return redirect(url_for('user.finance'))

    amount = int(amount)
    settings = PaymentSettings.query.first()
    min_amount = settings.min_topup_amount if settings else 1000
    max_amount = settings.max_topup_amount if settings else 10000000

    if amount < min_amount:
        flash(f"Minimal to'ldirish summasi — {min_amount:,} so'm".replace(',', ' '), "danger")
        return redirect(url_for('user.finance'))

    if amount > max_amount:
        flash(f"Maksimal to'ldirish summasi — {max_amount:,} so'm".replace(',', ' '), "danger")
        return redirect(url_for('user.finance'))

    if not settings or not settings.payme_merchant_id or settings.payme_merchant_id == 'your_merchant_id':
        flash("To'lov tizimi hali sozlanmagan. Iltimos, adminga murojaat qiling.", "warning")
        return redirect(url_for('user.finance'))

    # Payme expects amount in tiyin (1 sum = 100 tiyin)
    amount_tiyin = amount * 100
    merchant_id = settings.payme_merchant_id
    phone_clean = current_user.phone.replace('+', '').replace(' ', '')
    # Use the account field name configured by admin (default: phone)
    account_field = getattr(settings, 'payme_account_field', None) or 'phone'
    params = f"m={merchant_id};ac.{account_field}={phone_clean};a={amount_tiyin};l=uz"
    
    logging.info(f"Generating Payme URL for user {current_user.phone}")
    logging.info(f"Raw params: {params}")
    
    encoded_params = base64.b64encode(params.encode()).decode()
    
    # Choose base URL based on test mode
    base_url = "https://test.payme.uz" if getattr(settings, 'is_test_mode', False) else "https://checkout.payme.uz"
    payme_url = f"{base_url}/b/{encoded_params}"

    # Create pending transaction
    new_trans = Transaction(
        user_id=current_user.id,
        amount=amount,
        type='topup',
        status='pending'
    )
    db.session.add(new_trans)
    db.session.commit()

@user_bp.route('/test-payme')
@login_required
def test_payme():
    settings = PaymentSettings.query.first()
    if not settings:
        return "No settings found"
        
    merchant_id = settings.payme_merchant_id
    phone = current_user.phone.replace('+', '').replace(' ', '')
    amount = (settings.min_topup_amount or 1000) * 100 # Default min amount in tiyin
    
    variants = []
    
    # Variant 1: phone + ;
    s1 = f"m={merchant_id};ac.phone={phone};a={amount};l=uz"
    variants.append({"name": "phone + semicolon", "url": f"https://test.payme.uz/b/{base64.b64encode(s1.encode()).decode()}"})
    
    # Variant 2: phone + &
    s2 = f"m={merchant_id}&ac.phone={phone}&a={amount}&l=uz"
    variants.append({"name": "phone + ampersand", "url": f"https://test.payme.uz/b/{base64.b64encode(s2.encode()).decode()}"})
    
    # Variant 3: phone_number + ;
    s3 = f"m={merchant_id};ac.phone_number={phone};a={amount};l=uz"
    variants.append({"name": "phone_number + semicolon", "url": f"https://test.payme.uz/b/{base64.b64encode(s3.encode()).decode()}"})
    
    # Variant 4: phone_number + &
    s4 = f"m={merchant_id}&ac.phone_number={phone}&a={amount}&l=uz"
    variants.append({"name": "phone_number + ampersand", "url": f"https://test.payme.uz/b/{base64.b64encode(s4.encode()).decode()}"})
    
    # Variant 5: phone + ; (no language)
    s5 = f"m={merchant_id};ac.phone={phone};a={amount}"
    variants.append({"name": "no language + semicolon", "url": f"https://test.payme.uz/b/{base64.b64encode(s5.encode()).decode()}"})

    return render_template('user/test_payme.html', variants=variants)
