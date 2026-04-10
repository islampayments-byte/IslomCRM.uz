from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import User, PaymentSettings, Transaction, Driver
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

@user_bp.route('/pricing')
@login_required
def pricing():
    return render_template('user/pricing.html')

@user_bp.route('/drivers')
@login_required
def drivers():
    drivers_data = []
    error_msg = None
    
    if current_user.yandex_keys_active:
        try:
            # CLEANUP DUPLICATES: One-time/Continuous check to ensure database integrity
            all_drivers = Driver.query.filter_by(user_id=current_user.id).all()
            unique_ids = set()
            for dr in all_drivers:
                if dr.yandex_driver_id in unique_ids:
                    db.session.delete(dr)
                else:
                    unique_ids.add(dr.yandex_driver_id)
            db.session.commit()

            # Query the local database correctly after cleanup
            local_drivers = Driver.query.filter_by(user_id=current_user.id).order_by(Driver.created_at.desc()).all()
            for dr in local_drivers:
                drivers_data.append({
                    'first_name': dr.first_name or '',
                    'last_name': dr.last_name or '',
                    'phones': [dr.phone] if dr.phone and dr.phone != "yo'q" else [],
                    'status': dr.status
                })
        except Exception as e:
            error_msg = f"Baza bilan bog'lanishda xato: {str(e)}"
            
    return render_template('user/drivers.html', drivers=drivers_data, error_msg=error_msg)

