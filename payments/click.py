from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction, Driver
from extensions import db
import hashlib
import logging
import datetime

click_bp = Blueprint('click', __name__)

def get_global_settings():
    return PaymentSettings.query.first()

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
        # Check if transaction exists if merchant_trans_id was provided
        if merchant_trans_id:
            trans = Transaction.query.get(merchant_trans_id)
            if not trans:
                return click_error(-5, "Transaction not found")
            if trans.status != 'pending':
                return click_error(-4, "Already paid or cancelled")
        
        return jsonify({
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_trans_id, # We use our trans ID as prepare ID too
            "error": 0,
            "error_note": "Success"
        })

    # Action 1: Complete
    elif action == '1':
        trans = Transaction.query.get(merchant_trans_id)
        if not trans:
            return click_error(-5, "Transaction not found")
        
        if trans.status == 'success':
            return click_error(-4, "Already paid")
            
        if params.get('error') == '0':
            # SUCCESS
            if trans.status != 'success':
                # Update balance only for org topup
                if trans.type == 'balance_topup':
                    owner = User.query.get(trans.user_id)
                    if owner:
                        owner.balance = (owner.balance or 0.0) + trans.amount
                        logging.info(f"Click: Balance UPDATED for user {owner.id}: {trans.amount}")
                else:
                    logging.info(f"Click: Driver payment SUCCESS: {trans.id}")

                trans.status = 'success'
                db.session.commit()
            
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
            return click_error(-9, "Transaction cancelled by user or Click")

    return click_error(-3, "Unknown action")
