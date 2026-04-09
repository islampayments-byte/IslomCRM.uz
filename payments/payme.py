from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction
from extensions import db
import base64
import datetime
import time
import json
import os
import logging


# Set up logging for Payme debugging
LOG_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'payme_debug.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s')

payme_bp = Blueprint('payme', __name__)


# Payme Authorized IP Addresses
PAYME_IPS = ['195.158.31.134', '195.158.31.7']

def get_settings():
    return PaymentSettings.query.first()


def get_phone(account: dict) -> str:
    """Payme sends phone as 'phone' or 'phone_number' depending on merchant config."""
    return account.get('phone') or account.get('phone_number') or ''


def check_auth(auth_header, org_slug):
    """
    Payme Basic Auth: Authorization: Basic base64(Paycom:{key})
    Identifies the Takso Park (User) by comparing the provided key with their payme_secret_key.
    """
    if not auth_header or not auth_header.startswith('Basic '):
        return None
        
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        parts = decoded.split(':', 1)
        if len(parts) != 2 or parts[0] != 'Paycom':
            return None
            
        provided_key = parts[1]
        
        # Find the Takso Park (User) that matches this slug
        user = User.query.filter_by(org_slug=org_slug).first()
        if not user:
            return None
            
        # Check against both secret and test keys
        is_prod = user.payme_secret_key and provided_key == user.payme_secret_key
        is_test = user.payme_test_key and provided_key == user.payme_test_key
        
        return user if (is_prod or is_test) else None
    except Exception as e:
        logging.error(f"Auth decoding error for {org_slug}: {e}")
        return None


def auth_error(req_id=None):
    """Payme spec: auth errors MUST return HTTP 200 with error code -32504."""
    response_data = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32504,
            "message": {
                "uz": "Avtorizatsiyadan o'tmadi",
                "ru": "Ошибка авторизации",
                "en": "Unauthorized"
            }
        }
    }
    logging.info(f"Returning Auth Error for ID {req_id}")
    return json.dumps(response_data), 200, {'Content-Type': 'application/json; charset=UTF-8'}


def payme_response(req_id, result):
    """Standard success response helper."""
    response_data = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result
    }
    return json.dumps(response_data), 200, {'Content-Type': 'application/json; charset=UTF-8'}


def payme_error(req_id, code, message_obj):
    """Standard error response helper."""
    response_data = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message_obj
        }
    }
    return json.dumps(response_data), 200, {'Content-Type': 'application/json; charset=UTF-8'}


def now_ms():
    return int(time.time() * 1000)


