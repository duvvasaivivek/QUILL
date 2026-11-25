"""Settings for the QUILL order-to-audit system."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from psycopg.conninfo import conninfo_to_dict

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Read a conventional boolean environment variable."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


ON_RENDER = env_bool("RENDER")
SECURE_DEPLOYMENT = env_bool("DJANGO_SECURE", ON_RENDER)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key-change-before-deployment")
if SECURE_DEPLOYMENT and (len(SECRET_KEY) < 50 or SECRET_KEY.startswith("unsafe-development-")):
    raise ImproperlyConfigured("Set a long, random DJANGO_SECRET_KEY for the hosted deployment.")
DEBUG = env_bool("DJANGO_DEBUG", not SECURE_DEPLOYMENT) and not SECURE_DEPLOYMENT
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
if render_host := os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()
]
if SECURE_DEPLOYMENT:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "core.apps.CoreConfig",
    "masters.apps.MastersConfig",
    "inventory.apps.InventoryConfig",
    "production.apps.ProductionConfig",
    "sales.apps.SalesConfig",
    "reports.apps.ReportsConfig",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "reports.views.access",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if env_bool("USE_SQLITE_FOR_TESTS") and not SECURE_DEPLOYMENT:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.sqlite3",
        }
    }
elif database_url := os.getenv("DATABASE_URL"):
    parameters = conninfo_to_dict(database_url)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parameters.pop("dbname", ""),
        "USER": parameters.pop("user", ""),
        "PASSWORD": parameters.pop("password", ""),
        "HOST": parameters.pop("host", ""),
        "PORT": parameters.pop("port", ""),
        "OPTIONS": parameters,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "quill"),
            "USER": os.getenv("POSTGRES_USER", "quill"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "quill_local_password"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5433"),
            "CONN_MAX_AGE": 60,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "sales_orders"

# Local defaults are fictional and intended only for the sample invoices.
QUILL_INVOICE_ISSUER = {
    key: os.getenv(f"QUILL_FACTORY_{key.upper()}", "" if SECURE_DEPLOYMENT else demo_value).strip()
    for key, demo_value in {
        "name": "QUILL Demo Foods",
        "address": "Demo Industrial Estate, Tiruchirappalli, Tamil Nadu",
        "gstin": "33AAAAA0000A1Z0",
        "state_name": "Tamil Nadu",
        "state_code": "33",
    }.items()
}

# Values used by the production module in Phase 3. Keep calculations decimal-based.
DEFAULT_VARIANCE_TOLERANCE_PERCENT = "3.00"
