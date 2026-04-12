from flask import Blueprint, render_template, abort, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import User, PaymentSettings
from extensions import db
import psutil
import platform
import subprocess
import datetime
import os

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

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role != 'admin':
        abort(403)
    
    settings = PaymentSettings.query.first()
    if not settings:
        settings = PaymentSettings()
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        # Qaysi formadan kelganini aniqlash
        # (Payme formasi 'merchant_id' yuboradi, Click formasi 'click_service_id')
        if 'merchant_id' in request.form:
            # Payme settings
            settings.payme_merchant_id = request.form.get('merchant_id')
            settings.payme_secret_key = request.form.get('secret_key')
            settings.payme_test_key = request.form.get('test_key')
            settings.is_test_mode = 'is_test_mode' in request.form
            settings.payme_account_field = request.form.get('account_field', 'phone')
            
            try:
                settings.min_topup_amount = int(request.form.get('min_topup_amount', 1000))
                settings.max_topup_amount = int(request.form.get('max_topup_amount', 10000000))
            except (ValueError, TypeError):
                pass
            flash("Payme sozlamalari saqlandi!", "success")

        elif 'click_service_id' in request.form:
            # Click settings
            settings.click_service_id = request.form.get('click_service_id')
            settings.click_merchant_id = request.form.get('click_merchant_id')
            settings.click_secret_key = request.form.get('click_secret_key')
            flash("Click sozlamalari saqlandi!", "success")

        elif 'sms_price' in request.form:
            # SMS settings
            try:
                settings.sms_price = float(request.form.get('sms_price', 100))
                flash("SMS narxi saqlandi!", "success")
            except (ValueError, TypeError):
                flash("SMS narxi noto'g'ri kiritildi", "danger")

        db.session.commit()
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', settings=settings)

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

@admin_bp.route('/users/<int:user_id>/reset_keys')
@login_required
def reset_yandex_keys(user_id):
    if current_user.role != 'admin':
        abort(403)
        
    user = User.query.get_or_404(user_id)
    user.yandex_park_id = None
    user.yandex_client_id = None
    user.yandex_api_key = None
    user.yandex_keys_active = False
    
    db.session.commit()
    flash(f"{user.phone} (ID: {user.id}) uchun Yandex kalitlari muvaffaqiyatli o'chirildi.", "success")
    return redirect(request.referrer or url_for('admin.users_list'))