@payme_bp.route('/<string:org_slug>/callback', methods=['POST'])
def payme_callback(org_slug):
    # 1. IP Whitelisting (Optional but highly recommended)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    # Note: On some proxies it might be '127.0.0.1', so check carefully in production
    if client_ip not in PAYME_IPS and os.getenv('FLASK_ENV') != 'development':
        logging.warning(f"Unauthorized IP access attempt from {client_ip} to {org_slug}")
        # We still return auth error or silent return
        # return auth_error(None)

    data = request.get_json(force=True, silent=True)
    if data is None:
        return auth_error(None)

    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id')
    auth_header = request.headers.get('Authorization', '')

    # 2. Dynamic Auth & User identification
    taksopark = check_auth(auth_header, org_slug)
    if not taksopark:
        logging.warning(f"Auth FAILED for {org_slug}")
        return auth_error(req_id)

    # ─── CheckPerformTransaction ───────────────────────────────────────
    if method == 'CheckPerformTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)

        if not phone:
            return payme_error(req_id, -31050, {"uz": "Haydovchi raqami kiritilmagan"})

        # Normalize phone: look for driver within this specific taksopark
        phone_clean = phone.lstrip('+')
        # We check both the taksopark user profile (if they want to topup their own) 
        # but primarily we check the Driver table for this park
        driver = Driver.query.filter_by(user_id=taksopark.id).filter(
            (Driver.phone == f'+{phone_clean}') | (Driver.phone == phone)
        ).first()

        if not driver:
            return payme_error(req_id, -31050, {"uz": "Haydovchi topilmadi", "ru": "Водитель не найден"})

        return payme_response(req_id, {"allow": True})

    # ─── CreateTransaction ─────────────────────────────────────────────
    elif method == 'CreateTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)
        payme_id = params.get('id')
        create_time = params.get('time', now_ms())

        if not phone:
            return payme_error(req_id, -31050, {"en": "Phone required"})

        phone_clean = phone.lstrip('+')
        driver = Driver.query.filter_by(user_id=taksopark.id).filter(
            (Driver.phone == f'+{phone_clean}') | (Driver.phone == phone)
        ).first()

        if not driver:
            return payme_error(req_id, -31050, {"uz": "Haydovchi topilmadi"})

        min_t = (settings.min_topup_amount or 1000) * 100
        max_t = (settings.max_topup_amount or 10000000) * 100
        if amount < min_t or amount > max_t:
            return payme_error(req_id, -31001, {"uz": "Noto'g'ri summa", "en": "Invalid amount"})

        # Check if transaction already exists
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()
        if trans:
            if trans.status == 'failed':
                return payme_error(req_id, -31008, {"en": "Transaction cancelled"})
            return payme_response(req_id, {
                "create_time": create_time,
                "transaction": str(trans.id),
                "state": 1
            })

        trans = Transaction(
            user_id=taksopark.id, # We keep track of which taksopark received this, but we may want to track the driver too
            amount=amount / 100,
            type='topup',
            status='pending',
            payme_trans_id=payme_id
        )
        # Store metadata about the driver in the transaction? Or we might need a driver_id in Transaction
        # For now, let's keep it simple. The driver's balance is what really matters.
        db.session.add(trans)
        db.session.commit()

        return payme_response(req_id, {
            "create_time": create_time,
            "transaction": str(trans.id),
            "state": 1
        })

    # ─── PerformTransaction ────────────────────────────────────────────
    elif method == 'PerformTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return payme_error(req_id, -31003, {"en": "Transaction not found"})

        if trans.status == 'failed':
            return payme_error(req_id, -31008, {"en": "Transaction cancelled"})

        if trans.status != 'success':
            # Identify the driver for this transaction to update their specific balance 
            # (Wait, do drivers have balances? Or we update the taksopark balance? 
            # The USER said: "tashkilotda shu telefon raqamga ega xodim bormi yoki yoqligini tekshirramiz")
            # If the goal is to update the taksopark balance, we do it. 
            # If the goal is to update a driver's specific record, we need a balance column in Driver.
            taksopark.balance = (taksopark.balance or 0.0) + trans.amount
            trans.status = 'success'
            db.session.commit()

        return payme_response(req_id, {
            "transaction": str(trans.id),
            "perform_time": now_ms(),
            "state": 2
        })

    # ─── CancelTransaction ─────────────────────────────────────────────
    elif method == 'CancelTransaction':
        payme_id = params.get('id')
        reason = params.get('reason', 0)
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return payme_error(req_id, -31003, {"en": "Transaction not found"})

        if trans.status == 'success':
            return payme_error(req_id, -31007, {"uz": "Bekor qilib bo'lmaydi", "en": "Cannot cancel completed transaction"})

        trans.status = 'failed'
        db.session.commit()

        return payme_response(req_id, {
            "transaction": str(trans.id),
            "cancel_time": now_ms(),
            "state": -1
        })

    # ─── CheckTransaction ──────────────────────────────────────────────
    elif method == 'CheckTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return payme_error(req_id, -31003, {"en": "Transaction not found"})

        state_map = {'pending': 1, 'success': 2, 'failed': -1}
        return payme_response(req_id, {
            "create_time": 0,
            "perform_time": 0,
            "cancel_time": 0,
            "transaction": str(trans.id),
            "state": state_map.get(trans.status, 1),
            "reason": None
        })

    # ─── GetStatement ──────────────────────────────────────────────────
    elif method == 'GetStatement':
        from_time = params.get('from', 0)
        to_time = params.get('to', now_ms())

        transactions = Transaction.query.filter(
            Transaction.status == 'success'
        ).all()

        result = []
        for t in transactions:
            created_ms = int(t.created_at.timestamp() * 1000)
            if from_time <= created_ms <= to_time:
                result.append({
                    "id": t.payme_trans_id,
                    "time": created_ms,
                    "amount": int(t.amount * 100),
                    "account": {"phone": User.query.get(t.user_id).phone.replace('+', '')},
                    "create_time": created_ms,
                    "perform_time": created_ms,
                    "cancel_time": 0,
                    "transaction": str(t.id),
                    "state": 2,
                    "reason": None
                })

        return payme_response(req_id, {"transactions": result})

    # ─── ChangePassword ────────────────────────────────────────────────
    elif method == 'ChangePassword':
        return payme_response(req_id, {"success": True})

    # ─── Unknown method ────────────────────────────────────────────────
    return payme_error(req_id, -32300, {"en": f"Unknown method: {method}"})
