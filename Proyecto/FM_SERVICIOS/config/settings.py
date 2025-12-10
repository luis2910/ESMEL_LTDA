from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
import os
BASE_DIR = Path(__file__).resolve().parent.parent

# Carga opcional de variables desde .env (sin dependencias externas)
ENV_PATH = BASE_DIR / '.env'
if ENV_PATH.exists():
    try:
        for _line in ENV_PATH.read_text(encoding='utf-8').splitlines():
            line = _line.strip()
            if not line or line.startswith('#'):
                continue
            if line.lower().startswith('export '):
                line = line[7:].strip()
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('\"').strip("'"))
                continue
            if line.lower().startswith(('setx ', 'set ')):
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    key = parts[1].strip().strip('\"').strip("'")
                    val = parts[2].strip().strip('\"').strip("'")
                    os.environ.setdefault(key, val)
    except Exception:
        # No interrumpe si .env no es legible
        pass


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_csv(name: str) -> list[str]:
    raw = os.environ.get(name, '')
    return [chunk.strip() for chunk in raw.split(',') if chunk.strip()]


SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-please-change')
DEBUG = _get_bool('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = _get_csv('DJANGO_ALLOWED_HOSTS')
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = _get_csv('DJANGO_CSRF_TRUSTED_ORIGINS')

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
SUPABASE_BUCKET_DOCUMENTOS = os.environ.get('SUPABASE_BUCKET_DOCUMENTOS', 'documentos')
SUPABASE_BUCKET_FACTURAS = os.environ.get('SUPABASE_BUCKET_FACTURAS', SUPABASE_BUCKET_DOCUMENTOS)

if os.environ.get('RENDER', '').lower() == 'true':
    render_external = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    render_internal = os.environ.get('RENDER_INTERNAL_HOSTNAME')
    if render_external and render_external not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(render_external)
    if render_external:
        origin = f"https://{render_external}"
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)
    if render_internal and render_internal not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(render_internal)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django.contrib.postgres',   # utilidades de Postgres
    'FM.apps.FMConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

_template_dirs: list[Path] = []
_global_templates = BASE_DIR / 'templates'
if _global_templates.exists():
    _template_dirs.append(_global_templates)

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': _template_dirs,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


def _database_from_url(url: str) -> dict:
    """Parsea DATABASE_URL en formato RFC-1738."""
    parsed = urlparse(url)
    scheme = parsed.scheme
    if scheme in {'postgres', 'postgresql'}:
        options = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        options.setdefault('sslmode', 'require')
        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed.path.lstrip('/') or 'postgres',
            'USER': unquote(parsed.username or ''),
            'PASSWORD': unquote(parsed.password or ''),
            'HOST': parsed.hostname or '',
            'PORT': str(parsed.port or ''),
            'OPTIONS': options,
        }
    if scheme == 'sqlite':
        db_path = parsed.path or parsed.netloc
        db_path = db_path.lstrip('/') if db_path else 'db.sqlite3'
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / db_path,
        }
    raise ValueError(f'Esquema de base de datos no soportado: {scheme}')


DATABASES: dict = {}
database_url = os.environ.get('DATABASE_URL')
db_from_url = None
if database_url:
    try:
        db_from_url = _database_from_url(database_url)
    except Exception:
        db_from_url = None

if db_from_url:
    DATABASES['default'] = db_from_url
else:
    # Fallback a Postgres con variables PG* o SQLite si DEBUG
    pg_name = os.environ.get('PGDATABASE', 'postgres')
    pg_user = os.environ.get('PGUSER', 'postgres')
    pg_pass = os.environ.get('PGPASSWORD', '')
    pg_host = os.environ.get('PGHOST', 'localhost')
    pg_port = os.environ.get('PGPORT', '5432')
    if DEBUG or os.environ.get('DJANGO_DB_ENGINE', '').lower() == 'sqlite':
        DATABASES['default'] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    else:
        DATABASES['default'] = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': pg_name,
            'USER': pg_user,
            'PASSWORD': pg_pass,
            'HOST': pg_host,
            'PORT': pg_port,
            'OPTIONS': {'sslmode': 'require'},
        }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# LocalizaciÃ³n
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# Auth redirects
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'index'
LOGOUT_REDIRECT_URL = 'login'

# Session config: expira al cerrar el navegador
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Archivos estÃ¡ticos y media
STATIC_URL = '/static/'
STATICFILES_DIRS: list[Path] = []
_project_static = BASE_DIR / 'static'
if _project_static.exists():
    STATICFILES_DIRS.append(_project_static)
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _get_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# **User personalizado**
AUTH_USER_MODEL = 'FM.User'

# Permitir iframe en el mismo origen (para ver PDFs/medios en modales)
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Email
# Por defecto en desarrollo imprime en consola. Puedes cambiarlo vÃ­a variables de entorno.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND')
if not EMAIL_BACKEND:
    _user = os.environ.get('EMAIL_HOST_USER', '')
    _pwd = os.environ.get('EMAIL_HOST_PASSWORD', '')
    if _user and _pwd:
        EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    elif DEBUG:
        EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    else:
        EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
        EMAIL_FILE_PATH = BASE_DIR / os.environ.get('EMAIL_FILE_PATH', 'sent_emails')

if EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = _get_bool('EMAIL_USE_TLS', True)
    EMAIL_USE_SSL = _get_bool('EMAIL_USE_SSL', False)
elif EMAIL_BACKEND == 'django.core.mail.backends.filebased.EmailBackend':
    EMAIL_FILE_PATH = BASE_DIR / os.environ.get('EMAIL_FILE_PATH', 'sent_emails')

# From por defecto: toma el remitente real si esta disponible
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', os.environ.get('EMAIL_HOST_USER', 'no-reply@fm-servicios.local'))

# Fallback de desarrollo: mantiene consola si fue elegido; si quieres ver archivos, define EMAIL_FILE_PATH
if EMAIL_BACKEND == 'django.core.mail.backends.filebased.EmailBackend':
    EMAIL_FILE_PATH = BASE_DIR / os.environ.get('EMAIL_FILE_PATH', 'sent_emails')

# Configuracion SendGrid (opcional, usado por FM.email_utils)
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "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")
DEFAULT_FROM_EMAIL = "no.reply.fmservicios@gmail.com"  # remitente verificado en SendGrid

# En produccion exige un backend real (SMTP o SendGrid)
if not DEBUG and EMAIL_BACKEND == 'django.core.mail.backends.filebased.EmailBackend':
    raise RuntimeError('Configura un backend SMTP o SendGrid para produccion.')


# Transbank Webpay
TB_COMMERCE_CODE = os.environ.get("TB_COMMERCE_CODE", "")
TB_API_KEY = os.environ.get("TB_API_KEY", "")
TB_INTEGRATION_TYPE = os.environ.get("TB_INTEGRATION_TYPE", "TEST")  # TEST o LIVE
TB_RETURN_URL = os.environ.get("TB_RETURN_URL", "")
