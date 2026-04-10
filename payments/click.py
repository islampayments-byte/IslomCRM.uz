from flask import Blueprint, request, jsonify, current_app
from models import User, PaymentSettings, Transaction, Driver
from extensions import db
import hashlib
import logging
import datetime
import threading

click_bp = Blueprint('click', __name__)

def get_global_settings():
    return PaymentSettings.query.first()

def find_user_by_phone(phone_raw, user_id=None):
    """
    Find a User or Driver by phone number.
    Identical logic to payme.py for consistency.
    """
    phone = str(phone_raw).strip()
    digits = phone.lstrip('+').strip()
    if len(digits) == 9:
        digits = f"998{digits}"
    variants = [f"+{digits}", digits]

    if user_id is not None:
        for v in variants:
            obj = Driver.query.filter_by(user_id=user_id).filter(
                (Driver.phone == v) | (Driver.phone == v.replace('+', ''))
            ).first()
            if obj: return obj
    else:
        for v in variants:
            obj = User.query.filter(
                (User.phone == v) | (User.phone == v.replace('+', ''))
            ).first()
            if obj: return obj
    return None

def click_error(error_code, error_note):
    return jsonify({
        "error": error_code,
        "error_note": error_note
    })

def verify_signature(params, secret_key):
    """
    Verify Click signature.
    Formula: md5(click_trans_id + service_id + secret_key + merchant_trans_id + [merchant_prepare_id] + amount + action + sign_time)
    """
    click_trans_id = params.get('click_trans_id')
    service_id = params.get('service_id')
    merchant_trans_id = params.get('merchant_trans_id')
    merchant_prepare_id = params.get('merchant_prepare_id', '')
    amount = params.get('amount')
    action = params.get('action')
    sign_time = params.get('sign_time')
    
    # Base string
    s = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}"
    if action == '1': # Complete
        s += f"{merchant_prepare_id}"
    s += f"{amount}{action}{sign_time}"
    
    expected_sign = hashlib.md5(s.encode('utf-8')).hexdigest()
    return params.get('sign_string') == expected_sign

# ─── Callbacks ──────────────────────────────────────────────────────────────

@click_bp.route('/click/callback', methods=['POST'])
def global_click_callback():
    """Global callback for platform balance topup."""
    return _handle_click_request(org_slug=None)

@click_bp.route('/<org_slug>/click/callback', methods=['POST'])
def taksopark_click_callback(org_slug):
    """Per-org callback for driver payments."""
    return _handle_click_request(org_slug=org_slug)

