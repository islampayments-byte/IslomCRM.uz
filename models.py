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
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def check_pin(self, pin, bcrypt):
        return bcrypt.check_password_hash(self.pin_hash, pin)

class PaymentSettings(db.Model):
    __tablename__ = 'payment_settings'
    id = db.Column(db.Integer, primary_key=True)
    payme_merchant_id = db.Column(db.String(100))
    payme_secret_key = db.Column(db.String(255))
    payme_test_key = db.Column(db.String(255))
    is_test_mode = db.Column(db.Boolean, default=True)
    min_topup_amount = db.Column(db.Integer, default=1000)
    max_topup_amount = db.Column(db.Integer, default=10000000)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20)) # topup or payment
    status = db.Column(db.String(20), default='pending') # pending, success, failed
    payme_trans_id = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))
