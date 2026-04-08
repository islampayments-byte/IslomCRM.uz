from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import User, PaymentSettings, Transaction
from extensions import db
import requests
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

@user_bp.route('/info')
@login_required
def info():
    return render_template('user/info.html')

@user_bp.route('/profile')
@login_required
def profile():
    return render_template('user/profile.html')

@user_bp.route('/finance')
@login_required
def finance():
    settings = PaymentSettings.query.first()
    min_amount = settings.min_topup_amount if settings else 1000
    max_amount = settings.max_topup_amount if settings else 10000000
    
    # Fetch user's transactions (most recent first)
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.id.desc()).all()
    
    return render_template('user/finance.html', 
                          min_amount=min_amount, 
                          max_amount=max_amount,
                          transactions=transactions)

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

    if not settings or not settings.payme_merchant_id or not settings.payme_secret_key:
        flash("To'lov tizimi hali sozlanmagan. Iltimos, adminga murojaat qiling.", "warning")
        return redirect(url_for('user.finance'))

    # Payme expects amount in tiyin (1 sum = 100 tiyin)
    amount_tiyin = amount * 100
    merchant_id = settings.payme_merchant_id
    secret_key = settings.payme_secret_key
    phone_clean = current_user.phone.replace('+', '').replace(' ', '')
    account_field = getattr(settings, 'payme_account_field', None) or 'phone_number'
    
    # Check if in test mode
    is_test = getattr(settings, 'is_test_mode', False)
    api_url = "https://checkout.test.paycom.uz/api" if is_test else "https://checkout.paycom.uz/api"
    checkout_url = "https://checkout.test.paycom.uz" if is_test else "https://checkout.payme.uz"

    # 1. Create a receipt via Payme API
    headers = {
        "X-Auth": f"{merchant_id}:{secret_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "jsonrpc": "2.0",
        "method": "receipts.create",
        "params": {
            "amount": amount_tiyin,
            "account": {
                account_field: phone_clean
            }
        },
        "id": int(os.urandom(4).hex(), 16) # Unique request ID
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        
        if "error" in res_data:
            logging.error(f"Payme API Error: {res_data['error']}")
            flash(f"To'lov tizimida xatolik yuz berdi: {res_data['error'].get('message', 'Noma''lum xato')}", "danger")
            return redirect(url_for('user.finance'))
            
        receipt_id = res_data["result"]["receipt"]["_id"]
        
        # 2. Construct redirect URL
        payme_redirect_url = f"https://payme.uz/checkout/{receipt_id}"

        # Create pending transaction locally
        new_trans = Transaction(
            user_id=current_user.id,
            amount=amount,
            type='topup',
            status='pending',
            payme_trans_id=receipt_id 
        )
        db.session.add(new_trans)
        db.session.commit()

        return redirect(payme_redirect_url)

    except Exception as e:
        error_msg = str(e)
        logging.error(f"Exception during Payme receipt creation: {error_msg}")
        flash(f"To'lov serveri bilan bog'lanishda xatolik: {error_msg}", "danger")
        return redirect(url_for('user.finance'))

@user_bp.route('/transaction/cancel/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    trans = Transaction.query.filter_by(id=transaction_id, user_id=current_user.id).first()
    
    if not trans:
        flash("Tranzaksiya topilmadi.", "danger")
        return redirect(url_for('user.finance'))
        
    if trans.status != 'pending':
        flash("Ushbu tranzaksiyani bekor qilib bo'lmaydi.", "warning")
        return redirect(url_for('user.finance'))
        
    trans.status = 'failed'
    db.session.commit()
    
    flash(f"#{transaction_id} raqamli to'lov bekor qilindi.", "info")
    return redirect(url_for('user.finance'))
