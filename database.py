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
            if params is None:
                cur.execute(query)
            else:
                cur.execute(query, params)
            return cur.fetchall()
    except Exception as e:
        if 'does not exist' in str(e).lower() and not getattr(query_all, '_in_init', False):
            logger.info("Undefined table detected. Running init_db() to provision schema...")
            query_all._in_init = True
            try:
                init_db()
                with get_db_cursor(commit=False) as cur:
                    if params is None:
                        cur.execute(query)
                    else:
                        cur.execute(query, params)
                    return cur.fetchall()
            except Exception as retry_err:
                logger.error(f"Failed to auto-provision schema on query_all: {retry_err}")
            finally:
                query_all._in_init = False
        raise

def query_one(query, params=None):
    try:
        with get_db_cursor(commit=False) as cur:
            if params is None:
                cur.execute(query)
            else:
                cur.execute(query, params)
            return cur.fetchone()
    except Exception as e:
        if 'does not exist' in str(e).lower() and not getattr(query_one, '_in_init', False):
            logger.info("Undefined table detected. Running init_db() to provision schema...")
            query_one._in_init = True
            try:
                init_db()
                with get_db_cursor(commit=False) as cur:
                    if params is None:
                        cur.execute(query)
                    else:
                        cur.execute(query, params)
                    return cur.fetchone()
            except Exception as retry_err:
                logger.error(f"Failed to auto-provision schema on query_one: {retry_err}")
            finally:
                query_one._in_init = False
        raise

def execute(query, params=None):
    with get_db_cursor(commit=True) as cur:
        if params is None:
            cur.execute(query)
        else:
            cur.execute(query, params)
        return cur.rowcount

def execute_returning_id(query, params=None):
    with get_db_cursor(commit=True) as cur:
        if params is None:
            cur.execute(query)
        else:
            cur.execute(query, params)
        row = cur.fetchone()
        return row['id'] if row else None

def get_next_sequence_val(seq_name):
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT nextval(%s) as val;", (seq_name,))
        return cur.fetchone()['val']

def _row_val(row, key, idx=0):
    if not row:
        return None
    if isinstance(row, dict) or hasattr(row, 'get'):
        val = row.get(key)
        if val is not None:
            return val
    try:
        return row[idx]
    except (IndexError, KeyError, TypeError):
        return None

def _ensure_sequence_exists(c, seq_name):
    try:
        c.execute("SELECT 1 FROM pg_sequences WHERE sequencename = %s;", (seq_name,))
        if not c.fetchone():
            c.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1;")
    except Exception:
        pass

