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
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def check_pin(self, pin, bcrypt):
        return bcrypt.check_password_hash(self.pin_hash, pin)
