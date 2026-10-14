import sys
import os
import re
import logging
from collections import Counter
from decimal import Decimal

# Ensure utf-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pyodbc
import psycopg2
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.update_uoms')

def get_sqlserver_connection():
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

def extract_sku_and_name(pid, orig_name):
    orig_name = (orig_name or '').strip()
    khmer_match = re.search(r'[\u1780-\u17FF]', orig_name)
    if khmer_match and khmer_match.start() > 0:
        prefix = orig_name[:khmer_match.start()].strip().rstrip(' -_:/')
        rem = orig_name[khmer_match.start():].strip()
        if prefix and re.search(r'[A-Za-z]', prefix):
            return prefix, rem
    return f"SKU-{pid:04d}", orig_name

def determine_uoms(row):
    pid, orig_name, base_uom, so_uom, so_ratio_std, so_ratio, po_uom, po_ratio_std, po_ratio, m_pack = row
    orig_name = (orig_name or '').strip()

    u_sales = (so_uom or '').strip()
    r_sales_std = float(so_ratio_std) if so_ratio_std is not None else 1.0
    r_sales = float(so_ratio) if so_ratio is not None else 1.0

    # If inFlow ratio is <= 1, check product name for pack ratio
    if r_sales_std <= 1.0:
        name_pack_match = re.search(r'(\d+)\s*(?:ចាន|ប្រអប់|កែវ|ដប|គ្រាប់|ថង់|កំប៉ុង|សន្លឹក|pcs|ដុំ|គូរ)?\s*[/／]\s*(កេស|Case|Pack|ដុំ|បេ)', orig_name, re.IGNORECASE)
        if name_pack_match:
            extracted_num = float(name_pack_match.group(1))
            pack_type = name_pack_match.group(2).lower()
            if extracted_num > 1.0:
                r_sales_std = extracted_num
                if not u_sales:
                    if pack_type in ('pack', 'ដុំ'):
                        u_sales = 'packs'
                    else:
                        u_sales = 'cases'
        elif m_pack and float(m_pack) > 1.0:
            r_sales_std = float(m_pack)
            if not u_sales:
                u_sales = 'cases'

    if not u_sales:
        u_sales = 'cases' if r_sales_std > 1.0 else (base_uom or 'pcs.')

    # Purchasing UOM is made identical to Sales UOM
    u_purch = u_sales
    r_purch = r_sales
    r_purch_std = r_sales_std

    return u_sales, r_sales, r_sales_std, u_purch, r_purch, r_purch_std

def update_products():
    logger.info("Connecting to inFlow SQL Server and PostgreSQL...")
    mssql_conn = get_sqlserver_connection()
    mssql_cur = mssql_conn.cursor()

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor()

    try:
        mssql_cur.execute("""
            SELECT ProdId, Name, Uom, SoUomName, SoUomRatioStd, SoUomRatio, PoUomName, PoUomRatioStd, PoUomRatio, MasterPackQty
            FROM BASE_Product
            ORDER BY ProdId
        """)
        rows = mssql_cur.fetchall()
        logger.info(f"Fetched {len(rows)} products from inFlow SQL Server.")

        # Process SKUs, Names, and UOMs
        transformed = []
        sku_counter = Counter()

        for r in rows:
            pid = r[0]
            orig_name = r[1]
            sku, clean_name = extract_sku_and_name(pid, orig_name)
            u_sales, r_sales, r_sales_std, u_purch, r_purch, r_purch_std = determine_uoms(r)
            transformed.append({
                'pid': pid,
                'raw_sku': sku,
                'clean_name': clean_name,
                'orig_name': orig_name,
                'sales_uom': u_sales,
                'sales_uom_ratio': r_sales,
                'sales_uom_ratio_std': r_sales_std,
                'purchasing_uom': u_purch,
                'purchasing_uom_ratio': r_purch,
                'purchasing_uom_ratio_std': r_purch_std
            })

        # Ensure SKU uniqueness
        for item in transformed:
            raw = item['raw_sku']
            sku_counter[raw] += 1
            if sku_counter[raw] > 1:
                item['final_sku'] = f"{raw}-{sku_counter[raw]}"
            else:
                item['final_sku'] = raw

        logger.info("Updating products in PostgreSQL...")
        for item in transformed:
            pg_cur.execute("""
                UPDATE products
                SET sku = %s,
                    name = %s,
                    sales_uom = %s,
                    sales_uom_ratio = %s,
                    sales_uom_ratio_std = %s,
                    purchasing_uom = %s,
                    purchasing_uom_ratio = %s,
                    purchasing_uom_ratio_std = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (
                item['final_sku'],
                item['clean_name'],
                item['sales_uom'],
                item['sales_uom_ratio'],
                item['sales_uom_ratio_std'],
                item['purchasing_uom'],
                item['purchasing_uom_ratio'],
                item['purchasing_uom_ratio_std'],
                item['pid']
            ))

        pg_conn.commit()
        logger.info("Successfully updated all products in PostgreSQL!")

        # Print sample results
        print("\n=== Sample Updated Products ===")
        pg_cur.execute("""
            SELECT id, sku, name, sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std
            FROM products
            ORDER BY id
            LIMIT 15;
        """)
        for r in pg_cur.fetchall():
            print(f"ID {r[0]:3d} | SKU: {r[1]:<20} | Name: {r[2][:35]:<35} | Sales: {r[3]} ({float(r[4]):g}) | Purch: {r[5]} ({float(r[6]):g})")

    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Error updating products: {e}", exc_info=True)
        raise
    finally:
        mssql_cur.close()
        mssql_conn.close()
        pg_cur.close()
        pg_conn.close()

if __name__ == '__main__':
    update_products()