def _handle_click_request(org_slug):
    params = request.form.to_dict()
    if not params: # Handle JSON if POSTed as JSON
        params = request.json or {}
        
    action = params.get('action')
    click_trans_id = params.get('click_trans_id')
    merchant_trans_id = params.get('merchant_trans_id') # This is our Transaction.id
    
    logging.info(f"Click Callback | Action: {action} | Trans: {merchant_trans_id} | Org: {org_slug}")

    # 1. Determine Secret Key for Auth
    global_settings = get_global_settings()
    secret_key = None
    user_context = None
    
    if org_slug:
        user_context = User.query.filter_by(org_slug=org_slug).first()
        if user_context and user_context.click_secret_key:
            secret_key = user_context.click_secret_key
    
    if not secret_key: # Fallback to global
        secret_key = global_settings.click_secret_key if global_settings else None

    if not secret_key:
        return click_error(-1, "Click configuration missing")

    # 2. Verify Signature
    if not verify_signature(params, secret_key):
        return click_error(-1, "Signature mismatch")

    # 3. Handle Actions
    # Action 0: Prepare
    if action == '0':
        # Check if transaction exists OR if merchant_trans_id is a phone number
        trans = Transaction.query.get(merchant_trans_id)
        if not trans:
            # Maybe it's a phone number (direct payment from Click app)
            target = find_user_by_phone(merchant_trans_id, user_id=user_context.id if user_context else None)
            if not target:
                logging.warning(f"Click Prepare: Subscriber not found: {merchant_trans_id}")
                return click_error(-5, "Subscriber not found")
        else:
            if trans.status != 'pending':
                return click_error(-4, "Already paid or cancelled")
        
        return jsonify({
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_trans_id,
            "error": 0,
            "error_note": "Success"
        })

    # Action 1: Complete
    elif action == '1':
        trans = Transaction.query.get(merchant_trans_id)
        
        # If no transaction exists (direct payment), create one on the fly
        if not trans:
            target = find_user_by_phone(merchant_trans_id, user_id=user_context.id if user_context else None)
            if not target:
                return click_error(-5, "Subscriber not found")
            
            # SUCCESS case for direct payment
            if params.get('error') == '0':
                owner_id = user_context.id if user_context else (target.id if hasattr(target, 'user_id') is False else target.user_id)
                trans_type = 'driver_payment' if user_context else 'balance_topup'
                new_trans = Transaction(
                    user_id=owner_id,
                    amount=float(params.get('amount', 0)),
                    type=trans_type,
                    status='success',
                    click_trans_id=click_trans_id,
                    payer_phone=merchant_trans_id,
                    # Yandex'ga yuborishni kutamiz (driver_payment)
                    yandex_sync_status='pending' if trans_type == 'driver_payment' else 'not_applicable'
                )
                
                # Platforma balansi faqat balance_topup uchun oshadi
                if new_trans.type == 'balance_topup':
                    owner = User.query.get(new_trans.user_id)
                    if owner:
                        owner.balance = (owner.balance or 0.0) + new_trans.amount
                        logging.info(f"Click Direct: Balance UPDATED for user {owner.id}: {new_trans.amount}")
                
                db.session.add(new_trans)
                db.session.commit()

                # Yandex Fleet'ga balans yuborish (agar haydovchi to'lovi bo'lsa)
                if new_trans.type == 'driver_payment' and user_context and user_context.yandex_keys_active:
                    from services import yandex_topup_driver
                    app = current_app._get_current_object()
                    t = threading.Thread(
                        target=yandex_topup_driver,
                        args=(app, user_context, new_trans.id),
                        daemon=True
                    )
                    t.start()
                    logging.info(f"[Click Direct] Yandex topup thread boshlandi: trans #{new_trans.id}")
                
                return jsonify({
                    "click_trans_id": click_trans_id,
                    "merchant_trans_id": merchant_trans_id,
                    "merchant_confirm_id": new_trans.id,
                    "error": 0,
                    "error_note": "Success"
                })
            else:
                return click_error(-9, "Transaction failed")

        # Existing Transaction (from redirect)
        if trans.status == 'success':
            return click_error(-4, "Already paid")
            
        if params.get('error') == '0':
            # SUCCESS
            if trans.status != 'success':
                if trans.type == 'balance_topup':
                    owner = User.query.get(trans.user_id)
                    if owner:
                        owner.balance = (owner.balance or 0.0) + trans.amount
                        logging.info(f"Click: Balance UPDATED for user {owner.id}: {trans.amount}")

                trans.status = 'success'
                # Yandex Fleet'ga balans yuborish (agar haydovchi to'lovi bo'lsa)
                if trans.type == 'driver_payment':
                    trans.yandex_sync_status = 'pending'
                db.session.commit()

                if trans.type == 'driver_payment':
                    owner_user = User.query.get(trans.user_id)
                    if owner_user and owner_user.yandex_keys_active:
                        from services import yandex_topup_driver
                        app = current_app._get_current_object()
                        t = threading.Thread(
                            target=yandex_topup_driver,
                            args=(app, owner_user, trans.id),
                            daemon=True
                        )
                        t.start()
                        logging.info(f"[Click] Yandex topup thread boshlandi: trans #{trans.id}")
                    else:
                        logging.info(f"[Click] Driver payment, lekin Yandex aktiv emas. Trans #{trans.id}")
            
            return jsonify({
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": merchant_trans_id,
                "error": 0,
                "error_note": "Success"
            })
        else:
            # FAILED
            trans.status = 'failed'
            db.session.commit()
            return click_error(-9, "Transaction cancelled")

    return click_error(-3, "Unknown action")
