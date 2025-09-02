import environ
import os
from datetime import timedelta
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
env_file = os.path.join(os.path.dirname(BASE_DIR), ".env")
env.read_env(env_file=env_file)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY_DEFAULT = "django-insecure-3**i%5(i9m$3&m)&js8m^(m96!+^*t8u#r#aiq_^z-%f38hy)u"
SECRET_KEY = env("DJANGO_SECRET_KEY", default=SECRET_KEY_DEFAULT)

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
TWILIO_VERIFY_SERVICE_SID = os.environ.get('TWILIO_VERIFY_SERVICE_SID')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DJANGO_DEBUG', default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=['*'])

# Allow Replit hosts - add specific pattern for Replit domains
if '*' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.extend([
        '.replit.dev',
        '*.replit.dev'
    ])

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS",
                                default=['http://localhost:8000'])

# CORS configuration
CORS_ALLOWED_ORIGINS = [
    "https://casaaustin.pe",
    "https://www.casaaustin.pe",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://reservas.casaaustin.pe",
    "https://6d9c1416-4d5a-43ff-b6d9-45dcb8a576cf-00-1qgg6m6ft27vv.riker.replit.dev:5000",
    "https://cab29a16-7aa5-424c-bab7-ab151a3d5519-00-2791s37o4sobf.picard.replit.dev",
]

# Permitir headers adicionales para autenticación
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

CORS_ALLOW_CREDENTIALS = True

# Simple JWT Settings
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=60),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'AUTH_HEADER_TYPES': ('Bearer', ),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken', ),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# Configuraciones CORS ya definidas arriba

META_PIXEL_ID = os.environ.get("META_PIXEL_ID")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")

# AirBnB API Configuration
AIRBNB_API_URL_BASE = env("AIRBNB_API_URL_BASE",
                          default="https://api.airbnb.com/v1/calendar")

# Token y ID para el Píxel de Meta
META_PIXEL_ID = env("META_PIXEL_ID", default="No pixel ID")
META_PIXEL_TOKEN = env("META_PIXEL_TOKEN", default="No pixel token")

# Token y ID para la Audiencia personalizada en Meta
META_AUDIENCE_ID = env("META_AUDIENCE_ID", default="No audience ID")
META_AUDIENCE_TOKEN = env("META_AUDIENCE_TOKEN", default="No audience token")

# Application definition
DJANGO_APPS = [
    "django.contrib.admin", "django.contrib.auth",
    "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles"
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.clients.apps.ClientsConfig',  # Aquí la forma correcta
    'apps.property',
    'apps.reservation',
    'apps.dashboard'
]

THIRD_APPS = [
    'rest_framework', 'rest_framework_simplejwt', 'drf_spectacular',
    'corsheaders'
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS + THIRD_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
USE_MYSQL = env.bool('USE_MYSQL', default=False)

if USE_MYSQL:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('MYSQL_DATABASE', default='my_database'),
            'USER': 'Reservas',
            'PASSWORD': env('MYSQL_PASSWORD', default='!Leonel123'),
            'HOST': env('MYSQL_HOST', default='172.18.0.2'),
            'PORT': env('MYSQL_PORT', default='3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"
            }
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME":
        "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "es"

TIME_ZONE = "America/Atikokan"

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Media files configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Additional file upload settings for better compatibility
FILE_UPLOAD_HANDLERS = [
    'django.core.files.uploadhandler.TemporaryFileUploadHandler',
]
FILE_UPLOAD_TEMP_DIR = None  # Use system temp directory
FILE_UPLOAD_PERMISSIONS = 0o644

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = 'accounts.CustomUser'

DEFAULT_PAGE_SIZE = 20

# REST
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.AllowAny', ),
    'DEFAULT_AUTHENTICATION_CLASSES':
    ('rest_framework_simplejwt.authentication.JWTAuthentication', ),
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
    ],
    'DEFAULT_PAGINATION_CLASS':
    'apps.core.paginator.CustomPagination',
    'PAGE_SIZE':
    DEFAULT_PAGE_SIZE,
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'NON_FIELD_ERRORS_KEY':
    'detail',
    'DEFAULT_SCHEMA_CLASS':
    'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER':
    'apps.core.utils.custom_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1460),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1460),
}