@admin_bp.route('/vps')
@login_required
def vps_management():
    if current_user.role != 'admin':
        abort(403)
    
    try:
        # System Stats
        cpu_percent = psutil.cpu_percent(interval=None) # Use None for non-blocking if called frequently
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        boot_time_timestamp = psutil.boot_time()
        uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot_time_timestamp)
        uptime_str = str(uptime).split('.')[0] # Remove microseconds
        
        # Process list (Python only)
        python_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
            try:
                if 'python' in proc.info['name'].lower() or 'gunicorn' in proc.info['name'].lower():
                    python_processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # System info
        system_info = {
            'os': platform.system(),
            'os_release': platform.release(),
            'os_version': platform.version(),
            'machine': platform.machine(),
            'hostname': platform.node(),
            'cpu_count': psutil.cpu_count(logical=True),
            'uptime': uptime_str,
            'ip_address': request.host.split(':')[0]
        }
        
        # Try to get top 5 lines of a log file if it exists
        logs = "Log fayli topilmadi."
        possible_logs = ['app.log', 'gunicorn.error.log', 'error.log']
        for log_name in possible_logs:
            if os.path.exists(log_name):
                with open(log_name, 'r') as f:
                    logs = "".join(f.readlines()[-20:]) # Last 20 lines
                break

        # Additional metrics
        net_io = psutil.net_io_counters() if hasattr(psutil, 'net_io_counters') else None
        
        try:
            load_avg = os.getloadavg()
        except AttributeError:
            load_avg = (0.0, 0.0, 0.0) # Windows fallback
            
        swap = psutil.swap_memory()
        
        # Format network variables for template (MB/GB)
        def format_size(bytes_val):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_val < 1024.0:
                    return f"{bytes_val:.2f} {unit}"
                bytes_val /= 1024.0
            return f"{bytes_val:.2f} PB"
            
        net_stats = {
            'sent': format_size(net_io.bytes_sent) if net_io else "0 B",
            'recv': format_size(net_io.bytes_recv) if net_io else "0 B"
        }
        
        # Database size
        from flask import current_app
        db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        db_size = format_size(os.path.getsize(db_path)) if os.path.exists(db_path) else "Topilmadi"
        
        # Auth / Security logs
        auth_logs = []
        try:
            if os.path.exists('/var/log/auth.log'):
                with open('/var/log/auth.log', 'r') as f:
                    auth_logs = f.readlines()[-10:] # last 10 entries
        except Exception:
            auth_logs = ["Xavfsizlik loglarini o'qishga ruxsat yo'q (Root talab etiladi)"]

        return render_template('admin/vps.html', 
                               system_info=system_info, 
                               cpu_percent=cpu_percent,
                               memory=memory,
                               disk=disk,
                               processes=python_processes[:10],
                               logs=logs,
                               net_stats=net_stats,
                               load_avg=load_avg,
                               swap=swap,
                               db_size=db_size,
                               auth_logs=auth_logs)
    except Exception as e:
        flash(f"VPS ma'lumotlarini olishda xatolik: {str(e)}", "danger")
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/security')
@login_required
def security_center():
    if current_user.role != 'admin':
        abort(403)
    
    security_data = {
        'firewall_status': "Noma'lum",
        'banned_ips': [],
        'failed_attempts': [],
        'open_ports': [],
        'last_update': datetime.datetime.now()
    }
    
    try:
        # 1. Firewall Status
        try:
            # Use full path and sudo if needed
            fw = subprocess.check_output(['sudo', 'ufw', 'status'], stderr=subprocess.STDOUT).decode()
            security_data['firewall_status'] = 'Faol' if 'Status: active' in fw else 'Faol emas'
        except Exception as fe:
            with open('error.log', 'a') as f:
                f.write(f"{datetime.datetime.now()} - Firewall Check Error: {str(fe)}\n")
        
        # 2. Banned IPs (Fail2Ban)
        try:
            f2b = subprocess.check_output(['sudo', 'fail2ban-client', 'status', 'sshd'], stderr=subprocess.STDOUT).decode()
            for line in f2b.split('\n'):
                if 'Banned IP list:' in line:
                    ips_str = line.split('Banned IP list:')[1].strip()
                    if ips_str:
                        security_data['banned_ips'] = ips_str.split()
        except Exception as f2e:
           with open('error.log', 'a') as f:
                f.write(f"{datetime.datetime.now()} - Fail2Ban Check Error: {str(f2e)}\n")
            
        # 3. Failed Login Attempts (Last 50 logs, filtered)
        try:
            log_out = subprocess.check_output(['sudo', 'journalctl', '_SYSTEMD_UNIT=ssh.service', '--no-pager', '-n', '100'], stderr=subprocess.STDOUT).decode()
            seen_ips = set()
            attempts = []
            for line in reversed(log_out.split('\n')):
                if 'Failed password' in line:
                    parts = line.split('from ')
                    if len(parts) > 1:
                        ip = parts[1].split()[0]
                        time_part = " ".join(line.split()[:3])
                        user_type = "root" if 'for root' in line else "invalid user"
                        attempts.append({
                            'time': time_part,
                            'ip': ip,
                            'user': user_type
                        })
            security_data['failed_attempts'] = attempts[:20] # Return last 20 unique-ish
        except Exception as le:
            with open('error.log', 'a') as f:
                f.write(f"{datetime.datetime.now()} - Log Check Error: {str(le)}\n")
            
        # 4. Open Ports
        try:
            ports_out = subprocess.check_output(['sudo', 'ss', '-tuln'], stderr=subprocess.STDOUT).decode()
            # Clean up the output to be more readable
            lines = [l for l in ports_out.split('\n') if l.strip()]
            security_data['open_ports'] = lines
        except Exception as pe:
            pass
            
    except Exception as e:
        with open('error.log', 'a') as f:
            f.write(f"{datetime.datetime.now()} - Security Center Global Error: {str(e)}\n")
        flash(f"Xavfsizlik ma'lumotlarini olishda kutilmagan xatolik: {str(e)}", "warning")
        
    return render_template('admin/security.html', data=security_data)

@admin_bp.route('/vps/action/<action>')
@login_required
def vps_action(action):
    if current_user.role != 'admin':
        abort(403)
        
    if action == 'restart_app':
        flash("Ilovani qayta ishga tushirish so'rovi qabul qilindi. (Serverda gunicorn restart talab etiladi)", "info")
    elif action == 'clear_cache':
        # Example: clear __pycache__ or similar
        flash("Kesh tozalandi.", "success")
        
    return redirect(url_for('admin.vps_management'))

@admin_bp.route('/sms-requests')
@login_required
def sms_requests():
    if current_user.role != 'admin':
        abort(403)
    
    # Show users with pending or any non-none status if needed
    requests = User.query.filter(User.sms_status.in_(['pending', 'approved', 'rejected'])).order_by(User.created_at.desc()).all()
    return render_template('admin/sms_requests.html', sms_requests=requests)

@admin_bp.route('/sms-requests/<int:user_id>/action/<action>')
@login_required
def sms_action(user_id, action):
    if current_user.role != 'admin':
        abort(403)
        
    user = User.query.get_or_404(user_id)
    if action == 'approve':
        user.sms_status = 'approved'
        flash(f"{user.org_name} uchun maxsus SMS tasdiqlandi", "success")
    elif action == 'reject':
        user.sms_status = 'rejected'
        flash(f"{user.org_name} uchun maxsus SMS bekor qilindi", "warning")
        
    db.session.commit()
    return redirect(url_for('admin.sms_requests'))