def get_next_order_number(order_type='SO', branch_id=None, cur=None):
    """
    Auto-generates the next sequential order number (SO or PO) strictly derived from
    the LAST / highest existing order number in the database, with automatic PostgreSQL
    sequence synchronization and collision prevention.
    """
    import re

    def _generate(c):
        if order_type.upper() == 'SO':
            table = 'sales_orders'
            if branch_id:
                c.execute("SELECT code, so_prefix FROM branches WHERE id = %s;", (branch_id,))
                branch = c.fetchone()
                if branch:
                    b_code = _row_val(branch, 'code', 0)
                    b_prefix = _row_val(branch, 'so_prefix', 1)
                    prefix = (b_prefix or f"SO-{b_code}-").strip().upper()
                    if not prefix.endswith('-'):
                        prefix += '-'
                    seq_name = f"so_branch_{branch_id}_seq"
                    pad_len = 5
                else:
                    prefix = 'SO-'
                    seq_name = 'so_number_seq'
                    pad_len = 6
            else:
                prefix = 'SO-'
                seq_name = 'so_number_seq'
                pad_len = 6
        elif order_type.upper() == 'PO':
            table = 'purchase_orders'
            prefix = 'PO-'
            seq_name = 'po_number_seq'
            pad_len = 6
        else:
            raise ValueError(f"Unsupported order_type: {order_type}")

        # 1. Ensure the sequence exists
        _ensure_sequence_exists(c, seq_name)

        # 2. Find the highest existing sequence number in the database matching this prefix
        pattern = r'^' + re.escape(prefix) + r'([0-9]+)$'
        c.execute(f"""
            SELECT MAX(SUBSTRING(order_number FROM %s)::bigint) as max_val
            FROM {table}
            WHERE order_number ~ %s;
        """, (pattern, pattern))
        row = c.fetchone()
        max_existing = _row_val(row, 'max_val', 0) or 0

        # 3. Synchronize the PostgreSQL sequence if it is behind the existing orders
        c.execute(f"SELECT last_value, is_called FROM {seq_name};")
        srow = c.fetchone()
        current_seq_val = _row_val(srow, 'last_value', 0) or 0
        if max_existing > 0 and current_seq_val < max_existing:
            c.execute(f"SELECT setval('{seq_name}', %s, true);", (max_existing,))

        # 4. Advance sequence atomically
        c.execute(f"SELECT nextval('{seq_name}') as val;")
        next_val = _row_val(c.fetchone(), 'val', 0)

        if next_val <= max_existing:
            next_val = max_existing + 1
            c.execute(f"SELECT setval('{seq_name}', %s, true);", (next_val,))

        # 5. Ensure uniqueness against historical or manual entries
        while True:
            candidate = f"{prefix}{next_val:0{pad_len}d}"
            c.execute(f"SELECT 1 FROM {table} WHERE order_number = %s LIMIT 1;", (candidate,))
            if not c.fetchone():
                break
            next_val += 1
            c.execute(f"SELECT setval('{seq_name}', %s, true);", (next_val,))

        return f"{prefix}{next_val:0{pad_len}d}"

    if cur is not None:
        return _generate(cur)
    else:
        with get_db_cursor(commit=True) as c:
            return _generate(c)

def preview_order_number(order_type='SO', branch_id=None, cur=None):
    """
    Previews what the next auto-generated order number will be without consuming
    or incrementing sequence numbers.
    """
    import re

    def _preview(c):
        if order_type.upper() == 'SO':
            table = 'sales_orders'
            if branch_id:
                c.execute("SELECT code, so_prefix FROM branches WHERE id = %s;", (branch_id,))
                branch = c.fetchone()
                if branch:
                    b_code = _row_val(branch, 'code', 0)
                    b_prefix = _row_val(branch, 'so_prefix', 1)
                    prefix = (b_prefix or f"SO-{b_code}-").strip().upper()
                    if not prefix.endswith('-'):
                        prefix += '-'
                    seq_name = f"so_branch_{branch_id}_seq"
                    pad_len = 5
                else:
                    prefix = 'SO-'
                    seq_name = 'so_number_seq'
                    pad_len = 6
            else:
                prefix = 'SO-'
                seq_name = 'so_number_seq'
                pad_len = 6
        elif order_type.upper() == 'PO':
            table = 'purchase_orders'
            prefix = 'PO-'
            seq_name = 'po_number_seq'
            pad_len = 6
        else:
            return ''

        pattern = r'^' + re.escape(prefix) + r'([0-9]+)$'
        try:
            c.execute(f"""
                SELECT MAX(SUBSTRING(order_number FROM %s)::bigint) as max_val
                FROM {table}
                WHERE order_number ~ %s;
            """, (pattern, pattern))
            row = c.fetchone()
            max_existing = _row_val(row, 'max_val', 0) or 0
        except Exception:
            max_existing = 0

        seq_next = 1
        try:
            c.execute(f"SELECT last_value, is_called FROM {seq_name};")
            srow = c.fetchone()
            if srow:
                s_last = _row_val(srow, 'last_value', 0) or 0
                s_called = _row_val(srow, 'is_called', 1)
                seq_next = s_last + (1 if s_called else 0)
        except Exception:
            pass

        next_val = max(max_existing + 1, seq_next)
        return f"{prefix}{next_val:0{pad_len}d}"

    if cur is not None:
        return _preview(cur)
    else:
        with get_db_cursor(commit=False) as c:
            return _preview(c)

