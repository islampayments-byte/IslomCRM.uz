from flask import Blueprint, render_template
from flask_login import login_required, current_user

user_bp = Blueprint('user', __name__, template_folder='../templates')

@user_bp.route('/')
@login_required
def dashboard():
    return render_template('user/dashboard.html')

@user_bp.route('/finance')
@login_required
def finance():
    return render_template('user/finance.html')
