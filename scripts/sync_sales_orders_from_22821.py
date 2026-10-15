import sys
import os
import re
import logging
from datetime import datetime, date
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
from psycopg2.extras import RealDictCursor, execute_values
from config import Config
from database import resync_all_sequences

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.sync_so_22821')

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

def sync_sales_orders_from_22821():
    logger.info("=" * 70)
    logger.info("  inFlow Premium: Update Sales Orders Starting from SO-022821")
    logger.info("  Source: C:\\Program Files (x86)\\inFlow Inventory (.\\INFLOWSQL)")
    logger.info("=" * 70)

    mssql_conn = get_sqlserver_connection()
    mssql_cur = mssql_conn.cursor()

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor()

    try:
        # -------------------------------------------------------------
        # STEP 1: Query all sales orders in inFlow >= SO-022821
        # -------------------------------------------------------------
        mssql_cur.execute("""
            SELECT 
                so.SalesOrderId, so.OrderNumber, so.CustomerId, so.LocationId, so.OrderDate, so.DueDate, so.OrderStatus,
                so.OrderSubTotal, so.OrderTax1 + so.OrderTax2 as TaxAmount, so.OrderTotal, so.AmountPaid, so.InvoiceBalance,
                so.SalesRep, so.OrderRemarks, so.PickedDate, so.PackedDate, so.InvoicedDate,
                so.ContactName, so.Phone, so.ShippingAddress1, so.ShippingCity, so.PricingSchemeId, so.PONumber
            FROM SO_SalesOrder so
            WHERE so.OrderNumber >= 'SO-022821' OR so.SalesOrderId >= 34385
            ORDER BY so.SalesOrderId
        """)
        inflow_orders = mssql_cur.fetchall()
        logger.info(f"Found {len(inflow_orders)} sales orders in inFlow Inventory >= SO-022821.")

        if not inflow_orders:
            logger.info("No orders found to sync.")
            return 0

        target_so_ids = [r[0] for r in inflow_orders]
        target_so_ids_str = ','.join(map(str, target_so_ids))

        # -------------------------------------------------------------
        # STEP 2: Check & Sync Missing Customers Referenced by Orders
        # -------------------------------------------------------------
        needed_cust_ids = list(set([r[2] for r in inflow_orders if r[2]]))
        if needed_cust_ids:
            pg_cur.execute("SELECT id FROM customers WHERE id = ANY(%s)", (needed_cust_ids,))
            existing_cust_ids = set([r[0] for r in pg_cur.fetchall()])
            missing_cust_ids = [cid for cid in needed_cust_ids if cid not in existing_cust_ids]
            
            if missing_cust_ids:
                logger.info(f"Syncing {len(missing_cust_ids)} missing customer(s) from inFlow: {missing_cust_ids}")
                mssql_cur.execute(f"""
                    SELECT 
                        c.CustomerId, c.Name, c.ContactName, c.Phone, c.Fax, c.Email,
                        c.Address1, c.Address2, c.City, c.State, c.Country, c.PostalCode,
                        c.BillingAddress1, c.ShippingAddress1, c.DefaultPricingSchemeId, c.Discount,
                        c.IsActive, c.Website,
                        ISNULL(cb.Balance, 0) as Balance
                    FROM BASE_Customer c
                    LEFT JOIN (
                        SELECT CustomerId, SUM(Balance) as Balance 
                        FROM BASE_CustomerBalanceTotal 
                        GROUP BY CustomerId
                    ) cb ON c.CustomerId = cb.CustomerId
                    WHERE c.CustomerId IN ({','.join(map(str, missing_cust_ids))})
                """)
                new_custs = mssql_cur.fetchall()
                for c in new_custs:
                    pg_cur.execute("""
                        INSERT INTO customers (
                            id, name, contact_name, phone, fax, email,
                            address1, address2, city, state, country, postal_code,
                            billing_address, shipping_address, default_pricing_scheme_id, discount_percent,
                            is_active, website, balance, branch_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            contact_name = EXCLUDED.contact_name,
                            phone = EXCLUDED.phone,
                            address1 = EXCLUDED.address1,
                            balance = EXCLUDED.balance,
                            is_active = EXCLUDED.is_active;
                    """, (
                        c[0], (c[1] or f"Customer {c[0]}").strip(), (c[2] or '').strip(), (c[3] or '').strip(),
                        (c[4] or '').strip(), (c[5] or '').strip(), (c[6] or '').strip(), (c[7] or '').strip(),
                        (c[8] or '').strip(), (c[9] or '').strip(), (c[10] or 'Cambodia').strip(), (c[11] or '').strip(),
                        (c[12] or c[6] or '').strip(), (c[13] or c[6] or '').strip(), c[14], float(c[15] or 0),
                        bool(c[16]), (c[17] or '').strip(), float(c[18] or 0)
                    ))
                logger.info(f"Successfully inserted {len(new_custs)} missing customers.")

        # -------------------------------------------------------------
        # STEP 3: Check & Sync Missing Products Referenced by Order Lines
        # -------------------------------------------------------------
        mssql_cur.execute(f"""
            SELECT DISTINCT ProdId
            FROM SO_SalesOrder_Line
            WHERE SalesOrderId IN ({target_so_ids_str}) AND ProdId IS NOT NULL
        """)
        needed_prod_ids = [r[0] for r in mssql_cur.fetchall()]
        if needed_prod_ids:
            pg_cur.execute("SELECT id FROM products WHERE id = ANY(%s)", (needed_prod_ids,))
            existing_prod_ids = set([r[0] for r in pg_cur.fetchall()])
            missing_prod_ids = [pid for pid in needed_prod_ids if pid not in existing_prod_ids]

            if missing_prod_ids:
                logger.info(f"Syncing {len(missing_prod_ids)} missing product(s) from inFlow: {missing_prod_ids}")
                type_map = {1: 'Stockable', 2: 'Non-Stocked', 3: 'Service'}
                tax_map = {100: 'Taxable', 101: 'Non-Taxable'}
                costing_map = {1: 'Manual', 2: 'Average', 3: 'Standard', 4: 'FIFO'}

                mssql_cur.execute(f"""
                    SELECT 
                        p.ProdId,
                        ISNULL(p.Name, '') as Name,
                        p.Description,
                        p.BarCode,
                        p.CategoryId,
                        p.Uom,
                        p.MasterPackQty,
                        p.InnerPackQty,
                        p.DefaultLocationId,
                        p.ReorderPoint,
                        p.ReorderQuantity,
                        p.IsSellable,
                        p.IsPurchaseable,
                        p.IsActive,
                        p.DateIntroduced,
                        ISNULL(c.StandardCost, 0) as StandardCost,
                        ISNULL(c.AverageCost, 0) as AverageCost,
                        ISNULL(c.LastPurchaseCost, 0) as LastPurchaseCost,
                        ISNULL(pr.UnitPrice, 0) as DefaultPrice,
                        p.ItemType,
                        p.ItemTaxCodeId,
                        ISNULL(c.CostingMethod, 1) as CostingMethod,
                        p.PictureFileAttachmentId,
                        p.SoUomName, p.SoUomRatioStd, p.SoUomRatio,
                        p.PoUomName, p.PoUomRatioStd, p.PoUomRatio
                    FROM BASE_Product p
                    LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
                    LEFT JOIN BASE_ItemPrice pr ON p.ProdId = pr.ProdId AND pr.PricingSchemeId = 1
                    WHERE p.ProdId IN ({','.join(map(str, missing_prod_ids))})
                """)
                missing_prows = mssql_cur.fetchall()
                for p in missing_prows:
                    pid = p[0]
                    pname = (p[1] or f"Product {pid}").strip()
                    
                    # Generate SKU
                    khmer_m = re.search(r'[\u1780-\u17FF]', pname)
                    if khmer_m and khmer_m.start() > 0:
                        prefix = pname[:khmer_m.start()].strip().rstrip(' -_:/')
                        raw_sku = prefix if (prefix and re.search(r'[A-Za-z]', prefix)) else f"SKU-{pid:04d}"
                    else:
                        raw_sku = f"SKU-{pid:04d}"
                    
                    # Ensure SKU unique in PG
                    pg_cur.execute("SELECT 1 FROM products WHERE sku = %s", (raw_sku,))
                    if pg_cur.fetchone():
                        final_sku = f"{raw_sku}-{pid}"
                    else:
                        final_sku = raw_sku

                    base_uom = (p[5] or 'pcs').strip()
                    so_uom = (p[23] or '').strip()
                    so_ratio_std = float(p[24]) if p[24] is not None else 1.0
                    m_pack = float(p[6]) if p[6] else 1.0
                    if so_ratio_std <= 1.0:
                        name_pack_match = re.search(r'(\d+)\s*(?:ចាន|ប្រអប់|កែវ|ដប|គ្រាប់|ថង់|កំប៉ុង|សន្លឹក|pcs|ដុំ|គូរ)?\s*[/／]\s*(កេស|Case|Pack|ដុំ|បេ)', pname, re.IGNORECASE)
                        if name_pack_match:
                            extracted_num = float(name_pack_match.group(1))
                            pack_type = name_pack_match.group(2).lower()
                            if extracted_num > 1.0:
                                so_ratio_std = extracted_num
                                if not so_uom:
                                    so_uom = 'packs' if pack_type in ('pack', 'ដុំ') else 'cases'
                        elif m_pack > 1.0:
                            so_ratio_std = m_pack
                            if not so_uom:
                                so_uom = 'cases'
                    if not so_uom:
                        so_uom = 'cases' if so_ratio_std > 1.0 else base_uom

                    # Ensure category exists
                    cat_id = p[4]
                    if cat_id:
                        pg_cur.execute("SELECT 1 FROM categories WHERE id = %s", (cat_id,))
                        if not pg_cur.fetchone():
                            cat_id = None

                    pg_cur.execute("""
                        INSERT INTO products (
                            id, sku, name, description, barcode, category_id, uom,
                            master_pack_qty, inner_pack_qty, default_location_id, reorder_point, reorder_quantity,
                            standard_cost, average_cost, last_purchase_cost, default_price,
                            is_sellable, is_purchaseable, is_active,
                            item_type, tax_code, costing_method, image_url, custom_attributes,
                            sales_uom, sales_uom_ratio, sales_uom_ratio_std,
                            purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            sku = EXCLUDED.sku,
                            uom = EXCLUDED.uom,
                            sales_uom = EXCLUDED.sales_uom,
                            sales_uom_ratio_std = EXCLUDED.sales_uom_ratio_std;
                    """, (
                        pid, final_sku, pname, (p[2] or '').strip(), (p[3] or '').strip() or None, cat_id, base_uom,
                        m_pack, float(p[7]) if p[7] else 1.0, 100, float(p[9]) if p[9] else 0.0, float(p[10]) if p[10] else 0.0,
                        float(p[15]) if p[15] else 0.0, float(p[16]) if p[16] else 0.0, float(p[17]) if p[17] else 0.0, float(p[18]) if p[18] else 0.0,
                        bool(p[11]), bool(p[12]), bool(p[13]),
                        type_map.get(p[19], 'Stockable'), tax_map.get(p[20], 'Taxable'), costing_map.get(p[21], 'Manual'),
                        None, f'{{"inflow_prod_id": {pid}}}',
                        so_uom, so_ratio_std, so_ratio_std,
                        so_uom, so_ratio_std, so_ratio_std
                    ))
                logger.info(f"Successfully inserted {len(missing_prows)} missing products.")

        # -------------------------------------------------------------
        # STEP 4: Fetch all lines and costs for these orders
        # -------------------------------------------------------------
        logger.info("Fetching Sales Order Lines from inFlow...")
        mssql_cur.execute(f"""
            SELECT 
                sol.SalesOrderLineId, sol.SalesOrderId, sol.LineNum, sol.ProdId, sol.Description,
                sol.Quantity, sol.UnitPrice, sol.Discount, sol.SubTotal, sol.QuantityUom, sol.QuantityDisplay,
                p.Name as ProductName, ISNULL(c.StandardCost, ISNULL(c.AverageCost, 0)) as CostPrice
            FROM SO_SalesOrder_Line sol
            LEFT JOIN BASE_Product p ON sol.ProdId = p.ProdId
            LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
            WHERE sol.SalesOrderId IN ({target_so_ids_str})
            ORDER BY sol.SalesOrderId, sol.LineNum
        """)
        sol_rows = mssql_cur.fetchall()
        
        # Group lines by sales_order_id
        order_lines_map = {}
        for sol in sol_rows:
            lid = sol[0]
            so_id = sol[1]
            line_num = sol[2]
            prod_id = sol[3]
            inflow_desc = (sol[4] or '').strip()
            qty = float(sol[5] or 0)
            uprice = float(sol[6] or 0)
            disc = float(sol[7] or 0)
            subtot = float(sol[8] or 0)
            uom = (str(sol[9]).strip() if sol[9] else 'pcs')
            q_disp = float(sol[10]) if sol[10] is not None else qty
            cost_price = float(sol[12] or 0)

            line_entry = (
                lid, so_id, line_num, prod_id, inflow_desc if inflow_desc else None,
                qty, uprice, disc, subtot, cost_price,
                qty, qty, qty, uom, q_disp
            )
            order_lines_map.setdefault(so_id, []).append(line_entry)

        # -------------------------------------------------------------
        # STEP 5: Fetch payments from inFlow for these orders
        # -------------------------------------------------------------
        mssql_cur.execute(f"""
            SELECT 
                SalesOrderId, DatePaid,
                PaymentMethod, ReferenceNumber, Remarks, Amount
            FROM SO_SalesOrderPayment_Line
            WHERE SalesOrderId IN ({target_so_ids_str}) AND Amount IS NOT NULL AND Amount > 0
            ORDER BY SalesOrderId, DatePaid;
        """)
        so_pay_rows = mssql_cur.fetchall()
        order_payments_map = {}
        for pr in so_pay_rows:
            s_order_id = pr[0]
            p_date = pr[1] or datetime.now()
            p_method = (pr[2] or 'Cash').strip() or 'Cash'
            p_ref = (pr[3] or '').strip()
            p_rem = (pr[4] or '').strip()
            p_amt = float(pr[5] or 0)
            pay_entry = ('SO', s_order_id, p_amt, p_method, p_date, p_ref, p_rem, None)
            order_payments_map.setdefault(s_order_id, []).append(pay_entry)

        # -------------------------------------------------------------
        # STEP 6: Insert or Update Sales Orders & Lines & Payments in PG
        # -------------------------------------------------------------
        so_status_map = {1: 'QUOTE', 2: 'OPEN', 4: 'PICKED', 5: 'PACKED', 6: 'INVOICED', 10: 'CANCELLED'}

        updated_so_count = 0
        inserted_so_count = 0
        total_lines_synced = 0
        total_payments_synced = 0

        for so in inflow_orders:
            s_id = so[0]
            ord_num = (so[1] or f"SO-{s_id:06d}").strip()
            cust_id = so[2]
            loc_id = so[3] or 100
            so_date = so[4].date() if so[4] else datetime.now().date()
            due_dt = so[5].date() if so[5] else None

            tot_amt = float(so[9] or 0)
            paid_amt = float(so[10] or 0)
            bal_due = float(so[11] or 0)

            st_raw = so[6]
            st = so_status_map.get(st_raw, 'OPEN')

            # Calculate accurate payment status & balance
            if st == 'CANCELLED':
                bal_due = 0.0
                pay_st = 'UNPAID'
            elif paid_amt >= tot_amt and tot_amt > 0:
                pay_st = 'PAID'
                bal_due = 0.0
            elif st == 'INVOICED' and bal_due <= 0 and tot_amt > 0:
                pay_st = 'PAID'
                bal_due = 0.0
            elif paid_amt > 0:
                pay_st = 'PARTIAL'
                bal_due = max(0.0, tot_amt - paid_amt)
            else:
                pay_st = 'UNPAID'
                bal_due = tot_amt

            sales_rep = (so[12] or '').strip()
            notes = (so[13] or '').strip()
            picked_dt = so[14]
            packed_dt = so[15]
            invoiced_dt = so[16]
            contact = (so[17] or '').strip()
            phone = (so[18] or '').strip()
            ship_addr = (so[19] or '').strip()
            ship_city = (so[20] or '').strip()
            scheme_id = so[21]
            po_num = (so[22] or '').strip()
            subtotal = float(so[7] or 0)
            tax_amt = float(so[8] or 0)

            # Check if order already exists in PG
            pg_cur.execute("SELECT id FROM sales_orders WHERE id = %s OR order_number = %s", (s_id, ord_num))
            existing_row = pg_cur.fetchone()

            if existing_row:
                # Update existing sales order
                existing_id = existing_row[0]
                pg_cur.execute("""
                    UPDATE sales_orders
                    SET order_number = %s,
                        customer_id = %s,
                        location_id = %s,
                        order_date = %s,
                        due_date = %s,
                        status = %s,
                        payment_status = %s,
                        subtotal = %s,
                        tax_amount = %s,
                        total_amount = %s,
                        paid_amount = %s,
                        balance_due = %s,
                        sales_rep = %s,
                        notes = %s,
                        picked_date = %s,
                        packed_date = %s,
                        invoiced_date = %s,
                        customer_contact = %s,
                        customer_phone = %s,
                        customer_address = %s,
                        destination_province = %s,
                        pricing_scheme_id = %s,
                        po_number = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (
                    ord_num, cust_id, loc_id, so_date, due_dt,
                    st, pay_st, subtotal, tax_amt, tot_amt, paid_amt, bal_due,
                    sales_rep, notes, picked_dt, packed_dt, invoiced_dt,
                    contact, phone, ship_addr, ship_city, scheme_id, po_num,
                    existing_id
                ))
                updated_so_count += 1
                current_order_id = existing_id
            else:
                # Insert new sales order with exact id
                pg_cur.execute("""
                    INSERT INTO sales_orders (
                        id, order_number, customer_id, location_id, order_date, due_date,
                        status, payment_status, subtotal, tax_amount, total_amount, paid_amount, balance_due,
                        sales_rep, notes, picked_date, packed_date, invoiced_date,
                        customer_contact, customer_phone, customer_address, destination_province, pricing_scheme_id, po_number, branch_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, NULL
                    );
                """, (
                    s_id, ord_num, cust_id, loc_id, so_date, due_dt,
                    st, pay_st, subtotal, tax_amt, tot_amt, paid_amt, bal_due,
                    sales_rep, notes, picked_dt, packed_dt, invoiced_dt,
                    contact, phone, ship_addr, ship_city, scheme_id, po_num
                ))
                inserted_so_count += 1
                current_order_id = s_id

            # Sync Lines for this order: delete existing lines then re-insert
            pg_cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (current_order_id,))
            lines_for_so = order_lines_map.get(s_id, [])
            if lines_for_so:
                # Replace sales_order_id with current_order_id if different
                clean_lines = []
                for ln in lines_for_so:
                    clean_lines.append((
                        ln[0], current_order_id, ln[2], ln[3], ln[4],
                        ln[5], ln[6], ln[7], ln[8], ln[9],
                        ln[10], ln[11], ln[12], ln[13], ln[14]
                    ))
                execute_values(pg_cur, """
                    INSERT INTO sales_order_lines (
                        id, sales_order_id, line_num, product_id, description,
                        quantity, unit_price, discount_percent, subtotal, cost_price,
                        picked_qty, packed_qty, shipped_qty, uom, quantity_display
                    ) VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        sales_order_id = EXCLUDED.sales_order_id,
                        line_num = EXCLUDED.line_num,
                        product_id = EXCLUDED.product_id,
                        description = EXCLUDED.description,
                        quantity = EXCLUDED.quantity,
                        unit_price = EXCLUDED.unit_price,
                        discount_percent = EXCLUDED.discount_percent,
                        subtotal = EXCLUDED.subtotal,
                        cost_price = EXCLUDED.cost_price,
                        picked_qty = EXCLUDED.picked_qty,
                        packed_qty = EXCLUDED.packed_qty,
                        shipped_qty = EXCLUDED.shipped_qty,
                        uom = EXCLUDED.uom,
                        quantity_display = EXCLUDED.quantity_display;
                """, clean_lines)
                total_lines_synced += len(clean_lines)

            # Sync Payments for this order: delete existing payments then insert
            pg_cur.execute("DELETE FROM order_payments WHERE order_type = 'SO' AND order_id = %s", (current_order_id,))
            payments_for_so = order_payments_map.get(s_id, [])
            if payments_for_so:
                clean_payments = []
                for p in payments_for_so:
                    clean_payments.append((p[0], current_order_id, p[2], p[3], p[4], p[5], p[6], p[7]))
                execute_values(pg_cur, """
                    INSERT INTO order_payments (
                        order_type, order_id, amount, payment_method, payment_date, reference, notes, branch_id
                    ) VALUES %s
                """, clean_payments)
                total_payments_synced += len(clean_payments)

        # -------------------------------------------------------------
        # STEP 7: RESYNC POSTGRES SERIAL SEQUENCES
        # -------------------------------------------------------------
        logger.info("Resetting PostgreSQL sequences...")
        pg_cur.execute("""
            DO $$
            DECLARE
                t text;
                s text;
                m bigint;
            BEGIN
                FOR t IN SELECT unnest(ARRAY[
                    'sales_orders', 'sales_order_lines', 'order_payments', 'products', 'customers'
                ]) LOOP
                    s := pg_get_serial_sequence(t, 'id');
                    IF s IS NOT NULL THEN
                        EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I', t) INTO m;
                        IF m > 0 THEN
                            PERFORM setval(s, m, true);
                        END IF;
                    END IF;
                END LOOP;
            END $$;
        """)

        # Call database resync_all_sequences
        resync_all_sequences(pg_cur)

        pg_conn.commit()
        logger.info("Transaction committed successfully.")

        logger.info("=" * 70)
        logger.info("SALES ORDER SYNCHRONIZATION RESULTS (from SO-022821)")
        logger.info("=" * 70)
        logger.info(f"Total inFlow Orders Synced  : {len(inflow_orders)}")
        logger.info(f"  Existing Orders Updated   : {updated_so_count}")
        logger.info(f"  New Orders Inserted       : {inserted_so_count}")
        logger.info(f"Total Order Lines Synced    : {total_lines_synced}")
        logger.info(f"Total Order Payments Synced : {total_payments_synced}")
        logger.info("=" * 70)

        # Print detailed report of synced orders
        pg_cur.execute("""
            SELECT so.id, so.order_number, so.order_date, so.status, so.payment_status,
                   so.total_amount, so.paid_amount, so.balance_due, c.name as customer_name,
                   (SELECT COUNT(*) FROM sales_order_lines sol WHERE sol.sales_order_id = so.id) as line_count
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.order_number >= 'SO-022821'
            ORDER BY so.order_number;
        """)
        synced_records = pg_cur.fetchall()
        print("\n=== Current PostgreSQL State for Orders >= SO-022821 ===")
        for r in synced_records:
            print(f"Order: {r[1]:10s} (ID: {r[0]:5d}) | Date: {r[2]} | Status: {r[3]:10s} | Pay: {r[4]:8s} | Total: ${r[5]:9.2f} | Bal: ${r[7]:9.2f} | Cust: {r[8]} | Lines: {r[9]}")

        return len(inflow_orders)

    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Error syncing sales orders: {e}", exc_info=True)
        raise
    finally:
        mssql_conn.close()
        pg_conn.close()

if __name__ == '__main__':
    sync_sales_orders_from_22821()
