import os
import secrets
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


def _get_or_create_secret(env_var, file_name):
    """
    Reads a secret from the environment, falling back to a locally
    persisted random value (generated once, reused across restarts) instead
    of a hardcoded default. Mirrors the VAPID key persistence pattern below.
    """
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val

    path = os.path.join(basedir, file_name)
    if os.path.exists(path):
        with open(path, 'r') as f:
            existing = f.read().strip()
            if existing:
                return existing

    value = secrets.token_hex(32)
    try:
        with open(path, 'w') as f:
            f.write(value)
    except Exception:
        pass
    return value


class Config:
    SECRET_KEY = _get_or_create_secret('SECRET_KEY', '.secret_key')

    # Defaults to local SQLite database if DATABASE_URL is not set.
    # To use MySQL: set DATABASE_URL=mysql+pymysql://<user>:<password>@<host>:<port>/<db_name>
    default_db_path = os.path.join(basedir, 'meditrack.db').replace('\\', '/')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{default_db_path}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Household local timezone, used for daily reset boundaries, reminder
    # slot detection, and displaying timestamps (storage stays UTC).
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE', 'Asia/Dhaka')

    # Cron / Webhook Secret for automated wake-up triggers
    CRON_SECRET_TOKEN = _get_or_create_secret('CRON_SECRET_TOKEN', '.cron_secret')

    # Rate limiting storage (in-memory is fine for a single-process deployment)
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    # Web Push VAPID Configuration
    VAPID_CLAIMS_EMAIL = os.environ.get('VAPID_CLAIMS_EMAIL', 'admin@meditrack.local')
    _priv_path = os.path.join(basedir, 'vapid_private.pem')
    _pub_path = os.path.join(basedir, 'vapid_public.txt')
    
    if os.environ.get('VAPID_PRIVATE_KEY') and os.environ.get('VAPID_PUBLIC_KEY'):
        VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
        VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    elif os.path.exists(_priv_path) and os.path.exists(_pub_path):
        with open(_priv_path, 'r') as f:
            VAPID_PRIVATE_KEY = f.read().strip()
        with open(_pub_path, 'r') as f:
            VAPID_PUBLIC_KEY = f.read().strip()
    else:
        try:
            from py_vapid import Vapid
            from cryptography.hazmat.primitives import serialization
            import base64
            v = Vapid()
            v.generate_keys()
            VAPID_PRIVATE_KEY = v.private_pem().decode('utf-8')
            raw_pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(raw_pub).decode('utf-8').rstrip('=')
            with open(_priv_path, 'w') as f:
                f.write(VAPID_PRIVATE_KEY)
            with open(_pub_path, 'w') as f:
                f.write(VAPID_PUBLIC_KEY)
        except Exception:
            VAPID_PRIVATE_KEY = ''
            VAPID_PUBLIC_KEY = ''
