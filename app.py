from flask import Flask, redirect, url_for

app = Flask(__name__)
app.config['SECRET_KEY'] = 'islomcrm-secret-key-123'

# Import blueprints
from admin.routes import admin_bp
from user.routes import user_bp

# Register blueprints
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(user_bp, url_prefix='/user')

@app.route('/')
def index():
    # Redirect to user portal by default or show a landing page
    return redirect(url_for('user.dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