# Dinamic Django Admin URL
DJANGO_ADMIN_PATH = env('DJANGO_ADMIN_PATH', default='admin/')

# SWAGGER SETTINGS
SPECTACULAR_SETTINGS = {
    'TITLE': 'CASA AUSTIN API DOCUMENTANTION',
    'DESCRIPTION': 'API description of Casa Austin project',
    'VERSION': '0.7',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format':
            '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'casaaustin_debug.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'apps': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate':
            False,  # Evitar propagación que puede causar duplicados
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# Telegram settings
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CHAT_ID = os.getenv('CHAT_ID')

# Google Apps Script webhook for Google Sheets integration
GOOGLE_SCRIPT_WEBHOOK = env('GOOGLE_SCRIPT_WEBHOOK', default='https://script.google.com/macros/s/AKfycbxsxAZN85mp6BlXcCT-thkDtrg1Oh3Q54HKrd1KXaSMvhRLGu_g-X7r4h6QKYRJnBzzYQ/exec')

# Telegram settings
SECOND_CHAT_ID = env('SECOND_CHAT_ID', default='No second chat ID')
PERSONAL_CHAT_ID = env('PERSONAL_CHAT_ID', default='No personal chat ID')
CLIENTS_CHAT_ID = env('CLIENTS_CHAT_ID', default='No clients chat ID')

# Twilio settings for OTP (using env function for consistency)
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID', default='No SID')
TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN', default='No token')
TWILIO_VERIFY_SID = env('TWILIO_VERIFY_SID', default='No verify SID')
TWILIO_PHONE_NUMBER = env('TWILIO_PHONE_NUMBER', default='No phone')

# OpenPay Configuration
OPENPAY_MERCHANT_ID = env('OPENPAY_MERCHANT_ID', default='No merchant ID')
OPENPAY_PRIVATE_KEY = env('OPENPAY_PRIVATE_KEY', default='No private key')
OPENPAY_PUBLIC_KEY = env('OPENPAY_PUBLIC_KEY', default='No public key')
OPENPAY_SANDBOX = env.bool('OPENPAY_SANDBOX', default=True)

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'None'

# Trusted origins para CSRF
CSRF_TRUSTED_ORIGINS = [
    "https://casaaustin.pe",
    "https://www.casaaustin.pe",
    "https://api.casaaustin.pe",
    "https://reservas.casaaustin.pe",
    "https://6d9c1416-4d5a-43ff-b6d9-45dcb8a576cf-00-1qgg6m6ft27vv.riker.replit.dev:5000",
    "https://cab29a16-7aa5-424c-bab7-ab151a3d5519-00-2791s37o4sobf.picard.replit.dev",
    # Permitir todos los dominios de Replit
    "https://*.replit.dev",
]

# Para desarrollo en Replit, también obtener el dominio actual automáticamente
import os
if os.environ.get('REPL_ID'):
    # Estamos en Replit, agregar el dominio actual
    repl_id = os.environ.get('REPL_ID')
    repl_owner = os.environ.get('REPL_OWNER')
    if repl_id and repl_owner:
        current_replit_domain = f"https://{repl_id}.{repl_owner}.replit.dev"
        if current_replit_domain not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(current_replit_domain)

# Verificar que las variables de entorno se cargan correctamente
import logging

logger = logging.getLogger('apps')
logger.debug(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
logger.debug(f"CHAT_ID: {TELEGRAM_CHAT_ID}")
logger.debug(f"SECOND_CHAT_ID: {SECOND_CHAT_ID}")
logger.debug(f"PERSONAL_CHAT_ID: {PERSONAL_CHAT_ID}")
logger.debug(f"CLIENTS_CHAT_ID: {CLIENTS_CHAT_ID}")
logger.debug(f"TWILIO_ACCOUNT_SID: {TWILIO_ACCOUNT_SID}")
logger.debug(f"TWILIO_VERIFY_SID: {TWILIO_VERIFY_SID}")
logger.debug(f"GOOGLE_SCRIPT_WEBHOOK: {GOOGLE_SCRIPT_WEBHOOK}")