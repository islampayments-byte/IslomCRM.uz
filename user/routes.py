from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import User, PaymentSettings, Transaction
from extensions import db
import base64

user_bp = Blueprint('user', __name__, template_folder='../templates')

@user_bp.route('/')
@login_required
def dashboard():
    return render_template('user/dashboard.html')

@user_bp.route('/finance')
@login_required
def finance():
    return render_template('user/finance.html')

@user_bp.route('/topup/payme', methods=['POST'])
@login_required
def topup_payme():
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        flash("Iltimos, to'g'ri summa kiriting", "danger")
        return redirect(url_for('user.finance'))
    
    amount = int(amount)
    if amount < 1000:
        flash("Minimal summa - 1000 so'm", "danger")
        return redirect(url_for('user.finance'))

    settings = PaymentSettings.query.first()
    if not settings or not settings.payme_merchant_id:
        flash("To'lov tizimi hali sozlanmagan. Iltimos, adminga murojaat qiling.", "warning")
        return redirect(url_for('user.finance'))

    # Payme expects amount in tiyin (1 sum = 100 tiyin)
    amount_tiyin = amount * 100
    merchant_id = settings.payme_merchant_id
    
    # Structure for Payme: m={merchant_id};ac.phone={phone};a={amount_tiyin}
    # Using phone number without '+' for Payme identification
    phone_clean = current_user.phone.replace('+', '')
    params = f"m={merchant_id};ac.phone={phone_clean};a={amount_tiyin}"
    encoded_params = base64.b64encode(params.encode()).decode()
    
    payme_url = f"https://checkout.payme.uz/{encoded_params}"
    
    # Create pending transaction
    new_trans = Transaction(
        user_id=current_user.id,
        amount=amount,
        type='topup',
        status='pending'
    )
    db.session.add(new_trans)
    db.session.commit()
    
    return redirect(payme_url)
