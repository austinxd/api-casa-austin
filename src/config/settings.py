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

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DJANGO_DEBUG', default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=['*'])

CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS", 
    default=[
        'http://localhost:8000'
    ]
)

# CORS
CORS_ALLOWED_ORIGINS = env.list(
    "DJANGO_CORS_ALLOWED_ORIGINS", 
    default=[
        'http://localhost:3000'
        'https://casaaustin.pe'
    ]
)

META_PIXEL_ID = os.environ.get("META_PIXEL_ID")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")


# Token y ID para el Píxel de Meta
META_PIXEL_ID = env("META_PIXEL_ID", default="No pixel ID")
META_PIXEL_TOKEN = env("META_PIXEL_TOKEN", default="No pixel token")

# Token y ID para la Audiencia personalizada en Meta
META_AUDIENCE_ID = env("META_AUDIENCE_ID", default="No audience ID")
META_AUDIENCE_TOKEN = env("META_AUDIENCE_TOKEN", default="No audience token")

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles"
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.clients.apps.ClientsConfig',  # Aquí la forma correcta
    'apps.property',
    'apps.reservation',
    'apps.dashboard'
]

THIRD_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular'
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
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('MYSQL_DATABASE', default='my_database'),
        'USER': 'Reservas',
        'PASSWORD': env('MYSQL_PASSWORD', default='!Leonel123'),
        'HOST': env('MYSQL_HOST', default='172.18.0.2'),
        'PORT': env('MYSQL_PORT', default='3306'),
        'OPTIONS': {'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
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

STATIC_URL = "static/"

STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'static'),
)

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Configuraciones del media
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = 'accounts.CustomUser'

DEFAULT_PAGE_SIZE = 20

# REST
REST_FRAMEWORK = {
   'DEFAULT_PERMISSION_CLASSES': (
    'rest_framework.permissions.IsAuthenticated',
    'apps.core.permissions.CustomPermissions'
    # 'rest_framework.permissions.AllowAny',
   ),
   'DEFAULT_AUTHENTICATION_CLASSES': (
       'rest_framework_simplejwt.authentication.JWTAuthentication',
   ),
    'DEFAULT_FILTER_BACKENDS': ['rest_framework.filters.SearchFilter',],
    'DEFAULT_PAGINATION_CLASS': 'apps.core.paginator.CustomPagination',
    'PAGE_SIZE': DEFAULT_PAGE_SIZE,
    
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),

    'NON_FIELD_ERRORS_KEY': 'detail',

    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'apps.core.utils.custom_exception_handler',
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

AIRBNB_API_URL_BASE = env('AIRBNB_API_URL_BASE')

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'DEBUG',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',  # Reducir la verbosidad de Django
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,  # Evitar que se propague a otros loggers
        },
    },
}

# Telegram settings
TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='No token')
CHAT_ID = env('CHAT_ID', default='N° chat ID')
SECOND_CHAT_ID = env('SECOND_CHAT_ID', default='N° second chat ID')
PERSONAL_CHAT_ID = env('PERSONAL_CHAT_ID', default='N° personal chat ID')

# Twilio settings for OTP
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID', default='No SID')
TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN', default='No token')
TWILIO_VERIFY_SID = env('TWILIO_VERIFY_SID', default='No verify SID')
TWILIO_PHONE_NUMBER = env('TWILIO_PHONE_NUMBER', default='No phone')

# Verificar que las variables de entorno se cargan correctamente
import logging

logger = logging.getLogger('apps')
logger.debug(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
logger.debug(f"CHAT_ID: {CHAT_ID}")
logger.debug(f"SECOND_CHAT_ID: {SECOND_CHAT_ID}")
logger.debug(f"PERSONAL_CHAT_ID: {PERSONAL_CHAT_ID}")
logger.debug(f"TWILIO_ACCOUNT_SID: {TWILIO_ACCOUNT_SID}")
logger.debug(f"TWILIO_VERIFY_SID: {TWILIO_VERIFY_SID}")