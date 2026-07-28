import os
# from backend.Routes.user_route import CASHFREE_SECRET_KEY
from cashfree_pg.api_client import Cashfree

class Config():
    DEBUG = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "connect_args": {"sslmode": "require"},
    }

class LocalDevelopmentConfig(Config):
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")

    SECRET_KEY = os.getenv("SECRET_KEY")

    SECURITY_PASSWORD_HASH = "bcrypt"
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "this-is-a-password-salt")

    WTF_CSRF_ENABLED = False
    SECURITY_TOKEN_AUTHENTICATION_HEADER = "Authentication-Token"
    SECURITY_TOKEN_AUTHENTICATION_KEY = "auth_token"

    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    
    # In config.py
    CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID")
    CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY")
    CASHFREE_API_URL = os.getenv("CASHFREE_API_URL", "https://api.cashfree.com/pg")

    # Initialize Cashfree
    from cashfree_pg.api_client import Cashfree
    Cashfree.XClientId = CASHFREE_APP_ID
    Cashfree.XClientSecret = CASHFREE_SECRET_KEY
    Cashfree.XEnvironment = Cashfree.PRODUCTION  # Use Cashfree.SANDBOX for testing
