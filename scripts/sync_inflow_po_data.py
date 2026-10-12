import sys
import os
import logging
from datetime import datetime
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
from psycopg2.extras import execute_values, RealDictCursor
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.sync_po')

def get_sqlserver_connection():
    conn_str = (
        f"Driver={{ODBC Driver 17 for SQL Server}};"
        f"Server={Config.SQLSERVER_HOST};"
        f"Database={Config.SQLSERVER_DB};"
        f"UID={Config.SQLSERVER_USER};"
        f"PWD={Config.SQLSERVER_PASSWORD};"
        f"TrustServerCertificate=yes;"
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

def sync_po_data():
    logger.info("Connecting to inFlow SQL Server (.\\INFLOWSQL) and PostgreSQL...")
    mssql_conn = get_sqlserver_connection()
    mssql_cur = mssql_conn.cursor()

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 1. Sync Vendor details & Balances
        logger.info("Step 1: Syncing Vendors and balances from inFlow...")
        mssql_cur.execute("""
            SELECT 
                v.VendorId, v.Name, v.ContactName, v.Phone, v.Email, 
                v.Address1, v.City, v.Country, v.PostalCode, v.IsActive,
                ISNULL(vb.Balance, 0) as Balance
            FROM BASE_Vendor v
            LEFT JOIN (
                SELECT VendorId, SUM(Balance) as Balance 
                FROM BASE_VendorBalanceTotal 
                GROUP BY VendorId
            ) vb ON v.VendorId = vb.VendorId
            ORDER BY v.VendorId;
        """)
        vendors = mssql_cur.fetchall()
        for v in vendors:
            pg_cur.execute("""
                INSERT INTO vendors (
                    id, name, contact_name, phone, email, address1, city, country, postal_code, is_active, balance
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    contact_name = COALESCE(EXCLUDED.contact_name, vendors.contact_name),
                    phone = COALESCE(EXCLUDED.phone, vendors.phone),
                    email = COALESCE(EXCLUDED.email, vendors.email),
                    address1 = COALESCE(EXCLUDED.address1, vendors.address1),
                    balance = EXCLUDED.balance,
                    is_active = EXCLUDED.is_active;
            """, (
                v[0], (v[1] or f"Vendor {v[0]}").strip(), v[2], v[3], v[4],
                v[5], v[6], v[7] or 'Cambodia', v[8], bool(v[9]), float(v[10] or 0)
            ))
        logger.info(f"Synchronized {len(vendors)} vendors.")

        # 2. Sync Missing Products
        logger.info("Step 2: Checking and syncing missing products...")
        mssql_cur.execute("""
            SELECT 
                p.ProdId, p.Name, p.Description, p.BarCode, p.CategoryId, p.Uom,
                p.DefaultLocationId, p.ReorderPoint, p.ReorderQuantity, p.IsSellable, p.IsPurchaseable, p.IsActive,
                ISNULL(c.StandardCost, 0) as StandardCost,
                ISNULL(c.AverageCost, 0) as AverageCost,
                ISNULL(c.LastPurchaseCost, 0) as LastPurchaseCost,
                ISNULL(pr.UnitPrice, 0) as DefaultPrice
            FROM BASE_Product p
            LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
            LEFT JOIN BASE_ItemPrice pr ON p.ProdId = pr.ProdId AND pr.PricingSchemeId = 1
            ORDER BY p.ProdId;
        """)
        all_mssql_prods = mssql_cur.fetchall()

        # Build product mapping dictionary in PG
        pg_cur.execute("SELECT id, name, sku, custom_attributes FROM products")
        pg_prods = pg_cur.fetchall()
        pg_prod_by_inflow_id = {}
        pg_prod_by_name = {}

        for p in pg_prods:
            pname = p['name'].strip() if p['name'] else ''
            if pname:
                pg_prod_by_name[pname.lower()] = p['id']
            ca = p.get('custom_attributes') or {}
            if isinstance(ca, dict) and ca.get('inflow_prod_id'):
                pg_prod_by_inflow_id[int(ca['inflow_prod_id'])] = p['id']

        missing_count = 0
        for p in all_mssql_prods:
            prod_id = p[0]
            pname = (p[1] or f"Product {prod_id}").strip()
            
            # If not in PG by inflow_id and not by name, insert it
            if prod_id not in pg_prod_by_inflow_id and pname.lower() not in pg_prod_by_name:
                sku = f"SKU-{prod_id:04d}"
                pg_cur.execute("""
                    INSERT INTO products (
                        sku, name, description, barcode, category_id, uom,
                        default_location_id, reorder_point, reorder_quantity,
                        standard_cost, average_cost, last_purchase_cost, default_price,
                        is_sellable, is_purchaseable, is_active,
                        custom_attributes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id;
                """, (
                    sku, pname, p[2] or '', p[3] or '', p[4] or 100, p[5] or 'pcs',
                    p[6] or 100, float(p[7] or 0), float(p[8] or 0),
                    float(p[12] or 0), float(p[13] or 0), float(p[14] or 0), float(p[15] or 0),
                    bool(p[9]), bool(p[10]), bool(p[11]),
                    f'{{"inflow_prod_id": {prod_id}}}'
                ))
                new_id = pg_cur.fetchone()['id']
                pg_prod_by_inflow_id[prod_id] = new_id
                pg_prod_by_name[pname.lower()] = new_id
                missing_count += 1
            elif pname.lower() in pg_prod_by_name and prod_id not in pg_prod_by_inflow_id:
                # Update custom_attributes with inflow_prod_id
                matched_id = pg_prod_by_name[pname.lower()]
                pg_cur.execute("""
                    UPDATE products 
                    SET custom_attributes = jsonb_set(COALESCE(custom_attributes, '{}'::jsonb), '{inflow_prod_id}', %s::jsonb)
                    WHERE id = %s;
                """, (f'{prod_id}', matched_id))
                pg_prod_by_inflow_id[prod_id] = matched_id

        logger.info(f"Synced products: added {missing_count} missing products. Total mapped: {len(pg_prod_by_inflow_id)}")

        # 3. Synchronize Purchase Orders (PO_PurchaseOrder)
        logger.info("Step 3: Synchronizing Purchase Orders...")
        mssql_cur.execute("""
            SELECT 
                po.PurchaseOrderId, po.OrderNumber, po.VendorId, po.LocationId, 
                po.OrderDate, po.DueDate, po.RequestShipDate, po.OrderStatus,
                po.OrderSubTotal, po.OrderTax1 + po.OrderTax2 as TaxAmount, po.OrderExtra as Freight,
                po.OrderTotal, po.AmountPaid, po.PaymentBalance, 
                po.ContactName, po.Phone, po.VendorAddress1, po.Carrier, 
                po.VendorOrderNumber, po.AncillaryExpenses, po.OrderRemarks
            FROM PO_PurchaseOrder po
            ORDER BY po.PurchaseOrderId;
        """)
        po_rows = mssql_cur.fetchall()
        po_status_map = {1: 'ISSUED', 2: 'ISSUED', 5: 'RECEIVED', 6: 'PAID', 10: 'CANCELLED'}

        po_update_data = []
        for po in po_rows:
            p_id = po[0]
            ord_num = po[1] or f"PO-{p_id:06d}"
            vend_id = po[2]
            loc_id = po[3] or 100
            ord_date = po[4].date() if po[4] else datetime.now().date()
            due_date = po[5].date() if po[5] else (po[6].date() if po[6] else None)
            st_raw = po[7]
            st = po_status_map.get(st_raw, 'ISSUED')

            subtotal = float(po[8] or 0)
            tax_amt = float(po[9] or 0)
            freight = float(po[10] or 0)
            total_amt = float(po[11] or 0)
            paid_amt = float(po[12] or 0)
            balance_due = float(po[13] or 0)

            # Determine payment status
            if total_amt > 0 and balance_due <= 0:
                pay_st = 'PAID'
            elif paid_amt > 0:
                pay_st = 'PARTIAL'
            else:
                pay_st = 'UNPAID'

            contact = (po[14] or '').strip()
            phone = (po[15] or '').strip()
            addr = (po[16] or '').strip()
            carrier = (po[17] or '').strip()
            vendor_inv = (po[18] or '').strip()
            non_vendor = float(po[19] or 0)
            notes = (po[20] or '').strip()

            po_update_data.append((
                p_id, ord_num, vend_id, loc_id, ord_date, due_date,
                st, pay_st, subtotal, tax_amt, freight, total_amt, paid_amt, balance_due,
                contact, phone, addr, carrier, vendor_inv, non_vendor, 'USD', notes
            ))

        execute_values(pg_cur, """
            INSERT INTO purchase_orders (
                id, order_number, vendor_id, location_id, order_date, expected_date,
                status, payment_status, subtotal, tax_amount, shipping_fee, total_amount, paid_amount, balance_due,
                contact, phone, vendor_address, carrier, vendor_invoice_no, non_vendor_costs, currency_code, notes
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                order_number = EXCLUDED.order_number,
                vendor_id = EXCLUDED.vendor_id,
                location_id = EXCLUDED.location_id,
                order_date = EXCLUDED.order_date,
                expected_date = EXCLUDED.expected_date,
                status = EXCLUDED.status,
                payment_status = EXCLUDED.payment_status,
                subtotal = EXCLUDED.subtotal,
                tax_amount = EXCLUDED.tax_amount,
                shipping_fee = EXCLUDED.shipping_fee,
                total_amount = EXCLUDED.total_amount,
                paid_amount = EXCLUDED.paid_amount,
                balance_due = EXCLUDED.balance_due,
                contact = EXCLUDED.contact,
                phone = EXCLUDED.phone,
                vendor_address = EXCLUDED.vendor_address,
                carrier = EXCLUDED.carrier,
                vendor_invoice_no = EXCLUDED.vendor_invoice_no,
                non_vendor_costs = EXCLUDED.non_vendor_costs,
                currency_code = EXCLUDED.currency_code,
                notes = EXCLUDED.notes;
        """, po_update_data)
        logger.info(f"Synchronized {len(po_update_data)} Purchase Orders.")

        # 4. Synchronize Purchase Order Lines (PO_PurchaseOrder_Line)
        logger.info("Step 4: Synchronizing Purchase Order Lines...")
        # Clean existing lines for imported inFlow orders (id <= 880)
        pg_cur.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id <= 880;")

        mssql_cur.execute("""
            SELECT 
                pol.PurchaseOrderLineId, pol.PurchaseOrderId, pol.LineNum, pol.ProdId,
                pol.Description, pol.VendorItemCode, pol.Quantity, pol.UnitPrice,
                pol.Discount, pol.SubTotal, p.Name as ProductName
            FROM PO_PurchaseOrder_Line pol
            LEFT JOIN BASE_Product p ON pol.ProdId = p.ProdId
            ORDER BY pol.PurchaseOrderId, pol.LineNum;
        """)
        line_rows = mssql_cur.fetchall()

        # Pre-fetch receipts from PO_PurchaseOrderReceive_Line
        mssql_cur.execute("""
            SELECT PurchaseOrderId, LineNum, SUM(Quantity) as RecvQty
            FROM PO_PurchaseOrderReceive_Line
            WHERE IsReceived = 1
            GROUP BY PurchaseOrderId, LineNum;
        """)
        recv_dict = {}
        for r in mssql_cur.fetchall():
            recv_dict[(r[0], r[1])] = float(r[2] or 0)

        # Get PO status map from PostgreSQL for receipt calculation
        pg_cur.execute("SELECT id, status FROM purchase_orders;")
        po_status_in_pg = {r['id']: r['status'] for r in pg_cur.fetchall()}

        lines_insert_data = []
        for l in line_rows:
            lid = l[0]
            po_id = l[1]
            line_num = l[2]
            prod_id = l[3]
            inflow_desc = (l[4] or '').strip()
            vendor_code = (l[5] or '').strip()
            qty = float(l[6] or 0)
            cost = float(l[7] or 0)
            disc = float(l[8] or 0)
            subtot = float(l[9] or 0)
            prod_name = (l[10] or '').strip()

            # Map to PostgreSQL product_id
            pg_pid = pg_prod_by_inflow_id.get(prod_id)
            if not pg_pid and prod_name:
                pg_pid = pg_prod_by_name.get(prod_name.lower())

            # Final description
            final_desc = inflow_desc if inflow_desc else prod_name

            # Calculate received quantity
            actual_recv = recv_dict.get((po_id, line_num))
            if actual_recv is not None:
                received_qty = actual_recv
            elif po_status_in_pg.get(po_id) in ('RECEIVED', 'PAID'):
                received_qty = qty
            else:
                received_qty = 0.0

            lines_insert_data.append((
                lid, po_id, line_num, pg_pid, final_desc, vendor_code,
                qty, cost, disc, subtot, received_qty
            ))

        execute_values(pg_cur, """
            INSERT INTO purchase_order_lines (
                id, purchase_order_id, line_num, product_id, description, vendor_product_code,
                quantity, unit_cost, discount_percent, subtotal, received_qty
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                product_id = EXCLUDED.product_id,
                description = EXCLUDED.description,
                vendor_product_code = EXCLUDED.vendor_product_code,
                quantity = EXCLUDED.quantity,
                unit_cost = EXCLUDED.unit_cost,
                discount_percent = EXCLUDED.discount_percent,
                subtotal = EXCLUDED.subtotal,
                received_qty = EXCLUDED.received_qty;
        """, lines_insert_data)
        logger.info(f"Synchronized {len(lines_insert_data)} Purchase Order Lines.")

        # 5. Synchronize Supplier Payments (PO_PurchaseOrderMoneyPayment_Line)
        logger.info("Step 5: Synchronizing Supplier Payments...")
        pg_cur.execute("DELETE FROM order_payments WHERE order_type = 'PO';")
        mssql_cur.execute("""
            SELECT 
                PurchaseOrderMoneyPaymentLineId, PurchaseOrderId, DatePaid,
                PaymentMethod, ReferenceNumber, Remarks, Amount
            FROM PO_PurchaseOrderMoneyPayment_Line
            ORDER BY PurchaseOrderId, DatePaid;
        """)
        payment_rows = mssql_cur.fetchall()
        pay_insert_data = []
        for pr in payment_rows:
            pay_id = pr[0]
            p_order_id = pr[1]
            p_date = pr[2] or datetime.now()
            p_method = (pr[3] or 'Bank Transfer').strip() or 'Bank Transfer'
            p_ref = (pr[4] or '').strip()
            p_rem = (pr[5] or '').strip()
            p_amt = float(pr[6] or 0)
            pay_insert_data.append((
                pay_id, p_order_id, 'PO', p_amt, p_date, p_method, p_ref, p_rem
            ))

        execute_values(pg_cur, """
            INSERT INTO order_payments (
                id, order_id, order_type, amount, payment_date, payment_method, reference, notes
            ) VALUES %s
            ON CONFLICT (id) DO NOTHING;
        """, pay_insert_data)
        logger.info(f"Synchronized {len(pay_insert_data)} supplier payment records.")

        # 6. Update Sequence for PO Numbers
        pg_cur.execute("SELECT MAX(id) as max_id FROM purchase_orders;")
        max_po_id = pg_cur.fetchone()['max_id'] or 1
        pg_cur.execute(f"SELECT setval('po_number_seq', {max_po_id}, true);")
        logger.info(f"Updated po_number_seq to {max_po_id}.")

        pg_conn.commit()
        logger.info("=== SUCCESS: inFlow PO Data Synchronization Complete! ===")

    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Migration error: {e}", exc_info=True)
        raise
    finally:
        mssql_cur.close()
        mssql_conn.close()
        pg_cur.close()
        pg_conn.close()

if __name__ == '__main__':
    sync_po_data()
