import sys
import os
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.abspath('.'))
import logging
import pyodbc
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.update_names')

def update_product_names_from_inflow():
    logger.info("Connecting to inFlow Inventory SQL Server (.\\INFLOWSQL)...")
    mssql_conn = pyodbc.connect('Driver={SQL Server};Server=.\\INFLOWSQL;Database=inFlow;UID=sa;PWD=hbsr5Fe#6w;')
    m_cur = mssql_conn.cursor()
    m_cur.execute("""
        SELECT ProdId, Name
        FROM BASE_Product
        WHERE Name IS NOT NULL AND LTRIM(RTRIM(Name)) <> ''
        ORDER BY ProdId
    """)
    inflow_products = {row[0]: row[1].strip() for row in m_cur.fetchall()}
    mssql_conn.close()
    logger.info(f"Loaded {len(inflow_products)} products from inFlow Inventory.")

    logger.info("Connecting to inFlow Premium PostgreSQL database...")
    pg_conn = psycopg2.connect(
        host=Config.PG_HOST,
        port=Config.PG_PORT,
        user=Config.PG_USER,
        password=Config.PG_PASSWORD,
        dbname=Config.PG_DATABASE
    )
    pg_cur = pg_conn.cursor(cursor_factory=RealDictCursor)
    
    pg_cur.execute("SELECT id, name, sku FROM products ORDER BY id")
    pg_products = {row['id']: row for row in pg_cur.fetchall()}
    logger.info(f"Loaded {len(pg_products)} products from PostgreSQL.")

    updated_count = 0
    already_matched = 0
    updated_samples = []

    for pid, inflow_name in inflow_products.items():
        if pid in pg_products:
            current_pg = pg_products[pid]
            current_pg_name = (current_pg['name'] or '').strip()
            
            if current_pg_name != inflow_name:
                pg_cur.execute("""
                    UPDATE products
                    SET name = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (inflow_name, pid))
                
                updated_count += 1
                if len(updated_samples) < 20:
                    updated_samples.append({
                        'id': pid,
                        'sku': current_pg['sku'],
                        'old_name': current_pg_name,
                        'new_name': inflow_name
                    })
            else:
                already_matched += 1

    pg_conn.commit()
    pg_conn.close()

    logger.info("=" * 70)
    logger.info("PRODUCT NAME SYNCHRONIZATION RESULTS")
    logger.info("=" * 70)
    logger.info(f"Total products in PostgreSQL     : {len(pg_products)}")
    logger.info(f"Total products in inFlow Inventory: {len(inflow_products)}")
    logger.info(f"Products updated to exact name   : {updated_count}")
    logger.info(f"Products already exact match     : {already_matched}")
    logger.info("=" * 70)

    if updated_samples:
        print("\n=== Sample Updated Products (Before vs After) ===")
        for s in updated_samples:
            print(f"ID {s['id']:3d} | SKU: {s['sku']}")
            print(f"   BEFORE : {s['old_name']}")
            print(f"   AFTER  : {s['new_name']}\n")

    return updated_count

if __name__ == '__main__':
    update_product_names_from_inflow()
