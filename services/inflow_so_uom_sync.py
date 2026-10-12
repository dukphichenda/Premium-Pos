import sys
import os
sys.path.insert(0, os.path.abspath('.'))
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import logging
try:
    import pyodbc
except ImportError:
    pyodbc = None
import psycopg2
from psycopg2.extras import execute_values
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.so_uom_sync')

def get_sqlserver_connection():
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed in this environment.")
    conn_str = (
        f"Driver={{SQL Server}};"
        f"Server={Config.SQLSERVER_HOST};"
        f"Database={Config.SQLSERVER_DB};"
        f"UID={Config.SQLSERVER_USER};"
        f"PWD={Config.SQLSERVER_PASSWORD};"
    )
    return pyodbc.connect(conn_str)

def get_pg_connection():
    return psycopg2.connect(
        host=Config.PG_HOST,
        port=Config.PG_PORT,
        user=Config.PG_USER,
        password=Config.PG_PASSWORD,
        dbname=Config.PG_DATABASE
    )

def normalize_uom(raw_uom, raw_qty, raw_qdisp, prod_uom, prod_souom_name):
    """
    Normalizes inFlow UOM to canonical clean representations:
    'cases', 'packs', 'ea.', 'pcs.'
    """
    uom_clean = (raw_uom or '').strip()
    if uom_clean:
        u_lower = uom_clean.lower()
        if u_lower in ('cases', 'កេស/cases', 'case', 'កេស'):
            return 'cases'
        elif u_lower in ('packs', 'pack', 'ដុំ', 'កញ្ចប់'):
            return 'packs'
        elif u_lower in ('ea.', 'ea'):
            return 'ea.'
        elif u_lower in ('pcs.', 'pcs', 'ដប', 'គ្រាប់', 'ចាន', 'ប្រអប់'):
            return 'pcs.'
        return uom_clean

    # If raw_uom is blank:
    # Check if quantity display differs from base quantity (means a pack/case ratio was applied)
    q = float(raw_qty or 0)
    qd = float(raw_qdisp or 0)
    if qd > 0 and abs(q - qd) > 0.0001 and prod_souom_name:
        souom_clean = prod_souom_name.strip().lower()
        if souom_clean in ('cases', 'កេស/cases', 'case', 'កេស'):
            return 'cases'
        elif souom_clean in ('packs', 'pack'):
            return 'packs'
        return prod_souom_name.strip()

    if prod_uom and prod_uom.strip():
        pu_clean = prod_uom.strip().lower()
        if pu_clean in ('cases', 'កេស/cases', 'case', 'កេស'):
            return 'cases'
        elif pu_clean in ('packs', 'pack'):
            return 'packs'
        elif pu_clean in ('ea.', 'ea'):
            return 'ea.'
        elif pu_clean in ('pcs.', 'pcs'):
            return 'pcs.'
        return prod_uom.strip()

    return 'pcs.'

