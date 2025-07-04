"""
Django settings for Handcar project.

Generated by 'django-admin startproject' using Django 5.2.1.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""
import os
from decouple import config
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the 'Handcar' subdirectory
load_dotenv(os.path.join(BASE_DIR, 'Handcar', '.env'))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", cast=bool)



SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

ALLOWED_HOSTS = config("ALLOWED_HOSTS").split(",")



# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'Handcarapp',
    'corsheaders'
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOWED_ORIGINS = [
      "https://handcar.ae",
    "https://api.handcar.ae",
    "https://admin.handcar.ae",
    "https://vendor.handcar.ae",
]


CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    "https://handcar.ae",
    "https://api.handcar.ae",
    "https://admin.handcar.ae",
    "https://vendor.handcar.ae",
]


ROOT_URLCONF = 'Handcar.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # or your template folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                # Make sure this line exists:
                'django.contrib.messages.context_processors.messages',
                'django.contrib.auth.context_processors.auth',
                # any other context processors you use...
            ],
        },
    },
]


WSGI_APPLICATION = 'Handcar.wsgi.application'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'Handcarapp.authentication.CustomJWTAuthentication', # Check cookies first, then fallback
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # Only checks headers
    ),
}


from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=30),  # Adjust as needed
    'REFRESH_TOKEN_LIFETIME': timedelta(weeks=4),     # Adjust as needed
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_COOKIE': 'access_token',                    # Name of the access token cookie
    'AUTH_COOKIE_REFRESH': 'refresh_token',           # Name of the refresh token cookie
    'AUTH_COOKIE_SECURE': True,                      # Set to True in production
    'AUTH_COOKIE_HTTP_ONLY': True,                    # Cookie is HTTP only
    'AUTH_COOKIE_PATH': '/',                          # Cookie path
    'AUTH_COOKIE_SAMESITE': 'None',                  # Adjust based on your needs (None, Lax, Strict)
    'AUTH_COOKIE_EXPIRES': timedelta(days=30),        # Set cookie expiration to 30 days
    'UPDATE_LAST_LOGIN': True

}

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config("DB_NAME"),
        'USER': config("DB_USER"),
        'PASSWORD': config("DB_PASSWORD"),
        'HOST': config("DB_HOST"),
        'PORT': config("DB_PORT"),
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

SITE_URL = "https://handcar.ae/"

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"

TEMPLATES[0]['DIRS'] = [BASE_DIR / 'templates']


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


from pathlib import Path
from datetime import timedelta
import cloudinary

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Cloudinary configuration
cloudinary.config(
    cloud_name=config("CLOUDINARY_CLOUD_NAME"),
    api_key=config("CLOUDINARY_API_KEY"),
    api_secret=config("CLOUDINARY_API_SECRET"),
    secure=True
)

OPENCAGE_API_KEY = config('OPENCAGE_API_KEY')
