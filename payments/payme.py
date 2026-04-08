from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction
from extensions import db
import base64
import datetime

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
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        # decoded should be: "Paycom:{secret_key}" or "Paycom:{test_key}"
        parts = decoded.split(':', 1)
        if len(parts) != 2 or parts[0] != 'Paycom':
            return False
        provided_key = parts[1]
        if settings and settings.is_test_mode and settings.payme_test_key:
            return provided_key == settings.payme_test_key
        elif settings and settings.payme_secret_key:
            return provided_key == settings.payme_secret_key
        return False
    except Exception:
        return False


def auth_error(req_id=None):
    """Payme spec: auth errors MUST return HTTP 200 with error code -32504."""
    return jsonify({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32504,
            "message": "Authorization failed"
        }
    }), 200  # <-- must be 200 per Payme spec


def now_ms():
    return int(datetime.datetime.utcnow().timestamp() * 1000)


@payme_bp.route('/callback', methods=['POST'])
def payme_callback():
    data = request.get_json(force=True, silent=True)
    if data is None:
        # Invalid JSON or wrong content type handled by returning auth error or parse error
        # But we need req_id for the response, which we don't have.
        return auth_error(None)

    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id')

    settings = get_settings()

    # Auth check — always return HTTP 200
    if not check_auth(request.headers.get('Authorization', ''), settings):
        return auth_error(req_id)

    # ─── CheckPerformTransaction ───────────────────────────────────────
    if method == 'CheckPerformTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)  # tiyin

        if not phone:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {
                    "code": -31050,
                    "message": {"uz": "Telefon raqam kiritilmagan", "ru": "Введите номер телефона", "en": "Phone required"}
                }
            }), 200

        # Normalize phone: strip leading '+'
        phone_clean = phone.lstrip('+')
        user = User.query.filter(
            (User.phone == f'+{phone_clean}') | (User.phone == phone)
        ).first()

        if not user:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {
                    "code": -31050,
                    "message": {"uz": "Foydalanuvchi topilmadi", "ru": "Пользователь не найден", "en": "User not found"}
                }
            }), 200

        min_t = (settings.min_topup_amount or 1000) * 100
        max_t = (settings.max_topup_amount or 10000000) * 100
        if amount < min_t or amount > max_t:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {
                    "code": -31001,
                    "message": {"uz": "Noto'g'ri summa", "ru": "Неверная сумма", "en": "Invalid amount"}
                }
            }), 200

        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"allow": True}}), 200

    # ─── CreateTransaction ─────────────────────────────────────────────
    elif method == 'CreateTransaction':
        account = params.get('account', {})
        phone = get_phone(account)
        amount = params.get('amount', 0)
        payme_id = params.get('id')
        create_time = params.get('time', now_ms())

        if not phone:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31050, "message": {"en": "Phone required"}}
            }), 200

        phone_clean = phone.lstrip('+')
        user = User.query.filter(
            (User.phone == f'+{phone_clean}') | (User.phone == phone)
        ).first()

        if not user:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31050, "message": {"uz": "Foydalanuvchi topilmadi", "en": "User not found"}}
            }), 200

        min_t = (settings.min_topup_amount or 1000) * 100
        max_t = (settings.max_topup_amount or 10000000) * 100
        if amount < min_t or amount > max_t:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31001, "message": {"uz": "Noto'g'ri summa", "en": "Invalid amount"}}
            }), 200

        # Check if transaction already exists
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()
        if trans:
            if trans.status == 'failed':
                return jsonify({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -31008, "message": {"en": "Transaction cancelled"}}
                }), 200
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "create_time": create_time,
                    "transaction": str(trans.id),
                    "state": 1
                }
            }), 200

        trans = Transaction(
            user_id=user.id,
            amount=amount / 100,
            type='topup',
            status='pending',
            payme_trans_id=payme_id
        )
        db.session.add(trans)
        db.session.commit()

        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "create_time": create_time,
                "transaction": str(trans.id),
                "state": 1
            }
        }), 200

    # ─── PerformTransaction ────────────────────────────────────────────
    elif method == 'PerformTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31003, "message": {"en": "Transaction not found"}}
            }), 200

        if trans.status == 'failed':
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31008, "message": {"en": "Transaction cancelled"}}
            }), 200

        if trans.status != 'success':
            user = User.query.get(trans.user_id)
            user.balance = (user.balance or 0.0) + trans.amount
            trans.status = 'success'
            db.session.commit()

        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "transaction": str(trans.id),
                "perform_time": now_ms(),
                "state": 2
            }
        }), 200

    # ─── CancelTransaction ─────────────────────────────────────────────
    elif method == 'CancelTransaction':
        payme_id = params.get('id')
        reason = params.get('reason', 0)
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31003, "message": {"en": "Transaction not found"}}
            }), 200

        if trans.status == 'success':
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31007, "message": {"uz": "Bekor qilib bo'lmaydi", "en": "Cannot cancel completed transaction"}}
            }), 200

        trans.status = 'failed'
        db.session.commit()

        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "transaction": str(trans.id),
                "cancel_time": now_ms(),
                "state": -1
            }
        }), 200

    # ─── CheckTransaction ──────────────────────────────────────────────
    elif method == 'CheckTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -31003, "message": {"en": "Transaction not found"}}
            }), 200

        state_map = {'pending': 1, 'success': 2, 'failed': -1}
        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "create_time": 0,
                "perform_time": 0,
                "cancel_time": 0,
                "transaction": str(trans.id),
                "state": state_map.get(trans.status, 1),
                "reason": None
            }
        }), 200

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

        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"transactions": result}}), 200

    # ─── ChangePassword ────────────────────────────────────────────────
    elif method == 'ChangePassword':
        # According to Payme spec we just return success
        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"success": True}
        }), 200

    # ─── Unknown method ────────────────────────────────────────────────
    return jsonify({
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32300, "message": {"en": f"Unknown method: {method}"}}
    }), 200
