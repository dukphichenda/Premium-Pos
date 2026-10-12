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
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=Config.PG_MIN_CONN,
                maxconn=Config.PG_MAX_CONN,
                host=Config.PG_HOST,
                port=Config.PG_PORT,
                user=Config.PG_USER,
                password=Config.PG_PASSWORD,
                dbname=Config.PG_DATABASE
            )
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
    with get_db_cursor(commit=False) as cur:
        cur.execute(query, params or ())
        return cur.fetchall()

def query_one(query, params=None):
    with get_db_cursor(commit=False) as cur:
        cur.execute(query, params or ())
        return cur.fetchone()

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
        raise FileNotFoundError(f"Schema file not found at {schema_file}")
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            
            # Resynchronize custom numbering sequences with current max IDs
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
        conn.commit()
    logger.info("inFlow Premium PostgreSQL database schema initialized successfully.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialization completed successfully.")
