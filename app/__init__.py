from flask import Flask, flash, redirect, request, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.utils.timeutil import utc_to_local

    @app.template_filter('local_time')
    def local_time_filter(dt, fmt='%b %d, %Y %I:%M %p'):
        local_dt = utc_to_local(dt)
        return local_dt.strftime(fmt) if local_dt else ''

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Your session security token expired or was invalid. Please try the action again.', 'warning')
        return redirect(request.referrer or url_for('main.dashboard')), 400

    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    return app
