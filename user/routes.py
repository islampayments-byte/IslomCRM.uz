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

    if not settings or not settings.payme_merchant_id:
        flash("To'lov tizimi hali sozlanmagan. Iltimos, adminga murojaat qiling.", "warning")
        return redirect(url_for('user.finance'))

    # Payme expects amount in tiyin (1 sum = 100 tiyin)
    amount_tiyin = amount * 100
    merchant_id = settings.payme_merchant_id
    phone_clean = current_user.phone.replace('+', '')
    # Use the account field name configured by admin (default: phone)
    account_field = getattr(settings, 'payme_account_field', None) or 'phone'
    params = f"m={merchant_id};ac.{account_field}={phone_clean};a={amount_tiyin};l=uz"
    encoded_params = base64.b64encode(params.encode()).decode()
    payme_url = f"https://checkout.payme.uz/b/{encoded_params}"

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
