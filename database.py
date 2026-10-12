import os
import logging
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from config import Config

logger = logging.getLogger('inflow.database')

_connection_pool = None

def get_connection_pool():
    global _connection_pool
    if _connection_pool is None:
        try:
            if getattr(Config, 'RAW_DB_URL', None):
                _connection_pool = pool.ThreadedConnectionPool(
                    Config.PG_MIN_CONN,
                    Config.PG_MAX_CONN,
                    dsn=Config.RAW_DB_URL
                )
            else:
                pool_kwargs = {
                    'minconn': Config.PG_MIN_CONN,
                    'maxconn': Config.PG_MAX_CONN,
                    'host': Config.PG_HOST,
                    'port': Config.PG_PORT,
                    'user': Config.PG_USER,
                    'password': Config.PG_PASSWORD,
                    'dbname': Config.PG_DATABASE
                }
                if getattr(Config, 'PG_SSLMODE', None):
                    pool_kwargs['sslmode'] = Config.PG_SSLMODE
                _connection_pool = pool.ThreadedConnectionPool(**pool_kwargs)
            logger.info("PostgreSQL connection pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
            raise
    return _connection_pool

@contextmanager
def get_db_connection():
    p = get_connection_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        p.putconn(conn)

@contextmanager
def get_db_cursor(commit=False):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

def query_all(query, params=None):
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    except Exception as e:
        if 'does not exist' in str(e).lower() and not getattr(query_all, '_in_init', False):
            logger.info("Undefined table detected. Running init_db() to provision schema...")
            query_all._in_init = True
            try:
                init_db()
                with get_db_cursor(commit=False) as cur:
                    cur.execute(query, params or ())
                    return cur.fetchall()
            except Exception as retry_err:
                logger.error(f"Failed to auto-provision schema on query_all: {retry_err}")
            finally:
                query_all._in_init = False
        raise

def query_one(query, params=None):
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    except Exception as e:
        if 'does not exist' in str(e).lower() and not getattr(query_one, '_in_init', False):
            logger.info("Undefined table detected. Running init_db() to provision schema...")
            query_one._in_init = True
            try:
                init_db()
                with get_db_cursor(commit=False) as cur:
                    cur.execute(query, params or ())
                    return cur.fetchone()
            except Exception as retry_err:
                logger.error(f"Failed to auto-provision schema on query_one: {retry_err}")
            finally:
                query_one._in_init = False
        raise

def execute(query, params=None):
    with get_db_cursor(commit=True) as cur:
        cur.execute(query, params or ())
        return cur.rowcount

def execute_returning_id(query, params=None):
    with get_db_cursor(commit=True) as cur:
        cur.execute(query, params or ())
        row = cur.fetchone()
        return row['id'] if row else None

def get_next_sequence_val(seq_name):
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT nextval(%s) as val;", (seq_name,))
        return cur.fetchone()['val']

def init_db():
    schema_file = os.path.join(os.path.dirname(__file__), 'schema.sql')
    if not os.path.exists(schema_file):
        logger.warning(f"Schema file not found at {schema_file}, skipping automatic initialization.")
        return
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            
            # Resynchronize custom numbering sequences with current max IDs
            try:
                cur.execute(r"""
                    DO $$
                    DECLARE
                        m bigint;
                    BEGIN
                        SELECT GREATEST(COALESCE(MAX(id), 0), COALESCE(MAX(NULLIF(regexp_replace(order_number, '\D', '', 'g'), '')::bigint), 0)) INTO m FROM sales_orders;
                        IF m > 0 THEN PERFORM setval('so_number_seq', m, true); END IF;
                        
                        SELECT GREATEST(COALESCE(MAX(id), 0), COALESCE(MAX(NULLIF(regexp_replace(order_number, '\D', '', 'g'), '')::bigint), 0)) INTO m FROM purchase_orders;
                        IF m > 0 THEN PERFORM setval('po_number_seq', m, true); END IF;

                        SELECT COALESCE(MAX(id), 0) INTO m FROM stock_adjustments;
                        IF m > 0 THEN PERFORM setval('adj_number_seq', m, true); END IF;

                        SELECT COALESCE(MAX(id), 0) INTO m FROM stock_transfers;
                        IF m > 0 THEN PERFORM setval('trf_number_seq', m, true); END IF;
                    END $$;
                """)
            except Exception as seq_err:
                logger.warning(f"Sequence sync warning: {seq_err}")

            # Ensure essential initial seed records exist if table is fresh
            try:
                cur.execute("SELECT COUNT(*) FROM companies;")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO companies (name, currency_code, currency_symbol) VALUES ('inFlow Premium Wholesale', 'USD', '$');")

                cur.execute("SELECT COUNT(*) FROM locations;")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO locations (name, code, is_default) VALUES ('Central Warehouse', 'MAIN', TRUE);")

                cur.execute("SELECT COUNT(*) FROM branches;")
                if cur.fetchone()[0] == 0:
                    cur.execute("""
                        INSERT INTO branches (code, name, manager_name, phone, so_prefix, is_active)
                        VALUES ('HQ', 'Main Store HQ (កណ្តាល)', 'HQ Admin', '+855 23 888 999', 'SO-', TRUE),
                               ('TK', 'Toul Kork Branch (ទួលគោក)', 'Branch Manager', '+855 12 345 678', 'SO-TK-', TRUE)
                        ON CONFLICT DO NOTHING;
                    """)

                cur.execute("SELECT COUNT(*) FROM users;")
                if cur.fetchone()[0] == 0:
                    from werkzeug.security import generate_password_hash
                    pwd_hash = generate_password_hash('123')
                    cur.execute("""
                        INSERT INTO users (username, password_hash, display_name, email, role, is_active)
                        VALUES ('admin', %s, 'HQ Administrator', 'admin@inflow.com', 'main_admin', TRUE),
                               ('chenda', %s, 'Dok Chenda (HQ Admin)', 'chenda@inflow.com', 'main_admin', TRUE);
                    """, (pwd_hash, pwd_hash))
            except Exception as seed_err:
                logger.warning(f"Initial seed records notice: {seed_err}")

        conn.commit()
    logger.info("inFlow Premium PostgreSQL database schema initialized successfully.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialization completed successfully.")