def sync_sales_order_units():
    """
    Synchronizes authentic sales order line units of measure (UOM),
    quantity_display, standard base quantity, unit_price, discount, and subtotal
    from inFlow SQL Server (.\\INFLOWSQL) into PostgreSQL sales_order_lines.
    """
    logger.info("Connecting to inFlow SQL Server and PostgreSQL...")
    sql_conn = get_sqlserver_connection()
    sql_cur = sql_conn.cursor()

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor()

    # 1. Ensure compound index on sales_order_lines(sales_order_id, line_num)
    logger.info("Ensuring index on sales_order_lines(sales_order_id, line_num)...")
    pg_cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_sol_order_line 
        ON sales_order_lines (sales_order_id, line_num);
    """)
    pg_conn.commit()

    # 2. Fetch all lines from SQL Server
    logger.info("Fetching authentic SO lines from inFlow SQL Server...")
    sql_query = """
        SELECT 
            so.OrderNumber,
            sol.LineNum,
            sol.Quantity,
            sol.QuantityUom,
            sol.QuantityDisplay,
            sol.UnitPrice,
            sol.Discount,
            sol.SubTotal,
            sol.Description,
            p.Uom as ProductUom,
            p.SoUomName,
            p.SoUomRatioStd
        FROM SO_SalesOrder_Line sol
        JOIN SO_SalesOrder so ON sol.SalesOrderId = so.SalesOrderId
        LEFT JOIN BASE_Product p ON sol.ProdId = p.ProdId
        ORDER BY so.OrderNumber, sol.LineNum;
    """
    sql_cur.execute(sql_query)
    sql_rows = sql_cur.fetchall()
    total_sql_lines = len(sql_rows)
    logger.info(f"Loaded {total_sql_lines} lines from SQL Server.")

    # 3. Transform rows for bulk temporary staging
    transformed = []
    uom_counts = {}
    for r in sql_rows:
        order_num = (r[0] or '').strip()
        line_num = int(r[1])
        raw_qty = float(r[2]) if r[2] is not None else None
        raw_uom = r[3]
        raw_qdisp = float(r[4]) if r[4] is not None else None
        unit_price = float(r[5]) if r[5] is not None else 0.0
        discount = float(r[6]) if r[6] is not None else 0.0
        subtotal = float(r[7]) if r[7] is not None else 0.0
        prod_uom = r[9]
        prod_souom = r[10]

        norm_uom = normalize_uom(raw_uom, raw_qty, raw_qdisp, prod_uom, prod_souom)
        uom_counts[norm_uom] = uom_counts.get(norm_uom, 0) + 1

        final_qdisp = raw_qdisp if raw_qdisp is not None else (raw_qty if raw_qty is not None else 1.0)
        final_qty = raw_qty if raw_qty is not None else (raw_qdisp if raw_qdisp is not None else 1.0)

        transformed.append((
            order_num,
            line_num,
            norm_uom,
            final_qdisp,
            final_qty,
            unit_price,
            discount,
            subtotal
        ))

    logger.info("Normalized UOM breakdown across inFlow lines:")
    for u, cnt in sorted(uom_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {u}: {cnt} lines")

    # 4. Create temporary table in PostgreSQL
    logger.info("Creating temporary table in PostgreSQL for bulk update...")
    pg_cur.execute("""
        CREATE TEMP TABLE tmp_so_line_uom_sync (
            order_number VARCHAR(100),
            line_num INT,
            uom VARCHAR(50),
            quantity_display NUMERIC,
            quantity NUMERIC,
            unit_price NUMERIC,
            discount_percent NUMERIC,
            subtotal NUMERIC
        ) ON COMMIT DROP;
    """)

    # 5. Bulk insert in chunks of 5000
    chunk_size = 5000
    logger.info(f"Staging {len(transformed)} records into temp table...")
    for i in range(0, len(transformed), chunk_size):
        chunk = transformed[i:i + chunk_size]
        execute_values(pg_cur, """
            INSERT INTO tmp_so_line_uom_sync (
                order_number, line_num, uom, quantity_display, quantity,
                unit_price, discount_percent, subtotal
            ) VALUES %s;
        """, chunk)
    logger.info("Staging complete.")

    # 6. Execute bulk UPDATE via JOIN
    logger.info("Executing atomic bulk UPDATE on sales_order_lines...")
    update_sql = """
        UPDATE sales_order_lines sol
        SET uom = t.uom,
            quantity_display = t.quantity_display,
            quantity = t.quantity,
            unit_price = t.unit_price,
            discount_percent = t.discount_percent,
            subtotal = t.subtotal
        FROM tmp_so_line_uom_sync t
        JOIN sales_orders so ON t.order_number = so.order_number
        WHERE sol.sales_order_id = so.id 
          AND sol.line_num = t.line_num;
    """
    pg_cur.execute(update_sql)
    updated_rows = pg_cur.rowcount
    logger.info(f"Bulk UPDATE updated {updated_rows} rows in sales_order_lines.")

    pg_conn.commit()

    # 7. Verification in PostgreSQL
    logger.info("Verifying PostgreSQL sales_order_lines post-sync...")
    pg_cur.execute("""
        SELECT uom, COUNT(*), COUNT(quantity_display) 
        FROM sales_order_lines 
        GROUP BY uom 
        ORDER BY COUNT(*) DESC;
    """)
    post_stats = pg_cur.fetchall()
    logger.info("PostgreSQL sales_order_lines UOM distribution:")
    for r in post_stats:
        logger.info(f"  uom='{r[0]}': {r[1]} lines, quantity_display populated: {r[2]}")

    pg_cur.close()
    pg_conn.close()
    sql_cur.close()
    sql_conn.close()

    logger.info("Sales Order line UOM synchronization completed successfully!")
    return {
        'total_sql_lines': total_sql_lines,
        'updated_pg_lines': updated_rows,
        'uom_distribution': {r[0]: r[1] for r in post_stats}
    }

if __name__ == '__main__':
    sync_sales_order_units()