def resync_all_sequences(cur=None):
    """
    Resynchronizes all PostgreSQL sequence generators with the current maximum
    values in sales_orders, purchase_orders, stock_adjustments, stock_transfers, and branches.
    """
    import re

    def _resync(c):
        # 1. Main store SO sequence
        _ensure_sequence_exists(c, 'so_number_seq')
        c.execute(r"SELECT MAX(SUBSTRING(order_number FROM '^SO-([0-9]+)$')::bigint) as m FROM sales_orders WHERE order_number ~ '^SO-[0-9]+$';")
        m_row = c.fetchone()
        m_so = _row_val(m_row, 'm', 0) or 0
        if m_so > 0:
            c.execute("SELECT setval('so_number_seq', %s, true);", (m_so,))

        # 2. Purchase orders sequence
        _ensure_sequence_exists(c, 'po_number_seq')
        c.execute(r"SELECT MAX(SUBSTRING(order_number FROM '^PO-([0-9]+)$')::bigint) as m FROM purchase_orders WHERE order_number ~ '^PO-[0-9]+$';")
        p_row = c.fetchone()
        m_po = _row_val(p_row, 'm', 0) or 0
        if m_po > 0:
            c.execute("SELECT setval('po_number_seq', %s, true);", (m_po,))

        # 3. Branch SO sequences
        try:
            c.execute("SELECT id, code, so_prefix FROM branches WHERE is_active = TRUE;")
            branches = c.fetchall()
            for b in branches:
                b_id = _row_val(b, 'id', 0)
                b_code = _row_val(b, 'code', 1)
                b_prefix = _row_val(b, 'so_prefix', 2)
                prefix = (b_prefix or f"SO-{b_code}-").strip().upper()
                if not prefix.endswith('-'):
                    prefix += '-'
                seq_name = f"so_branch_{b_id}_seq"
                _ensure_sequence_exists(c, seq_name)
                pattern = r'^' + re.escape(prefix) + r'([0-9]+)$'
                c.execute(f"""
                    SELECT MAX(SUBSTRING(order_number FROM %s)::bigint) as m
                    FROM sales_orders
                    WHERE order_number ~ %s OR branch_id = %s;
                """, (pattern, pattern, b_id))
                b_row = c.fetchone()
                m_b = _row_val(b_row, 'm', 0) or 0
                if m_b > 0:
                    c.execute(f"SELECT setval('{seq_name}', %s, true);", (m_b,))
        except Exception as b_err:
            logger.warning(f"Branch sequence resync warning: {b_err}")

        # 4. Stock adjustments & transfers
        try:
            _ensure_sequence_exists(c, 'adj_number_seq')
            c.execute("SELECT COALESCE(MAX(id), 0) as m FROM stock_adjustments;")
            m_adj = _row_val(c.fetchone(), 'm', 0) or 0
            if m_adj > 0:
                c.execute("SELECT setval('adj_number_seq', %s, true);", (m_adj,))

            _ensure_sequence_exists(c, 'trf_number_seq')
            c.execute("SELECT COALESCE(MAX(id), 0) as m FROM stock_transfers;")
            m_trf = _row_val(c.fetchone(), 'm', 0) or 0
            if m_trf > 0:
                c.execute("SELECT setval('trf_number_seq', %s, true);", (m_trf,))
        except Exception:
            pass

    if cur is not None:
        _resync(cur)
    else:
        with get_db_cursor(commit=True) as c:
            _resync(c)

def init_db():
    schema_file = os.path.join(os.path.dirname(__file__), 'schema.sql')
    if not os.path.exists(schema_file):
        logger.warning(f"Schema file not found at {schema_file}, skipping automatic initialization.")
        return
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(schema_sql)
            
            # Resynchronize custom numbering sequences with current max IDs
            try:
                resync_all_sequences(cur=cur)
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
