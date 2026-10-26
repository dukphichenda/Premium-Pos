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

def close_connection_pool():
    global _connection_pool
    if _connection_pool is not None:
        try:
            _connection_pool.closeall()
            logger.info("PostgreSQL connection pool closed.")
        except Exception as e:
            logger.warning(f"Warning while closing PostgreSQL connection pool: {e}")
        finally:
            _connection_pool = None

def reset_connection_pool():
    close_connection_pool()
    return get_connection_pool()

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
        elif order_type.upper() in ('POS', 'SO_POS'):
            table = 'sales_orders'
            if branch_id:
                c.execute("SELECT code, so_prefix FROM branches WHERE id = %s;", (branch_id,))
                branch = c.fetchone()
                if branch:
                    b_code = (_row_val(branch, 'code', 0) or 'STM').strip().upper()
                    prefix = f"SO-{b_code}-P-"
                    seq_name = f"pos_branch_{branch_id}_seq"
                    pad_len = 5
                else:
                    prefix = 'SO-STM-P-'
                    seq_name = 'pos_branch_1_seq'
                    pad_len = 5
            else:
                prefix = 'SO-STM-P-'
                seq_name = 'pos_branch_1_seq'
                pad_len = 5
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

        # 3. Synchronize the PostgreSQL sequence
        if max_existing > 0:
            c.execute(f"SELECT last_value, is_called FROM {seq_name};")
            srow = c.fetchone()
            current_seq_val = _row_val(srow, 'last_value', 0) or 0
            if current_seq_val < max_existing:
                c.execute(f"SELECT setval('{seq_name}', %s, true);", (max_existing,))

            # 4. Advance sequence atomically
            c.execute(f"SELECT nextval('{seq_name}') as val;")
            next_val = _row_val(c.fetchone(), 'val', 0)

            if next_val <= max_existing:
                next_val = max_existing + 1
                c.execute(f"SELECT setval('{seq_name}', %s, true);", (next_val,))
        else:
            # When a branch or scope has NO bills/orders yet, start strictly from 1
            c.execute(f"SELECT last_value, is_called FROM {seq_name};")
            srow = c.fetchone()
            current_seq_val = _row_val(srow, 'last_value', 0) or 0
            is_called = _row_val(srow, 'is_called', 1)
            if current_seq_val > 1 or is_called:
                c.execute(f"SELECT setval('{seq_name}', 1, false);")
            c.execute(f"SELECT nextval('{seq_name}') as val;")
            next_val = _row_val(c.fetchone(), 'val', 0)

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
        elif order_type.upper() in ('POS', 'SO_POS'):
            table = 'sales_orders'
            if branch_id:
                c.execute("SELECT code, so_prefix FROM branches WHERE id = %s;", (branch_id,))
                branch = c.fetchone()
                if branch:
                    b_code = (_row_val(branch, 'code', 0) or 'STM').strip().upper()
                    prefix = f"SO-{b_code}-P-"
                    seq_name = f"pos_branch_{branch_id}_seq"
                    pad_len = 5
                else:
                    prefix = 'SO-STM-P-'
                    seq_name = 'pos_branch_1_seq'
                    pad_len = 5
            else:
                prefix = 'SO-STM-P-'
                seq_name = 'pos_branch_1_seq'
                pad_len = 5
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

        if max_existing == 0:
            next_val = 1
        else:
            seq_next = max_existing + 1
            try:
                c.execute(f"SELECT last_value, is_called FROM {seq_name};")
                srow = c.fetchone()
                if srow:
                    s_last = _row_val(srow, 'last_value', 0) or 0
                    s_called = _row_val(srow, 'is_called', 1)
                    c_next = s_last + (1 if s_called else 0)
                    seq_next = max(max_existing + 1, c_next)
            except Exception:
                pass
            next_val = seq_next

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
                    WHERE order_number ~ %s;
                """, (pattern, pattern))
                b_row = c.fetchone()
                m_b = _row_val(b_row, 'm', 0) or 0
                if m_b > 0:
                    c.execute(f"SELECT setval('{seq_name}', %s, true);", (m_b,))
                else:
                    c.execute(f"SELECT setval('{seq_name}', 1, false);")
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

            # 5. Customers sequence
            _ensure_sequence_exists(c, 'customers_id_seq')
            c.execute("SELECT COALESCE(MAX(id), 0) as m FROM customers;")
            m_cust = _row_val(c.fetchone(), 'm', 0) or 0
            if m_cust > 0:
                c.execute("SELECT setval('customers_id_seq', %s, true);", (m_cust,))
        except Exception:
            pass

    if cur is not None:
        _resync(cur)
    else:
        with get_db_cursor(commit=True) as c:
            _resync(c)

def check_duplicate_customer_name(name, exclude_id=None, cur=None):
    """
    Checks if a customer with the given name already exists (active customers only).
    Handles both English and Khmer (case-insensitive, trims, collapsed whitespace,
    zero-width space stripping, and Unicode NFC normalization).
    Returns the existing customer record (dict/row) if duplicated, or None.
    """
    if not name or not str(name).strip():
        return None
    import unicodedata, re

    clean_name = unicodedata.normalize('NFC', str(name).strip().replace('\u200b', ''))
    norm_name = ' '.join(clean_name.split())
    no_space_name = clean_name.replace(' ', '').lower()
    has_khmer = bool(re.search(r'[\u1780-\u17FF]', clean_name))

    sql = """
        SELECT id, name, phone, contact_name, branch_id
        FROM customers
        WHERE is_active = TRUE
          AND (
              LOWER(TRIM(name)) = LOWER(TRIM(%s))
              OR REGEXP_REPLACE(REPLACE(LOWER(TRIM(name)), chr(8203), ''), '\\s+', ' ', 'g') = LOWER(%s)
              OR (%s = TRUE AND REPLACE(REPLACE(LOWER(TRIM(name)), chr(8203), ''), ' ', '') = %s)
          )
          AND (%s IS NULL OR id != %s)
        LIMIT 1;
    """
    params = (clean_name, norm_name, has_khmer, no_space_name, exclude_id, exclude_id)

    if cur is not None:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        if hasattr(row, 'keys'):
            return dict(row)
        return {'id': row[0], 'name': row[1], 'phone': row[2], 'contact_name': row[3], 'branch_id': row[4]}
    else:
        row = query_one(sql, params)
        return dict(row) if row else None

def sync_customers_from_latest_orders(cur=None, customer_ids=None):
    """
    Synchronizes customer profile information (phone, address, contact name, city)
    from their latest sales order bill while preserving the customer name and order-level data.
    """
    def _sync(c):
        where_clause = "WHERE customer_id IS NOT NULL"
        params = []
        if customer_ids is not None:
            clean_ids = [int(cid) for cid in customer_ids if cid]
            if not clean_ids:
                return 0
            where_clause += " AND customer_id = ANY(%s)"
            params.append(clean_ids)

        sql = f"""
            UPDATE customers c
            SET phone = CASE WHEN COALESCE(NULLIF(latest_info.phone, ''), '') != '' THEN latest_info.phone ELSE c.phone END,
                address1 = CASE WHEN COALESCE(NULLIF(latest_info.address, ''), '') != '' THEN latest_info.address ELSE c.address1 END,
                shipping_address = CASE WHEN COALESCE(NULLIF(latest_info.address, ''), '') != '' THEN latest_info.address ELSE c.shipping_address END,
                billing_address = CASE WHEN COALESCE(NULLIF(latest_info.address, ''), '') != '' THEN latest_info.address ELSE c.billing_address END,
                contact_name = CASE WHEN COALESCE(NULLIF(latest_info.contact, ''), '') != '' THEN latest_info.contact ELSE c.contact_name END,
                city = CASE WHEN COALESCE(NULLIF(latest_info.province, ''), '') != '' THEN latest_info.province ELSE c.city END,
                updated_at = CURRENT_TIMESTAMP
            FROM (
                SELECT 
                    customer_id,
                    (ARRAY_AGG(customer_phone ORDER BY order_date DESC, id DESC) FILTER (WHERE customer_phone IS NOT NULL AND trim(customer_phone) != ''))[1] as phone,
                    (ARRAY_AGG(customer_address ORDER BY order_date DESC, id DESC) FILTER (WHERE customer_address IS NOT NULL AND trim(customer_address) != ''))[1] as address,
                    (ARRAY_AGG(customer_contact ORDER BY order_date DESC, id DESC) FILTER (WHERE customer_contact IS NOT NULL AND trim(customer_contact) != ''))[1] as contact,
                    (ARRAY_AGG(destination_province ORDER BY order_date DESC, id DESC) FILTER (WHERE destination_province IS NOT NULL AND trim(destination_province) != ''))[1] as province
                FROM sales_orders
                {where_clause}
                GROUP BY customer_id
            ) latest_info
            WHERE c.id = latest_info.customer_id;
        """
        c.execute(sql, tuple(params))
        return getattr(c, 'rowcount', 0) or 0

    if cur is not None:
        return _sync(cur)
    else:
        with get_db_cursor(commit=True) as c:
            return _sync(c)

def sync_inventory_reserved_quantities(cur=None, product_ids=None):
    """
    Recalculates and synchronizes inventory.reserved_quantity to accurately match
    active, unfulfilled sales orders (including kit BOM components and add-on products).
    Unfulfilled orders are:
    status NOT IN ('PAID', 'SHIPPED', 'CANCELLED', 'INVOICED') AND (payment_status IS NULL OR payment_status != 'PAID').
    """
    def _sync(c):
        p_filter = ""
        params = []
        if product_ids is not None:
            clean_ids = [int(pid) for pid in product_ids if pid]
            if not clean_ids:
                return 0
            p_filter = "AND (sol.product_id = ANY(%s) OR sol.addon_product_id = ANY(%s) OR EXISTS (SELECT 1 FROM product_boms pb_sub WHERE pb_sub.product_id = sol.product_id AND pb_sub.component_product_id = ANY(%s)))"
            params = [clean_ids, clean_ids, clean_ids]
            c.execute("UPDATE inventory SET reserved_quantity = 0 WHERE product_id = ANY(%s) AND reserved_quantity != 0;", (clean_ids,))
        else:
            c.execute("UPDATE inventory SET reserved_quantity = 0 WHERE reserved_quantity != 0;")

        sync_sql = f"""
            WITH open_so_lines AS (
                SELECT sol.product_id, sol.addon_product_id, sol.quantity, COALESCE(sol.addon_quantity, 1.0) as addon_qty,
                       COALESCE(
                           CASE WHEN so.location_id IN (SELECT id FROM locations WHERE name LIKE '<%%>') THEN NULL ELSE so.location_id END,
                           (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)
                       ) as loc_id
                FROM sales_order_lines sol
                JOIN sales_orders so ON sol.sales_order_id = so.id
                WHERE so.status NOT IN ('PAID', 'SHIPPED', 'CANCELLED', 'INVOICED')
                  AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
                  {p_filter}
            ),
            all_res AS (
                -- 1. Direct products on sales order lines
                SELECT product_id, loc_id, quantity as res_qty FROM open_so_lines
                UNION ALL
                -- 2. Add-on products on sales order lines
                SELECT addon_product_id as product_id, loc_id, (quantity * addon_qty) as res_qty 
                FROM open_so_lines WHERE addon_product_id IS NOT NULL
                UNION ALL
                -- 3. Kit BOM components
                SELECT pb.component_product_id as product_id, l.loc_id, (l.quantity * pb.quantity) as res_qty
                FROM open_so_lines l
                JOIN product_boms pb ON l.product_id = pb.product_id
            ),
            loc_res AS (
                SELECT product_id, loc_id, SUM(res_qty) as total_res
                FROM all_res
                WHERE product_id IS NOT NULL
                GROUP BY product_id, loc_id
            )
            UPDATE inventory i
            SET reserved_quantity = lr.total_res,
                updated_at = CURRENT_TIMESTAMP
            FROM loc_res lr
            WHERE i.id = (
                SELECT id FROM inventory
                WHERE product_id = lr.product_id AND location_id = lr.loc_id
                ORDER BY (sublocation = '') DESC, id ASC
                LIMIT 1
            );

            WITH open_so_lines AS (
                SELECT sol.product_id, sol.addon_product_id, sol.quantity, COALESCE(sol.addon_quantity, 1.0) as addon_qty,
                       COALESCE(
                           CASE WHEN so.location_id IN (SELECT id FROM locations WHERE name LIKE '<%%>') THEN NULL ELSE so.location_id END,
                           (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)
                       ) as loc_id
                FROM sales_order_lines sol
                JOIN sales_orders so ON sol.sales_order_id = so.id
                WHERE so.status NOT IN ('PAID', 'SHIPPED', 'CANCELLED', 'INVOICED')
                  AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
                  {p_filter}
            ),
            all_res AS (
                SELECT product_id, loc_id, quantity as res_qty FROM open_so_lines
                UNION ALL
                SELECT addon_product_id as product_id, loc_id, (quantity * addon_qty) as res_qty 
                FROM open_so_lines WHERE addon_product_id IS NOT NULL
                UNION ALL
                SELECT pb.component_product_id as product_id, l.loc_id, (l.quantity * pb.quantity) as res_qty
                FROM open_so_lines l
                JOIN product_boms pb ON l.product_id = pb.product_id
            ),
            loc_res AS (
                SELECT product_id, loc_id, SUM(res_qty) as total_res
                FROM all_res
                WHERE product_id IS NOT NULL
                GROUP BY product_id, loc_id
            )
            INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
            SELECT lr.product_id, lr.loc_id, '', 0, lr.total_res
            FROM loc_res lr
            WHERE NOT EXISTS (
                SELECT 1 FROM inventory WHERE product_id = lr.product_id AND location_id = lr.loc_id
            );
        """
        c.execute(sync_sql, tuple(params) if params else None)
        return getattr(c, 'rowcount', 0) or 0

    if cur is not None:
        return _sync(cur)
    else:
        with get_db_cursor(commit=True) as c:
            return _sync(c)

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
            
            # Ensure essential columns exist in customers
            try:
                cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS remarks TEXT;")
                cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS fax VARCHAR(100);")
                cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS website VARCHAR(255);")
                cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_number VARCHAR(100);")
                cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS branch_id INTEGER;")
                cur.execute("ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS submission_token VARCHAR(64);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_orders_sub_token ON sales_orders(submission_token);")
                cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS price_card_unit VARCHAR(50) DEFAULT 'ប្រអប់';")
                cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS price_card_custom_detail TEXT DEFAULT NULL;")
                cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS price_card_is_custom_detail BOOLEAN DEFAULT FALSE;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS purchase_order_attachments (
                        id SERIAL PRIMARY KEY,
                        purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                        file_name VARCHAR(255) NOT NULL,
                        file_path TEXT NOT NULL,
                        file_size BIGINT DEFAULT 0,
                        file_type VARCHAR(100),
                        caption TEXT,
                        uploaded_by VARCHAR(150),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_po_attachments_order_id ON purchase_order_attachments(purchase_order_id);
                """)
                cur.execute("ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS seller_signature_url TEXT;")
                cur.execute("ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS seller_name VARCHAR(150);")
                cur.execute("ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS gemini_api_key TEXT;")
                cur.execute("ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS unit_price_decimals INTEGER DEFAULT 2;")
                cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS gemini_api_key TEXT;")
                cur.execute("ALTER TABLE stock_adjustments ADD COLUMN IF NOT EXISTS custom_fields_json TEXT;")
                cur.execute("ALTER TABLE stock_adjustments ADD COLUMN IF NOT EXISTS created_by VARCHAR(100);")
                cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS recorded_by VARCHAR(100);")
                cur.execute("UPDATE expenses SET recorded_by = COALESCE(NULLIF(TRIM(paid_by), ''), 'admin') WHERE recorded_by IS NULL OR recorded_by = '';")
                cur.execute("ALTER TABLE stock_adjustment_lines ADD COLUMN IF NOT EXISTS sublocation VARCHAR(100) DEFAULT '';")
                cur.execute("ALTER TABLE products ALTER COLUMN tier_qty_1 DROP DEFAULT;")
                cur.execute("ALTER TABLE products ALTER COLUMN tier_qty_2 DROP DEFAULT;")
                cur.execute("ALTER TABLE products ALTER COLUMN tier_qty_3 DROP DEFAULT;")
                cur.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS price_table_style VARCHAR(20) DEFAULT 'classic';")
                cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS price_card_style VARCHAR(20) DEFAULT NULL;")
                cur.execute("""
                    INSERT INTO app_settings (setting_key, setting_value, description, updated_at)
                    VALUES ('default_price_table_style', 'classic', 'Default style for product price cards (classic or modern)', CURRENT_TIMESTAMP)
                    ON CONFLICT (setting_key) DO NOTHING;
                """)
            except Exception as mig_err:
                logger.warning(f"Customer/Invoice/Adjustment columns migration notice: {mig_err}")

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

            try:
                sync_customers_from_latest_orders(cur=cur)
            except Exception as sync_err:
                logger.warning(f"Customer latest bill sync notice: {sync_err}")

            try:
                sync_inventory_reserved_quantities(cur=cur)
            except Exception as inv_err:
                logger.warning(f"Inventory reserved quantities sync notice: {inv_err}")

        conn.commit()
    logger.info("inFlow Premium PostgreSQL database schema initialized successfully.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialization completed successfully.")
