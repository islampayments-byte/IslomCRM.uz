import requests
import logging
import time
from extensions import db
from models import Driver, Transaction
import datetime

def sync_user_drivers(app, user):
    """
    Sinxronizatsiya funksiyasi.
    Yandex Fleet API ga bog'lanib barcha haydovchilarni mahalliy bazaga yozadi.
    app: Flask app context uchun
    """
    if not user.yandex_keys_active or not user.yandex_client_id:
        return False, "Yandex kalitlari aktiv emas"

    url = "https://fleet-api.taxi.yandex.net/v1/parks/driver-profiles/list"
    headers = {
        'X-Client-ID': user.yandex_client_id.strip(),
        'X-Api-Key': user.yandex_api_key.strip()
    }
    payload = {
        "query": {
            "park": {
                "id": user.yandex_park_id.strip()
            }
        },
        "fields": {
            "park": ["name"] # Also fetch park name just in case
        },
        "limit": 500 # Adjust up to bounds if necessary
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            # Context managing directly passed from outside, or we push one inside
            with app.app_context():
                # 1. Update Park Name if it was missing 
                if not user.yandex_park_name:
                    try:
                        parks_data = data.get('parks', [])
                        if parks_data and isinstance(parks_data, list):
                            user.yandex_park_name = parks_data[0].get('name')
                    except Exception as e:
                        logging.error(f"Error extracting park name inside sync: {e}")

                profiles = data.get('driver_profiles', [])
                current_time = datetime.datetime.now()
                added_count = 0
                updated_count = 0
                
                # Fetch existing drivers from DB. 
                # DEDUPLICATION: If we have multiple records for the same yandex_driver_id, we keep only one.
                all_raw_drivers = Driver.query.filter_by(user_id=user.id).all()
                existing_drivers = {}
                for d in all_raw_drivers:
                    if d.yandex_driver_id in existing_drivers:
                        # Duplicate found - delete the extra one
                        db.session.delete(d)
                    else:
                        existing_drivers[d.yandex_driver_id] = d
                
                # Commit any deletions before proceeding to avoid conflicts
                db.session.flush()

                for p in profiles:
                    prof = p.get('driver_profile', {})
                    y_driver_id = prof.get('id')
                    
                    if not y_driver_id:
                        continue
                        
                    first_name = prof.get('first_name', '')
                    last_name = prof.get('last_name', '')
                    status = p.get('status', 'working')  # working, fired, etc. usually in nested dicts but default working
                    
                    # Phones is an array in Yandex API
                    phones_list = prof.get('phones', [])
                    phone = phones_list[0] if phones_list else 'yo\'q'

                    if y_driver_id in existing_drivers:
                        # Update existing
                        dr = existing_drivers[y_driver_id]
                        dr.first_name = first_name
                        dr.last_name = last_name
                        dr.phone = phone
                        dr.status = status
                        dr.last_sync = current_time
                        updated_count += 1
                        # Remove from dictionary so we know which ones weren't touched
                        del existing_drivers[y_driver_id]
                    else:
                        # Add new
                        new_driver = Driver(
                            user_id=user.id,
                            yandex_driver_id=y_driver_id,
                            first_name=first_name,
                            last_name=last_name,
                            phone=phone,
                            status=status,
                            last_sync=current_time
                        )
                        db.session.add(new_driver)
                        added_count += 1

                # If any drivers left in existing_drivers, it means they are no longer in standard API list
                # We could set their status to 'fired' or 'deleted' safely.
                for missing_id, dr in existing_drivers.items():
                    dr.status = 'fired'
                    dr.last_sync = current_time
                    updated_count += 1

                db.session.commit()
                logging.info(f"Yandex Sync Success for user {user.id}. Added: {added_count}, Updated: {updated_count}")
                return True, f"Muvaffaqiyatli sinxronizatsiya. Qo'shildi: {added_count}, Yangilandi: {updated_count}"
        else:
            return False, f"Yandex API Xatosi: {response.status_code}"
    except Exception as e:
        logging.error(f"Sinxronizatsiya xatosi: {e}")
        return False, str(e)


# Yandex Fleet: Haydovchi balansini to'ldirish
YANDEX_BASE = "https://fleet-api.taxi.yandex.net"
YANDEX_TOPUP_URL = f"{YANDEX_BASE}/v2/parks/driver-profiles/transactions"
YANDEX_CATEGORIES_URL = f"{YANDEX_BASE}/v2/parks/transactions/categories/list"

# Qayta urinish soni: API vaqtincha ishlamasa shuncha marta uranamiz
YANDEX_MAX_RETRIES = 5
# Har bir urinish orasidagi kutish (soniyada)
YANDEX_RETRY_DELAY = 3  # sekund


def fetch_yandex_categories(user):
    """
    Yandex Fleet API dan ushbu park uchun barcha tranzaksiya kategoriyalarini oladi.
    Bu kategoriyalar haydovchi balansi to'ldirishda qaysi sarlavha ostida ko'rinishini belgilaydi.

    Endpoint: POST /v2/parks/transactions/categories/list
    Headers : X-Client-ID, X-Api-Key, X-Park-ID
    Body    : {} (empty or optional filters)

    Qaytaradi: list of {"id": "...", "name": "..."}  yoki bo'sh list []
    """
    if not user or not user.yandex_keys_active:
        return []
    headers = {
        'X-Client-ID': user.yandex_client_id.strip(),
        'X-Api-Key':   user.yandex_api_key.strip(),
        'X-Park-ID':   user.yandex_park_id.strip(),
        'Content-Type': 'application/json',
    }
    # V2 categories/list odatda bo'sh {} bilan ham ishlayveradi
    # V2 categories/list requires query.park.id
    payload = {
        "query": {
            "park": {
                "id": user.yandex_park_id.strip()
            }
        }
    }
    
    try:
        resp = requests.post(YANDEX_CATEGORIES_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Response format: {"categories": [{"id": "...", "name": "...", ...}]}
            categories = data.get('categories', [])
            
            result = []
            for cat in categories:
                if isinstance(cat, dict):
                    cat_id = str(cat.get('id', ''))
                    # FILTER: Faqat partner_service_manual bilan boshlanadiganlarini olamiz
                    # Bu haydovchiga barcha texnik kategoriyalarni ko'rsatmaslik uchun kerak.
                    if cat_id.startswith('partner_service_manual'):
                        result.append({
                            'id':   cat_id,
                            'name': cat.get('name', f"Kategoriya {cat_id}")
                        })
            logging.info(f"[Yandex Categories] User {user.id} uchun {len(result)} ta kategoriya olindi")
            return result, None
        else:
            err_msg = f"HTTP {resp.status_code}: {resp.text[:100]}"
            logging.error(f"[Yandex Categories] API Xatosi (User {user.id}): {err_msg}")
            return [], err_msg
    except Exception as e:
        err_msg = str(e)
        logging.error(f"[Yandex Categories] Exception (User {user.id}): {err_msg}")
        return [], err_msg


def yandex_topup_driver(app, owner_user, transaction_id, payment_method='payme'):
    """
    Muvaffaqiyatli to'lovdan keyin haydovchining Yandex Fleet balansi to'ldiriladi.

    Xavfsizlik kafolatlari:
      1. IDEMPOTENTLIK: Transaction.id Yandex'ga idempotency_key sifatida yuboriladi.
         Bir xil tranzaksiya Yandex tomonida ikki marta qayta ishlanmaydi,
         hatto biz xato sababi bir nechta marta yuborsak ham.
      2. DUPLICATE PROTECTION: yandex_sync_status == 'success' bo'lsa, funksiya
         darhol qaytadi — Yandex'ga hech qanday so'rov yuborilmaydi.
      3. RETRY: Yandex API vaqtincha ishlamasa (500/504/timeout), tizim
         YANDEX_MAX_RETRIES marta qayta urinadi. Muvaffaqiyatsiz bo'lsa,
         yandex_sync_status='failed' va xato matni bazaga yoziladi.

    :param app:            Flask app (app_context uchun)
    :param owner_user:     Taksopark User obyekti (yandex kalitlari shu userlarda)
    :param transaction_id: Bizning Transaction.id raqami
    :param payment_method: 'payme' | 'click' — qaysi kategoriyadan foydalanish
    """
    with app.app_context():
        # 1. Tranzaksiyani topamiz
        trans = Transaction.query.get(transaction_id)
        if not trans:
            logging.error(f"[Yandex Topup] Transaction #{transaction_id} topilmadi.")
            return False, "Tranzaksiya topilmadi"

        # 2. Dublikatga qarshi himoya: agar avval muvaffaqiyatli yuborilgan bo'lsa — to'xamiz
        if trans.yandex_sync_status == 'success':
            logging.info(f"[Yandex Topup] Trans #{transaction_id} allaqachon Yandex'ga yuborilgan. Qayta o'tkazilmadi.")
            return True, "Allaqachon yuborilgan"

        # 3. Yandex kalitlarini tekshiramiz
        if not owner_user.yandex_keys_active:
            logging.warning(f"[Yandex Topup] User {owner_user.id} uchun Yandex kalitlari aktiv emas.")
            trans.yandex_sync_status = 'failed'
            trans.yandex_sync_error = "Yandex kalitlari aktiv emas"
            db.session.commit()
            return False, "Yandex kalitlari aktiv emas"

        # 4. Haydovchini telefon raqamidan topamiz
        payer_phone = trans.payer_phone
        if not payer_phone:
            logging.warning(f"[Yandex Topup] Trans #{transaction_id} da payer_phone yo'q.")
            trans.yandex_sync_status = 'failed'
            trans.yandex_sync_error = "Haydovchi telefoni saqlanmagan"
            db.session.commit()
            return False, "Haydovchi telefoni yo'q"

        driver = _find_driver_by_phone(payer_phone, owner_user.id)
        if not driver:
            logging.warning(f"[Yandex Topup] Haydovchi topilmadi: {payer_phone} (user {owner_user.id})")
            trans.yandex_sync_status = 'failed'
            trans.yandex_sync_error = f"Haydovchi topilmadi (tel: {payer_phone})"
            db.session.commit()
            return False, "Haydovchi topilmadi"

        # 5. To'lov turiga qarab tegishli kategoriya IDsini tanlaymiz
        # Payme to'lovi uchun alohida, Click to'lovi uchun alohida Yandex kategoriyasi
        if payment_method == 'click':
            category_id = (owner_user.yandex_click_category_id or '1').strip()
        else:  # payme (va boshqa holatlar)
            category_id = (owner_user.yandex_payme_category_id or '1').strip()
        logging.info(f"[Yandex Topup] Trans #{transaction_id} | payment_method={payment_method} | category_id={category_id}")

        # 6. So'rov tayyorlaymiz
        headers = {
            'X-Client-ID': owner_user.yandex_client_id.strip(),
            'X-Api-Key':   owner_user.yandex_api_key.strip(),
            'X-Park-ID':   owner_user.yandex_park_id.strip(),
            'Content-Type': 'application/json',
        }
        payload = {
            "park_id":           owner_user.yandex_park_id.strip(),
            "driver_profile_id": driver.yandex_driver_id,
            "amount":            trans.amount,      # so'mda (Yandex so'mni qabul qiladi)
            "category_id":       category_id,
            # IDEMPOTENCY KEY: tranzaksiya IDsi asosida — bir xil to'lov ikki marta tushmasin
            "idempotency_key":   f"islomcrm-trans-{trans.id}",
            "remarks":           f"IslomCRM | To'lov #{trans.id}"
        }

        # 7. Retry bilan yuboramiz
        last_error = None
        for attempt in range(1, YANDEX_MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    YANDEX_TOPUP_URL,
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                logging.info(f"[Yandex Topup] Trans #{trans.id} | Attempt {attempt} | Status: {resp.status_code} | Body: {resp.text[:300]}")

                if resp.status_code in (200, 201):
                    # MUVAFFAQIYAT
                    trans.yandex_sync_status = 'success'
                    trans.yandex_sync_error  = None
                    db.session.commit()
                    logging.info(f"[Yandex Topup] Trans #{trans.id} | Yandex'ga MUVAFFAQIYATLI yuborildi: {trans.amount} so'm")
                    return True, "Muvaffaqiyatli"

                elif resp.status_code == 409:
                    # 409 Conflict = idempotency key bilan avval yuborilgan, hisoblaschan
                    trans.yandex_sync_status = 'success'
                    trans.yandex_sync_error  = "Yandex: allaqachon mavjud (409 Conflict)"
                    db.session.commit()
                    logging.info(f"[Yandex Topup] Trans #{trans.id} | Yandex 409 qaytardi — avval yuborilgan.")
                    return True, "Allaqachon yuborilgan (409)"

                elif resp.status_code in (500, 502, 503, 504):
                    # Vaqtincha server xatosi — qayta urinamiz
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logging.warning(f"[Yandex Topup] Trans #{trans.id} | Server xatosi ({resp.status_code}), {attempt}/{YANDEX_MAX_RETRIES}. {YANDEX_RETRY_DELAY}s kutamiz...")
                    if attempt < YANDEX_MAX_RETRIES:
                        time.sleep(YANDEX_RETRY_DELAY)
                    continue

                else:
                    # 400/401/403 — bizning so'rovimizda muammo, retry bekor
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    logging.error(f"[Yandex Topup] Trans #{trans.id} | Hal qilib bo'lmaydigan xato: {last_error}")
                    break

            except requests.exceptions.Timeout:
                last_error = f"Timeout (attempt {attempt})"
                logging.warning(f"[Yandex Topup] Trans #{trans.id} | Timeout, {attempt}/{YANDEX_MAX_RETRIES}")
                if attempt < YANDEX_MAX_RETRIES:
                    time.sleep(YANDEX_RETRY_DELAY)

            except Exception as e:
                last_error = str(e)
                logging.error(f"[Yandex Topup] Trans #{trans.id} | Exception: {last_error}")
                if attempt < YANDEX_MAX_RETRIES:
                    time.sleep(YANDEX_RETRY_DELAY)

        # Barcha urinishlar muvaffaqiyatsiz
        trans.yandex_sync_status = 'failed'
        trans.yandex_sync_error  = last_error
        db.session.commit()
        logging.error(f"[Yandex Topup] Trans #{trans.id} | {YANDEX_MAX_RETRIES} urinishdan keyin ham yuborilmadi. Xato: {last_error}")
        return False, last_error


def _find_driver_by_phone(phone_raw, user_id):
    """Telefon raqami bo'yicha haydovchi qidiradi (bir nechta formatda)."""
    from models import Driver
    phone = str(phone_raw).strip()
    digits = phone.lstrip('+').strip()
    if len(digits) == 9:
        digits = f"998{digits}"
    variants = [f"+{digits}", digits]
    for v in variants:
        dr = Driver.query.filter_by(user_id=user_id).filter(
            (Driver.phone == v) | (Driver.phone == v.replace('+', ''))
        ).first()
        if dr:
            return dr
    return None
