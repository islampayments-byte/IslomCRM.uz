from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction, Driver
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

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_global_settings():
    return PaymentSettings.query.first()


def get_phone(account: dict) -> str:
    return account.get('phone') or account.get('phone_number') or ''


def find_user_by_phone(phone_raw, user_id=None):
    """
    Find a User or Driver by phone number.
    Tries multiple formats: +998XXXXXXXXX, 998XXXXXXXXX, XXXXXXXXX
    If user_id given, searches Driver table for that taksopark.
    Otherwise searches User table.
    """
    phone = phone_raw.strip()
    # Build list of variants to try
    digits = phone.lstrip('+')
    variants = [
        f'+{digits}',         # +998991476534
        digits,               # 998991476534
    ]
    # If only 9 digits (local format), add UZ prefix
    if len(digits) == 9:
        variants.append(f'+998{digits}')
        variants.append(f'998{digits}')

    if user_id is not None:
        for v in variants:
            obj = Driver.query.filter_by(user_id=user_id).filter(
                (Driver.phone == v) | (Driver.phone == v.replace('+', ''))
            ).first()
            if obj:
                return obj
    else:
        for v in variants:
            obj = User.query.filter(
                (User.phone == v) | (User.phone == v.replace('+', ''))
            ).first()
            if obj:
                return obj
    return None


def auth_error(req_id=None):
    """Payme spec: auth errors MUST return HTTP 200 with error code -32504."""
    return _json_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32504,
            "message": {"uz": "Avtorizatsiyadan o'tmadi", "ru": "Ошибка авторизации", "en": "Unauthorized"}
        }
    })


def payme_response(req_id, result):
    return _json_response({"jsonrpc": "2.0", "id": req_id, "result": result})


def payme_error(req_id, code, message_obj):
    return _json_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message_obj}})


def _json_response(data):
    return json.dumps(data), 200, {'Content-Type': 'application/json; charset=UTF-8'}


def now_ms():
    return int(time.time() * 1000)


def decode_key(auth_header):
    """Decode Payme Basic auth header and return the provided key, or None."""
    if not auth_header or not auth_header.startswith('Basic '):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        parts = decoded.split(':', 1)
        if len(parts) != 2 or parts[0] != 'Paycom':
            return None
        return parts[1]
    except Exception:
        return None


def check_global_auth(auth_header):
    """Check against global PaymentSettings keys. Returns True/False."""
    key = decode_key(auth_header)
    if not key:
        return False
    settings = get_global_settings()
    if not settings:
        return False
    return (settings.payme_secret_key and key == settings.payme_secret_key) or \
           (settings.payme_test_key and key == settings.payme_test_key)


def check_taksopark_auth(auth_header, org_slug):
    """Check against a specific Taksopark's keys. Returns user or None."""
    key = decode_key(auth_header)
    if not key:
        return None
    user = User.query.filter_by(org_slug=org_slug).first()
    if not user:
        return None
    is_prod = user.payme_secret_key and key == user.payme_secret_key
    is_test = user.payme_test_key and key == user.payme_test_key
    return user if (is_prod or is_test) else None


# ─── Global Platform Callback (IslomCRM's own Payme account) ──────────────────
# URL in Payme cabinet: https://islomcrm.uz/payments/payme/callback

@payme_bp.route('/payme/callback', methods=['POST'])
def global_payme_callback():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return auth_error(None)

    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id')
    auth_header = request.headers.get('Authorization', '')

    logging.info(f"[GLOBAL] Method: {method}")

    # Auth check using global PaymentSettings
    if not check_global_auth(auth_header):
        logging.warning(f"[GLOBAL] Auth FAILED for method {method}")
        return auth_error(req_id)

    settings = get_global_settings()

    return _handle_payme_methods(method, params, req_id, settings=settings, user_context=None)


# ─── Per-Taksopark Callback ────────────────────────────────────────────────────
# URL pattern: https://islomcrm.uz/payments/<org_slug>/payme/callback

@payme_bp.route('/<string:org_slug>/payme/callback', methods=['POST'])
def taksopark_payme_callback(org_slug):
    data = request.get_json(force=True, silent=True)
    if data is None:
        return auth_error(None)

    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id')
    auth_header = request.headers.get('Authorization', '')

    logging.info(f"[ORG:{org_slug}] Method: {method}")

    # Auth: first try taksopark keys, then fall back to global keys
    taksopark = check_taksopark_auth(auth_header, org_slug)
    if not taksopark:
        # Fallback: allow global key to access any org (admin access)
        if not check_global_auth(auth_header):
            logging.warning(f"[ORG:{org_slug}] Auth FAILED")
            return auth_error(req_id)
        # Find user by org_slug for context
        taksopark = User.query.filter_by(org_slug=org_slug).first()

    settings = get_global_settings()

    return _handle_payme_methods(method, params, req_id, settings=settings, user_context=taksopark)


# ─── Core Logic ───────────────────────────────────────────────────────────────

