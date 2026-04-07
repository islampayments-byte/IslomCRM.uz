from flask import Blueprint, render_template, abort, redirect, url_for, flash
from flask_login import login_required, current_user
from models import User
from extensions import db

admin_bp = Blueprint('admin', __name__, template_folder='../templates')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin':
        abort(403)
    
    users = User.query.all()
    total_users = User.query.count()
    blocked_users = User.query.filter_by(is_blocked=True).count()
    
    return render_template('admin/dashboard.html', 
                           users=users, 
                           total_users=total_users, 
                           blocked_users=blocked_users)

@admin_bp.route('/unblock/<int:user_id>')
@login_required
def unblock_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    
    user = User.query.get_or_404(user_id)
    user.is_blocked = False
    user.failed_attempts = 0
    db.session.commit()
    
    flash(f"Foydalanuvchi {user.phone} blokdan yechildi", "success")
    return redirect(url_for('admin.dashboard'))
