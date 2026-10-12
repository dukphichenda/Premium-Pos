import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'inflow_premium_super_secret_key_2026_boost')
    TEMPLATES_AUTO_RELOAD = True
    
    # Permanent Session - Keep user logged in permanently (no auto log out)
    from datetime import timedelta
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Server configuration
    PORT = int(os.environ.get('PORT', 5050))
    HOST = os.environ.get('HOST', '0.0.0.0')
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')

    # PostgreSQL Database Configuration (supports local and cloud like Neon / Supabase / Vercel Postgres)
    _db_url = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL')
    RAW_DB_URL = _db_url
    IS_CLOUD_DB = bool(_db_url)
    IS_VERCEL = bool(os.environ.get('VERCEL'))
    if _db_url:
        from urllib.parse import urlparse
        _parsed = urlparse(_db_url)
        PG_HOST = _parsed.hostname or '127.0.0.1'
        PG_PORT = _parsed.port or 5432
        PG_USER = _parsed.username or 'odoo'
        PG_PASSWORD = _parsed.password or 'odoo'
        PG_DATABASE = (_parsed.path or '/inflow_premium').lstrip('/')
        PG_SSLMODE = os.environ.get('PG_SSLMODE', 'require')
    else:
        PG_HOST = os.environ.get('PG_HOST', '127.0.0.1')
        PG_PORT = int(os.environ.get('PG_PORT', 5432))
        PG_USER = os.environ.get('PG_USER', 'odoo')
        PG_PASSWORD = os.environ.get('PG_PASSWORD', 'odoo')
        PG_DATABASE = os.environ.get('PG_DATABASE', 'inflow_premium')
        PG_SSLMODE = os.environ.get('PG_SSLMODE', None)

    PG_MIN_CONN = int(os.environ.get('PG_MIN_CONN', 1))
    PG_MAX_CONN = int(os.environ.get('PG_MAX_CONN', 10))

    # Legacy inFlow SQL Server Configuration
    SQLSERVER_HOST = os.environ.get('SQLSERVER_HOST', r'.\INFLOWSQL')
    SQLSERVER_DB = os.environ.get('SQLSERVER_DB', 'inFlow')
    SQLSERVER_USER = os.environ.get('SQLSERVER_USER', 'sa')
    SQLSERVER_PASSWORD = os.environ.get('SQLSERVER_PASSWORD', 'hbsr5Fe#6w')

    # Company Defaults
    DEFAULT_CURRENCY = os.environ.get('DEFAULT_CURRENCY', 'USD')
    DEFAULT_CURRENCY_SYMBOL = os.environ.get('DEFAULT_CURRENCY_SYMBOL', '$')
    COMPANY_NAME = "inFlow Premium Wholesale & Distribution"
