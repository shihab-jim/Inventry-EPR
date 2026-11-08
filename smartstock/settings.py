"""Settings for SmartStock ERP — Development and Production ready."""
import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env file if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Security & environment
SECRET_KEY = os.environ.get(
    "SECRET_KEY", "django-insecure-development-only-change-before-deploying-smartstock"
)
DEBUG = os.environ.get("DEBUG", "True").lower() == "true"

# Allowed hosts: handles localhost, local IP, and wildcard Render subdomains
ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS", "127.0.0.1,localhost,.onrender.com"
).split(",")

# CSRF trusted origins for secure HTTPS form submissions in production
CSRF_TRUSTED_ORIGINS = [
    "https://*.onrender.com",
    "http://127.0.0.1",
    "http://localhost",
]

# Google Gemini API key — read securely from environment variable or .env
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "smartstock.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "inventory.context_processors.navigation",
            ],
        },
    }
]

WSGI_APPLICATION = "smartstock.wsgi.application"

# Database: Uses DATABASE_URL (PostgreSQL on Render) if present, else fallback to SQLite
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inventory:dashboard"
LOGOUT_REDIRECT_URL = "login"
