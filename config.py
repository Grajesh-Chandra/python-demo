import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "a_default_secret_key"
    DEBUG = os.environ.get("DEBUG") or True


# Add other configuration variables as needed, such as database URI, etc.