def _handle_payme_methods(method, params, req_id, settings, user_context):
    """
    Handles all Payme JSON-RPC methods.
    user_context: A User (Taksopark) object for driver-scoped lookups, or None for global.
    settings: Global PaymentSettings for amount limits.
    """

    # ─── CheckPerformTransaction ───────────────────────────────────────
    if method == 'CheckPerformTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)

        if not phone:
            return payme_error(req_id, -31050, {"uz": "Telefon raqam kiritilmagan", "ru": "Телефон не указан"})

        found = find_user_by_phone(phone, user_id=user_context.id if user_context else None)

        if not found:
            logging.warning(f"Phone not found: '{phone}' | user_context: {user_context.id if user_context else 'global'}")
            return payme_error(req_id, -31050, {"uz": "Foydalanuvchi topilmadi", "ru": "Пользователь не найден"})

        min_t = (settings.min_topup_amount if settings else 1000) * 100
        max_t = (settings.max_topup_amount if settings else 10000000) * 100
        if amount < min_t or amount > max_t:
            return payme_error(req_id, -31001, {"uz": "Noto'g'ri summa", "ru": "Неверная сумма"})

        return payme_response(req_id, {"allow": True})

    # ─── CreateTransaction ─────────────────────────────────────────────
    elif method == 'CreateTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)
        payme_id = params.get('id')
        create_time = params.get('time', now_ms())

        if not phone:
            return payme_error(req_id, -31050, {"uz": "Telefon kiritilmagan"})

        target = find_user_by_phone(phone, user_id=user_context.id if user_context else None)

        if not target:
            logging.warning(f"CreateTransaction: Phone not found: '{phone}'")
            return payme_error(req_id, -31050, {"uz": "Foydalanuvchi topilmadi"})

        min_t = (settings.min_topup_amount if settings else 1000) * 100
        max_t = (settings.max_topup_amount if settings else 10000000) * 100
        if amount < min_t or amount > max_t:
            return payme_error(req_id, -31001, {"uz": "Noto'g'ri summa"})

        # Deduplicate
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()
        if trans:
            if trans.status == 'failed':
                return payme_error(req_id, -31008, {"uz": "Tranzaksiya bekor qilingan"})
            return payme_response(req_id, {
                "create_time": create_time,
                "transaction": str(trans.id),
                "state": 1
            })

        owner_id = user_context.id if user_context else (target.id if hasattr(target, 'user_id') is False else target.user_id)
        # user_context mavjud = per-org callback = haydovchi to'lovi
        # user_context None  = global callback   = user o'z balansi
        trans_type = 'driver_payment' if user_context else 'balance_topup'
        trans = Transaction(
            user_id=owner_id,
            amount=amount / 100,
            type=trans_type,
            status='pending',
            payme_trans_id=payme_id,
            payer_phone=phone  # Saqlaymiz: kim to'ladi
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
            return payme_error(req_id, -31003, {"uz": "Tranzaksiya topilmadi"})

        if trans.status == 'failed':
            return payme_error(req_id, -31008, {"uz": "Tranzaksiya bekor qilingan"})

        if trans.status != 'success':
            # FAQAT balance_topup (user uz balansini tuldirganda) balans oshadi
            # driver_payment (haydovchi tulovi) bo'lsa, platforma balansi o'zgarmaydi
            if trans.type == 'balance_topup':
                owner = User.query.get(trans.user_id)
                if owner:
                    owner.balance = (owner.balance or 0.0) + trans.amount
                    logging.info(f"Balance UPDATED for user {owner.id}: +{trans.amount}")
            else:
                logging.info(f"Driver payment SUCCESS (no balance update for org): {trans.payme_trans_id}")

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
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return payme_error(req_id, -31003, {"uz": "Tranzaksiya topilmadi"})

        if trans.status == 'success':
            return payme_error(req_id, -31007, {"uz": "Yakunlangan tranzaksiyani bekor qilib bo'lmaydi"})

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
            return payme_error(req_id, -31003, {"uz": "Tranzaksiya topilmadi"})

        state_map = {'pending': 1, 'success': 2, 'failed': -1}
        created_ms = int(trans.created_at.timestamp() * 1000) if trans.created_at else 0

        return payme_response(req_id, {
            "create_time": created_ms,
            "perform_time": created_ms if trans.status == 'success' else 0,
            "cancel_time": created_ms if trans.status == 'failed' else 0,
            "transaction": str(trans.id),
            "state": state_map.get(trans.status, 1),
            "reason": None
        })

    # ─── GetStatement ──────────────────────────────────────────────────
    elif method == 'GetStatement':
        from_time = params.get('from', 0)
        to_time = params.get('to', now_ms())

        query = Transaction.query.filter(Transaction.status == 'success')
        if user_context:
            query = query.filter_by(user_id=user_context.id)

        transactions = query.all()
        result = []
        for t in transactions:
            if not t.created_at:
                continue
            created_ms = int(t.created_at.timestamp() * 1000)
            if from_time <= created_ms <= to_time:
                owner = User.query.get(t.user_id)
                phone = owner.phone.replace('+', '') if owner else ''
                result.append({
                    "id": t.payme_trans_id,
                    "time": created_ms,
                    "amount": int(t.amount * 100),
                    "account": {"phone": phone},
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
