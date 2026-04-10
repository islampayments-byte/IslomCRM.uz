from extensions import db
from flask_login import UserMixin
import datetime

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    pin_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user') # admin or user
    failed_attempts = db.Column(db.Integer, default=0)
    is_blocked = db.Column(db.Boolean, default=False)
    last_ip = db.Column(db.String(45))
    
    # Organization Details
    stir = db.Column(db.String(9), unique=True)
    org_name = db.Column(db.String(255))
    director = db.Column(db.String(255))
    ifut = db.Column(db.String(10))
    email = db.Column(db.String(120))
    org_phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    is_verified = db.Column(db.Boolean, default=False) # IPv6 fits in 45 chars
    balance = db.Column(db.Float, default=0.0)
    
    # Yandex Fleet Integration
    yandex_park_name = db.Column(db.String(255))
    yandex_park_id = db.Column(db.String(255))
    yandex_client_id = db.Column(db.String(255))
    yandex_api_key = db.Column(db.String(255))
    yandex_keys_active = db.Column(db.Boolean, default=False)
    
    # Personal Payment Settings (Payme per Taksopark)
    payme_merchant_id = db.Column(db.String(100))
    payme_secret_key = db.Column(db.String(255))
    payme_test_key = db.Column(db.String(255))
    is_payme_test_mode = db.Column(db.Boolean, default=True)
    
    # Personal Payment Settings (Click per Taksopark)
    click_service_id = db.Column(db.String(100))
    click_merchant_id = db.Column(db.String(100))
    click_secret_key = db.Column(db.String(255))

    # Yandex Fleet: Haydovchi balansini to'ldirishda ishlatiladigan kategoriya IDlari.
    # Payme va Click uchun alohida-alohida kategoriya bo'lishi mumkin.
    # Kategoriyalar Yandex kabineti → Moliya → Kategoriyalar bo'limida ko'rinadi.
    # Default: '1' (aksariyat parklarda standart "Ish haqi" kategoriyasi)
    yandex_payme_category_id = db.Column(db.String(50), default='1')  # Payme orqali to'lovlar uchun
    yandex_click_category_id = db.Column(db.String(50), default='1')  # Click orqali to'lovlar uchun
    
    org_slug = db.Column(db.String(100), unique=True) # URL identifier e.g. 'islom-taxi'
    
    # Telegram Bot Integration
    tg_bot_token = db.Column(db.String(255))
    tg_bot_username = db.Column(db.String(100))
    tg_mini_app_url = db.Column(db.String(512))
    
    org_logo = db.Column(db.String(255)) # Path to uploaded logo
    org_link_code = db.Column(db.String(10), unique=True) # Unique 4-char code for secure link
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    def check_pin(self, pin, bcrypt):
        return bcrypt.check_password_hash(self.pin_hash, pin)

class PaymentSettings(db.Model):
    __tablename__ = 'payment_settings'
    id = db.Column(db.Integer, primary_key=True)
    payme_merchant_id = db.Column(db.String(100))
    payme_secret_key = db.Column(db.String(255))
    payme_test_key = db.Column(db.String(255))
    is_test_mode = db.Column(db.Boolean, default=True)
    
    # Global Click Settings
    click_service_id = db.Column(db.String(100))
    click_merchant_id = db.Column(db.String(100))
    click_secret_key = db.Column(db.String(255))
    
    min_topup_amount = db.Column(db.Integer, default=1000)
    max_topup_amount = db.Column(db.Integer, default=10000000)
    payme_account_field = db.Column(db.String(50), default='phone')

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20))    # 'balance_topup' | 'driver_payment'
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    payme_trans_id = db.Column(db.String(100), unique=True)
    click_trans_id = db.Column(db.String(100), unique=True)
    payer_phone = db.Column(db.String(50))  # Kim to'ladi: haydovchi telefoni
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    # Yandex Fleet integratsiyasi uchun:
    # 'driver_payment' tranzaksiyalari uchun pul Yandex'ga ham yuboriladi.
    # yandex_sync_status: 'pending' | 'success' | 'failed' | 'not_applicable'
    #   - 'pending'        : Hali yuborilmagan yoki xatolik sabab kutmoqda (retry bo'ladi)
    #   - 'success'        : Yandex'ga muvaffaqiyatli yuborildi
    #   - 'failed'         : Bir nechta urinishdan keyin ham xato bo'ldi (admin tekshirsin)
    #   - 'not_applicable' : balance_topup uchun — Yandex kerak emas
    yandex_sync_status = db.Column(db.String(20), default='not_applicable')
    yandex_sync_error = db.Column(db.Text)  # Oxirgi xato matni (debugging uchun)

    user = db.relationship('User', backref=db.backref('transactions', lazy=True))

class Driver(db.Model):
    __tablename__ = 'drivers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    yandex_driver_id = db.Column(db.String(100), nullable=False) # Important for distinguishing updates
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    status = db.Column(db.String(50), default='working')
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    last_sync = db.Column(db.DateTime, default=datetime.datetime.now)
    
    # We will need the backref on User but for simplicity keeping it as a forward relationship 
    # to fetch drivers by user_id
    user = db.relationship('User', backref=db.backref('yandex_drivers', lazy=True))