@user_bp.route('/webhook/driver_add', methods=['POST'])
def webhook_driver_add():
    """
    Bot yoki tizim API orqali chaqiriladi.
    Secret Tokenni tekshirish majburiy.
    Expected JSON: 
    {
        "secret_token": "YOUR_SECRET_TOKEN",
        "user_id": 1,
        "first_name": "Eshmat",
        "last_name": "Toshmatov",
        "phone": "+998...",
        "yandex_driver_id": "ab123..."
    }
    """
    from flask import request, jsonify
    data = request.json
    
    if not data or data.get('secret_token') != 'islomcrm_secret_2026':
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = data.get('user_id')
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    try:
        new_driver = Driver(
            user_id=user_id,
            yandex_driver_id=data.get('yandex_driver_id'),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            phone=data.get('phone', ''),
            status='working'
        )
        db.session.add(new_driver)
        db.session.commit()
        return jsonify({"success": True, "message": "Driver gracefully added to local DB!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@user_bp.route('/drivers/auto-reg')
@login_required
def auto_reg():
    return render_template('user/auto_reg.html')

@user_bp.route('/drivers/self-employed')
@login_required
def self_employed():
    return render_template('user/self_employed.html')

@user_bp.route('/drivers/callsigns')
@login_required
def callsigns():
    return render_template('user/callsigns.html')

@user_bp.route('/drivers/terms')
@login_required
def terms():
    return render_template('user/terms.html')

@user_bp.route('/settings')
@login_required
def settings():
    return render_template('user/settings.html')

@user_bp.route('/settings/yandex/save', methods=['POST'])
@login_required
def save_yandex_keys():
    if current_user.yandex_keys_active:
        flash("Kalitlar allaqachon tasdiqlangan va saqlangan.", "warning")
        return redirect(url_for('user.settings'))
        
    park_id = request.form.get('park_id')
    client_id = request.form.get('client_id')
    api_key = request.form.get('api_key')
    
    if not all([park_id, client_id, api_key]):
        flash("Barcha qatorlarni to'ldiring.", "danger")
        return redirect(url_for('user.settings'))
        
    # Verify using Yandex API Endpoint (fetching empty list of drivers to test Auth)
    url = "https://fleet-api.taxi.yandex.net/v1/parks/driver-profiles/list"
    headers = {
        'X-Client-ID': client_id.strip(),
        'X-Api-Key': api_key.strip()
    }
    payload = {
        "query": {
            "park": {
                "id": park_id.strip()
            }
        },
        "fields": {
            "park": ["name"]
        },
        "limit": 1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Extract park name if available
            park_name = "Yandex Taksopark"
            try:
                parks_data = data.get('parks', [])
                if parks_data and isinstance(parks_data, list):
                    park_name = parks_data[0].get('name', 'Yandex Taksopark')
            except Exception as e:
                logging.error(f"Failed to parse park name: {e}")

            current_user.yandex_park_name = park_name
            current_user.yandex_park_id = park_id.strip()
            current_user.yandex_client_id = client_id.strip()
            current_user.yandex_api_key = api_key.strip()
            current_user.yandex_keys_active = True
            
            # Generate org_slug automatically from park name if it doesn't exist
            if not current_user.org_slug:
                import re
                slug = re.sub(r'[^a-z0-9]', '-', park_name.lower()).strip('-')
                # Check for uniqueness just in case
                existing = User.query.filter_by(org_slug=slug).first()
                if existing:
                    import random
                    slug = f"{slug}-{random.randint(100, 999)}"
                current_user.org_slug = slug
                
            db.session.commit()
            flash(f"Yandex API kalitlari muvaffaqiyatli saqlandi va bog'landi! (Park: {park_name})", "success")
        else:
            flash(f"Kalitlar aktiv emas yoki xato (Status: {response.status_code}). Boshqatdan urinib ko'ring.", "danger")
            logging.error(f"Yandex API klyuch test xatosi: {response.text}")
    except Exception as e:
        flash(f"Server(lar) bilan bog'lanishda xatolik yuz berdi: {str(e)}", "danger")
        
    return redirect(url_for('user.settings'))

@user_bp.route('/settings/permissions')
@login_required
def permissions():
    return render_template('user/permissions.html')

@user_bp.route('/settings/payments', methods=['GET', 'POST'])
@login_required
def payment_settings():
    if request.method == 'POST':
        payment_method = request.form.get('payment_method', 'payme')
        
        if payment_method == 'payme':
            merchant_id = request.form.get('merchant_id')
            secret_key = request.form.get('secret_key')
            test_key = request.form.get('test_key')
            test_mode = request.form.get('test_mode') == 'on'
            
            if not merchant_id or not secret_key:
                flash("Payme: Merchant ID va Secret Key bo'sh bo'lmasligi kerak.", "danger")
                return redirect(url_for('user.payment_settings'))
                
            current_user.payme_merchant_id = merchant_id.strip()
            current_user.payme_secret_key = secret_key.strip()
            current_user.payme_test_key = test_key.strip() if test_key else None
            current_user.is_payme_test_mode = test_mode
            flash("Payme sozlamalari muvaffaqiyatli saqlandi!", "success")

        elif payment_method == 'click':
            click_service_id = request.form.get('click_service_id')
            click_merchant_id = request.form.get('click_merchant_id')
            click_secret_key = request.form.get('click_secret_key')
            
            if not click_service_id or not click_merchant_id or not click_secret_key:
                flash("Click: Barcha qatorlarni to'ldiring.", "danger")
                return redirect(url_for('user.payment_settings'))
                
            current_user.click_service_id = click_service_id.strip()
            current_user.click_merchant_id = click_merchant_id.strip()
            current_user.click_secret_key = click_secret_key.strip()
            flash("Click sozlamalari muvaffaqiyatli saqlandi!", "success")

        elif payment_method == 'yandex_payme_category':
            # Payme orqali haydovchi to'lovi uchun Yandex kategoriya IDsini saqlaymiz.
            # Bo'sh yuborilsa — default '1' (standart kategoriya).
            cat_id = request.form.get('yandex_payme_category_id', '').strip()
            current_user.yandex_payme_category_id = cat_id if cat_id else '1'
            flash(f"Payme uchun Yandex kategoriyasi saqlandi: #{current_user.yandex_payme_category_id}", "success")

        elif payment_method == 'yandex_click_category':
            # Click orqali haydovchi to'lovi uchun alohida Yandex kategoriya IDsini saqlaymiz.
            # Bo'sh yuborilsa — default '1' (standart kategoriya).
            cat_id = request.form.get('yandex_click_category_id', '').strip()
            current_user.yandex_click_category_id = cat_id if cat_id else '1'
            flash(f"Click uchun Yandex kategoriyasi saqlandi: #{current_user.yandex_click_category_id}", "success")
        
        # Ensure org_slug exists (safety check)
        if not current_user.org_slug and current_user.yandex_park_name:
            import re
            slug = re.sub(r'[^a-z0-9]', '-', current_user.yandex_park_name.lower()).strip('-')
            current_user.org_slug = slug
            
        db.session.commit()
        return redirect(url_for('user.payment_settings'))
        
    return render_template('user/payment_settings.html')


@user_bp.route('/ajax/yandex-categories')
@login_required
def ajax_yandex_categories():
    """
    AJAX endpoint — Yandex Fleet API dan kategoriyalar ro'yxatini qaytaradi.
    JavaScript bu endpointga murojaat qilib, dropdownni to'ldiradi.
    Natija: [{"id": "1", "name": "Ish haqi"}, ...]
    """
    from services import fetch_yandex_categories
    if not current_user.yandex_keys_active:
        return jsonify({'error': 'Yandex kalitlari aktiv emas', 'categories': []}), 400
    
    categories, error_msg = fetch_yandex_categories(current_user)
    
    if error_msg:
        return jsonify({'error': f"Yandex API xatosi: {error_msg}", 'categories': []}), 500
        
    return jsonify({'categories': categories})

@user_bp.route('/finance')
@login_required
def finance():
    settings = PaymentSettings.query.first()
    min_amount = settings.min_topup_amount if settings else 1000
    max_amount = settings.max_topup_amount if settings else 10000000
    
    # Fetch user's system balance transactions (most recent first)
    transactions = Transaction.query.filter_by(
        user_id=current_user.id, 
        type='balance_topup'
    ).order_by(Transaction.id.desc()).all()
    
    return render_template('user/finance.html', 
                          min_amount=min_amount, 
                          max_amount=max_amount,
                          transactions=transactions)

@user_bp.route('/reports')
@login_required
def reports():
    """
    Hisobotlar bo'limi.
    Faqat haydovchilar tranzaksiyalarini ko'rsatadi (driver_payment).
    User o'z balansini to'ldirganda bu yerda ko'rinmaydi.
    """
    # Filter params
    status_filter = request.args.get('status', 'all')
    
    # Faqat haydovchi to'lovlari — type='driver_payment'
    query = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.type == 'driver_payment'
    )
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    transactions = query.order_by(Transaction.id.desc()).all()

    # Summary stats (faqat driver_payment)
    all_driver_trans = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.type == 'driver_payment'
    ).all()
    
    total_count   = len(all_driver_trans)
    success_count = sum(1 for t in all_driver_trans if t.status == 'success')
    pending_count = sum(1 for t in all_driver_trans if t.status == 'pending')
    failed_count  = sum(1 for t in all_driver_trans if t.status == 'failed')
    
    total_amount   = sum(t.amount for t in all_driver_trans if t.status == 'success')
    pending_amount = sum(t.amount for t in all_driver_trans if t.status == 'pending')

    # Drivers lookup map for phone display
    drivers = Driver.query.filter_by(user_id=current_user.id).all()
    driver_map = {d.phone: d for d in drivers}
    driver_map.update({d.phone.replace('+', ''): d for d in drivers if d.phone})

    return render_template('user/reports.html',
        transactions=transactions,
        status_filter=status_filter,
        total_count=total_count,
        success_count=success_count,
        pending_count=pending_count,
        failed_count=failed_count,
        total_amount=total_amount,
        pending_amount=pending_amount,
        driver_map=driver_map,
    )

@user_bp.route('/topup/payme', methods=['POST'])
@login_required
def topup_payme():
    """
    IslomCRM platformasidagi foydalanuvchi balansini Payme orqali to'ldirish.
    
    MUHIM QOIDA:
      - Bu route FAQAT global admin PaymentSettings kalitlarini ishlatadi.
      - Foydalanuvchining o'z Payme kalitlari (payme_merchant_id) faqat
        HAYDOVCHILAR to'lovlari uchun mo'ljallangan (per-org callback).
      - Callback URL: /payments/payme/callback (global)
    """
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        flash("Iltimos, to'g'ri summa kiriting", "danger")
        return redirect(url_for('user.finance'))

    amount = int(amount)

    # FAQAT admin global kalitlaridan foydalanamiz
    global_settings = PaymentSettings.query.first()
    if not global_settings or not global_settings.payme_merchant_id or not global_settings.payme_secret_key:
        flash("To'lov tizimi hali sozlanmagan. Iltimos, adminga murojaat qiling.", "warning")
        return redirect(url_for('user.finance'))

    merchant_id  = global_settings.payme_merchant_id
    secret_key   = global_settings.payme_secret_key
    is_test      = bool(getattr(global_settings, 'is_test_mode', False))
    logging.info(f"Topup started | user: {current_user.phone} | test: {is_test}")

    min_amount = global_settings.min_topup_amount if global_settings else 1000
    max_amount = global_settings.max_topup_amount if global_settings else 10000000

    if amount < min_amount:
        flash(f"Minimal to'ldirish summasi — {min_amount:,} so'm".replace(',', ' '), "danger")
        return redirect(url_for('user.finance'))

    if amount > max_amount:
        flash(f"Maksimal to'ldirish summasi — {max_amount:,} so'm".replace(',', ' '), "danger")
        return redirect(url_for('user.finance'))

    # Payme expects amount in tiyin (1 sum = 100 tiyin)
    amount_tiyin = amount * 100
    phone_clean = current_user.phone.replace('+', '').replace(' ', '')
    account_field = getattr(global_settings, 'payme_account_field', None) or 'phone'
    
    # API URLs and auth key — test vs production
    if is_test:
        api_url = "https://checkout.test.paycom.uz/api"
        checkout_base = "https://checkout.test.paycom.uz"
        # In test mode, use test_key if available
        if current_user.payme_merchant_id and current_user.payme_test_key:
            auth_key = current_user.payme_test_key
        elif global_settings and global_settings.payme_test_key:
            auth_key = global_settings.payme_test_key
        else:
            auth_key = secret_key
    else:
        api_url = "https://checkout.paycom.uz/api"
        checkout_base = "https://checkout.paycom.uz"
        auth_key = secret_key

    # 1. Create a receipt via Payme API
    headers = {
        "X-Auth": f"{merchant_id}:{auth_key}",
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
        "id": int(os.urandom(4).hex(), 16)
    }
    logging.info(f"Payme receipts.create | merchant:{merchant_id} | test:{is_test} | url:{api_url}")

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        logging.info(f"Payme response: {res_data}")
        
        if "error" in res_data:
            err = res_data['error']
            err_msg = err.get('message', {})
            if isinstance(err_msg, dict):
                err_msg = err_msg.get('uz') or err_msg.get('ru') or err_msg.get('en') or str(err)
            logging.error(f"Payme API Error: {err}")
            flash(f"To'lov tizimida xatolik: {err_msg} (kod: {err.get('code', '?')})", "danger")
            return redirect(url_for('user.finance'))
            
        receipt_id = res_data["result"]["receipt"]["_id"]
        
        # 2. Redirect to Payme checkout
        payme_redirect_url = f"{checkout_base}/{receipt_id}"

        # Create pending transaction locally (balance_topup = user o'z balansi)
        new_trans = Transaction(
            user_id=current_user.id,
            amount=amount,
            type='balance_topup',
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

@user_bp.route('/topup/click', methods=['POST'])
@login_required
def topup_click():
    """
    IslomCRM platformasidagi foydalanuvchi balansini Click orqali to'ldirish.
    FAQAT global admin kalitlaridan foydalanamiz.
    """
    amount = request.form.get('amount')
    if not amount or not amount.isdigit():
        flash("Iltimos, to'g'ri summa kiriting", "danger")
        return redirect(url_for('user.finance'))

    amount = int(amount)
    global_settings = PaymentSettings.query.first()
    
    if not global_settings or not global_settings.click_service_id or not global_settings.click_merchant_id:
        flash("Click to'lov tizimi hali sozlanmagan.", "warning")
        return redirect(url_for('user.finance'))

    service_id = global_settings.click_service_id
    merchant_id = global_settings.click_merchant_id
    
    # Create pending transaction locally
    new_trans = Transaction(
        user_id=current_user.id,
        amount=amount,
        type='balance_topup',
        status='pending',
        payer_phone=current_user.phone
    )
    db.session.add(new_trans)
    db.session.commit()

    # Click Redirect URL construction
    # https://my.click.uz/services/pay?service_id=ID&merchant_id=ID&amount=AMOUNT&transaction_param=TRANS_ID
    # Click expects amount as float (e.g. 1000.00)
    click_url = (
        f"https://my.click.uz/services/pay?"
        f"service_id={service_id}&"
        f"merchant_id={merchant_id}&"
        f"amount={amount}&"
        f"transaction_param={new_trans.id}"
    )
    
    logging.info(f"Click topup started | user: {current_user.phone} | trans: {new_trans.id}")
    return redirect(click_url)

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
