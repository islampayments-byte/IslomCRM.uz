from flask import Blueprint, render_template, abort, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import User
from extensions import db

admin_bp = Blueprint('admin', __name__, template_folder='../templates')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin':
        abort(403)
    
    total_users = User.query.count()
    blocked_users = User.query.filter_by(is_blocked=True).count()
    
    # Show last 5 users on dashboard
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    return render_template('admin/dashboard.html', 
                           users=recent_users, 
                           total_users=total_users, 
                           blocked_users=blocked_users)

@admin_bp.route('/users')
@login_required
def users_list():
    if current_user.role != 'admin':
        abort(403)
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/toggle_block/<int:user_id>')
@login_required
def toggle_block_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("O'zingizni bloklay olmaysiz!", "danger")
        return redirect(request.referrer or url_for('admin.users_list'))

    user.is_blocked = not user.is_blocked
    if not user.is_blocked:
        user.failed_attempts = 0
    
    db.session.commit()
    
    status = "bloklandi" if user.is_blocked else "blokdan yechildi"
    flash(f"Foydalanuvchi {user.phone} {status}", "success")
    return redirect(request.referrer or url_for('admin.users_list'))
