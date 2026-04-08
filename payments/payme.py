from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction
from extensions import db
import base64
import datetime
import json
import os
import logging


# Set up logging for Payme debugging
LOG_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'payme_debug.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s')

payme_bp = Blueprint('payme', __name__)


def get_settings():
    return PaymentSettings.query.first()


def get_phone(account: dict) -> str:
    """Payme sends phone as 'phone' or 'phone_number' depending on merchant config."""
    return account.get('phone') or account.get('phone_number') or ''


def check_auth(auth_header, settings):
    """Payme Basic Auth: Authorization: Basic base64(Paycom:{key})"""
    if not auth_header or not auth_header.startswith('Basic '):
        return False
    if not settings:
        return False
        
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        parts = decoded.split(':', 1)
        if len(parts) != 2 or parts[0] != 'Paycom':
            return False
            
        provided_key = parts[1]
        
        # Check against both keys to allow simultaneous testing/production use
        is_test_match = settings.payme_test_key and provided_key == settings.payme_test_key
        is_prod_match = settings.payme_secret_key and provided_key == settings.payme_secret_key
        
        return is_test_match or is_prod_match
    except Exception as e:
        logging.error(f"Auth decoding error: {e}")
        return False


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
    return int(datetime.datetime.utcnow().timestamp() * 1000)


@payme_bp.route('/callback', methods=['POST'])
def payme_callback():
    raw_data = request.data.decode('utf-8')
    auth_header = request.headers.get('Authorization', '')
    
    # data = request.get_json(force=True, silent=True) # Already handled below

    data = request.get_json(force=True, silent=True)
    if data is None:
        logging.warning("Failed to parse JSON body")
        return auth_error(None)

    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id')

    settings = get_settings()

    # Auth check — always return HTTP 200
    if not check_auth(auth_header, settings):
        logging.warning(f"Auth check FAILED for method {method}")
        return auth_error(req_id)

    # logging.info(f"Auth check PASSED for method {method}")

    # ─── CheckPerformTransaction ───────────────────────────────────────
    if method == 'CheckPerformTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)  # tiyin

        if not phone:
            return payme_error(req_id, -31050, {"uz": "Telefon raqam kiritilmagan", "ru": "Введите номер телефона", "en": "Phone required"})

        # Normalize phone: strip leading '+'
        phone_clean = phone.lstrip('+')
        user = User.query.filter(
            (User.phone == f'+{phone_clean}') | (User.phone == phone)
        ).first()

        if not user:
            return payme_error(req_id, -31050, {"uz": "Foydalanuvchi topilmadi", "ru": "Пользователь не найден", "en": "User not found"})

        min_t = (settings.min_topup_amount or 1000) * 100
        max_t = (settings.max_topup_amount or 10000000) * 100
        if amount < min_t or amount > max_t:
            return payme_error(req_id, -31001, {"uz": "Noto'g'ri summa", "ru": "Неверная сумма", "en": "Invalid amount"})

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
        user = User.query.filter(
            (User.phone == f'+{phone_clean}') | (User.phone == phone)
        ).first()

        if not user:
            return payme_error(req_id, -31050, {"uz": "Foydalanuvchi topilmadi", "en": "User not found"})

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
            user_id=user.id,
            amount=amount / 100,
            type='topup',
            status='pending',
            payme_trans_id=payme_id
        )
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
            user = User.query.get(trans.user_id)
            user.balance = (user.balance or 0.0) + trans.amount
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
