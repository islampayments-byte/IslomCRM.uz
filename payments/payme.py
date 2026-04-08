from flask import Blueprint, request, jsonify
from models import User, PaymentSettings, Transaction
from extensions import db
import base64

payme_bp = Blueprint('payme', __name__)

def check_auth(auth_header, settings):
    """Payme Basic Auth tekshiruvi."""
    if not auth_header or not auth_header.startswith('Basic '):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        # Format: Paycom:{secret_key} yoki test-{test_key}
        key_to_check = settings.payme_test_key if settings.is_test_mode else settings.payme_secret_key
        expected = f"Paycom:{key_to_check}"
        return decoded == expected
    except Exception:
        return False

@payme_bp.route('/callback', methods=['POST'])
def payme_callback():
    """Payme merchant callback endpoint."""
    settings = PaymentSettings.query.first()

    # Auth tekshiruvi
    auth = request.headers.get('Authorization', '')
    if not check_auth(auth, settings):
        return jsonify({
            "error": {
                "code": -32504,
                "message": {"uz": "Autentifikatsiya muvaffaqiyatsiz", "ru": "Ошибка авторизации", "en": "Unauthorized"}
            },
            "id": request.json.get('id') if request.json else None
        }), 401

    data = request.json
    method = data.get('method')
    params = data.get('params', {})
    req_id = data.get('id')

    if method == 'CheckPerformTransaction':
        # Foydalanuvchini tekshirish
        phone = params.get('account', {}).get('phone', '')
        amount = params.get('amount', 0)  # tiyin

        user = User.query.filter_by(phone=f'+{phone}').first()
        if not user:
            return jsonify({
                "error": {"code": -31050, "message": {"uz": "Foydalanuvchi topilmadi", "en": "User not found"}},
                "id": req_id
            })

        min_tiyin = (settings.min_topup_amount or 1000) * 100
        max_tiyin = (settings.max_topup_amount or 10000000) * 100

        if amount < min_tiyin or amount > max_tiyin:
            return jsonify({
                "error": {"code": -31001, "message": {"uz": "Summa chegaradan tashqarida", "en": "Amount out of range"}},
                "id": req_id
            })

        return jsonify({"result": {"allow": True}, "id": req_id})

    elif method == 'CreateTransaction':
        phone = params.get('account', {}).get('phone', '')
        amount = params.get('amount', 0)
        payme_id = params.get('id')
        create_time = params.get('time')

        user = User.query.filter_by(phone=f'+{phone}').first()
        if not user:
            return jsonify({
                "error": {"code": -31050, "message": {"uz": "Foydalanuvchi topilmadi", "en": "User not found"}},
                "id": req_id
            })

        # Tranzaksiyani tekshir yoki yarat
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()
        if not trans:
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
            "result": {
                "create_time": create_time,
                "transaction": str(trans.id),
                "state": 1
            },
            "id": req_id
        })

    elif method == 'PerformTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "error": {"code": -31003, "message": {"uz": "Tranzaksiya topilmadi", "en": "Transaction not found"}},
                "id": req_id
            })

        if trans.status != 'success':
            # Balansni oshir
            user = User.query.get(trans.user_id)
            user.balance = (user.balance or 0) + trans.amount
            trans.status = 'success'
            db.session.commit()

        import datetime
        return jsonify({
            "result": {
                "transaction": str(trans.id),
                "perform_time": int(datetime.datetime.utcnow().timestamp() * 1000),
                "state": 2
            },
            "id": req_id
        })

    elif method == 'CancelTransaction':
        payme_id = params.get('id')
        reason = params.get('reason', 0)
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "error": {"code": -31003, "message": {"en": "Transaction not found"}},
                "id": req_id
            })

        if trans.status == 'success':
            # To'liq bekor qilib bo'lmaydi
            return jsonify({
                "error": {"code": -31007, "message": {"uz": "Bekor qilib bo'lmaydi", "en": "Cannot cancel"}},
                "id": req_id
            })

        trans.status = 'failed'
        db.session.commit()

        import datetime
        return jsonify({
            "result": {
                "transaction": str(trans.id),
                "cancel_time": int(datetime.datetime.utcnow().timestamp() * 1000),
                "state": -1
            },
            "id": req_id
        })

    elif method == 'CheckTransaction':
        payme_id = params.get('id')
        trans = Transaction.query.filter_by(payme_trans_id=payme_id).first()

        if not trans:
            return jsonify({
                "error": {"code": -31003, "message": {"en": "Transaction not found"}},
                "id": req_id
            })

        state_map = {'pending': 1, 'success': 2, 'failed': -1}
        return jsonify({
            "result": {
                "create_time": 0,
                "perform_time": 0,
                "cancel_time": 0,
                "transaction": str(trans.id),
                "state": state_map.get(trans.status, 1),
                "reason": None
            },
            "id": req_id
        })

    return jsonify({"error": {"code": -32300, "message": "Unknown method"}, "id": req_id})
