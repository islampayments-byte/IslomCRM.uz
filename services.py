import requests
import logging
from extensions import db
from models import Driver
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
                
                # Fetch existing drivers from DB into a dict by yandex_driver_id
                existing_drivers = {d.yandex_driver_id: d for d in Driver.query.filter_by(user_id=user.id).all()}

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
