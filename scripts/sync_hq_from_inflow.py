import sys
import os
import time
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
from psycopg2.extras import execute_values
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.sync_hq')

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

def sync_hq():
    start_time = time.time()
    logger.info("=================================================================")
    logger.info("  inFlow Premium: Selective Update HQ Database from inFlow ETL   ")
    logger.info("  Source: C:\\Program Files (x86)\\inFlow Inventory (.\\INFLOWSQL) ")
    logger.info("=================================================================")

    # 1. Connect to both databases
    logger.info("Connecting to SQL Server and PostgreSQL...")
    mssql_conn = get_sqlserver_connection()
    mssql_cur = mssql_conn.cursor()

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor()

    stats = {
        'products': 0,
        'product_prices': 0,
        'product_versions': 0,
        'product_vendors': 0,
        'inventory': 0,
        'customers': 0,
        'vendors': 0,
        'categories': 0,
        'locations': 0,
        'pricing_schemes': 0,
        'purchase_orders': 0,
        'purchase_order_lines': 0,
        'po_payments': 0,
        'sales_orders': 0,
        'sales_order_lines': 0,
        'so_payments': 0,
        'duration_seconds': 0
    }

    try:
        # -------------------------------------------------------------
        # STEP 1: PURGE EXISTING PRODUCTS, CUSTOMERS, SO, PO (HQ & ALL BRANCHES)
        # -------------------------------------------------------------
        logger.info("STEP 1: Purging all existing products, customers, sales orders, purchase orders across HQ and branches...")
        pg_cur.execute("""
            TRUNCATE TABLE 
                order_payments,
                sales_order_lines,
                sales_orders,
                purchase_order_lines,
                purchase_orders,
                stock_transfer_lines,
                stock_transfers,
                stock_adjustment_lines,
                stock_adjustments,
                inventory_logs,
                inventory,
                product_prices,
                product_versions,
                product_vendors,
                product_boms,
                product_combine_options,
                product_attachments,
                products,
                customers
            CASCADE;
        """)
        logger.info("Purged target tables successfully. (Users, branches, expenses, delivery intact).")

        # -------------------------------------------------------------
        # STEP 2: SYNC CORE LOOKUPS (Categories, Locations, Schemes, Vendors)
        # -------------------------------------------------------------
        logger.info("STEP 2: Synchronizing categories, locations, pricing schemes, and vendors...")
        
        # 2a. Categories
        mssql_cur.execute("SELECT CategoryId, Name, ParentCategoryId, IsActive FROM BASE_Category ORDER BY CategoryId")
        cat_rows = mssql_cur.fetchall()
        for cat in cat_rows:
            pg_cur.execute("""
                INSERT INTO categories (id, name, parent_id, is_active)
                VALUES (%s, %s, NULL, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active;
            """, (cat[0], (cat[1] or f"Category {cat[0]}").strip(), bool(cat[3])))
        for cat in cat_rows:
            if cat[2] and cat[2] != cat[0]:
                pg_cur.execute("UPDATE categories SET parent_id = %s WHERE id = %s", (cat[2], cat[0]))
        stats['categories'] = len(cat_rows)

        # 2b. Locations
        mssql_cur.execute("SELECT LocationId, Name, IsActive, IsSpecialRecord FROM BASE_Location ORDER BY LocationId")
        loc_rows = mssql_cur.fetchall()
        for loc in loc_rows:
            is_def = (loc[0] == 100)
            pg_cur.execute("""
                INSERT INTO locations (id, name, is_active, is_default)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    is_default = EXCLUDED.is_default;
            """, (loc[0], (loc[1] or f"Location {loc[0]}").strip(), bool(loc[2]), is_def))
        stats['locations'] = len(loc_rows)

        # 2c. Pricing Schemes
        mssql_cur.execute("SELECT PricingSchemeId, Name, IsActive FROM BASE_PricingScheme ORDER BY PricingSchemeId")
        scheme_rows = mssql_cur.fetchall()
        for s in scheme_rows:
            pg_cur.execute("""
                INSERT INTO pricing_schemes (id, name, is_active, is_default)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active;
            """, (s[0], (s[1] or f"Scheme {s[0]}").strip(), bool(s[2]), s[0] == 1))
        stats['pricing_schemes'] = len(scheme_rows)

        # 2d. Vendors (with balances from BASE_VendorBalanceTotal)
        mssql_cur.execute("""
            SELECT 
                v.VendorId, v.Name, v.ContactName, v.Phone, v.Email, 
                v.Address1, v.Address2, v.City, v.Country, v.PostalCode, v.IsActive,
                ISNULL(vb.Balance, 0) as Balance
            FROM BASE_Vendor v
            LEFT JOIN (
                SELECT VendorId, SUM(Balance) as Balance 
                FROM BASE_VendorBalanceTotal 
                GROUP BY VendorId
            ) vb ON v.VendorId = vb.VendorId
            ORDER BY v.VendorId;
        """)
        vend_rows = mssql_cur.fetchall()
        for v in vend_rows:
            pg_cur.execute("""
                INSERT INTO vendors (
                    id, name, contact_name, phone, email, address1, address2, city, country, postal_code, is_active, balance
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    contact_name = EXCLUDED.contact_name,
                    phone = EXCLUDED.phone,
                    email = EXCLUDED.email,
                    address1 = EXCLUDED.address1,
                    city = EXCLUDED.city,
                    country = EXCLUDED.country,
                    is_active = EXCLUDED.is_active,
                    balance = EXCLUDED.balance;
            """, (
                v[0], (v[1] or f"Vendor {v[0]}").strip(), v[2], v[3], v[4],
                v[5], v[6], v[7], v[8] or 'Cambodia', v[9], bool(v[10]), float(v[11] or 0)
            ))
        stats['vendors'] = len(vend_rows)
        logger.info(f"Synchronized lookups: {stats['categories']} categories, {stats['locations']} locations, {stats['pricing_schemes']} pricing schemes, {stats['vendors']} vendors.")

        # -------------------------------------------------------------
        # STEP 3: EXTRACT PRODUCT IMAGES
        # -------------------------------------------------------------
        logger.info("STEP 3: Extracting product images from inFlow...")
        img_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'products')
        os.makedirs(img_dir, exist_ok=True)
        mssql_cur.execute("""
            SELECT p.ProdId, fa.Data
            FROM BASE_Product p
            JOIN BASE_FileAttachment fa ON p.PictureFileAttachmentId = fa.FileAttachmentId
            WHERE fa.Data IS NOT NULL
        """)
        img_dict = {}
        for r_pid, r_data in mssql_cur.fetchall():
            if r_data:
                b_data = bytes(r_data)
                ext = 'png' if b_data.startswith(b'\x89PNG') else 'jpg'
                fname = f"prod_{r_pid}.{ext}"
                fpath = os.path.join(img_dir, fname)
                try:
                    with open(fpath, 'wb') as img_f:
                        img_f.write(b_data)
                    img_dict[r_pid] = f"/static/uploads/products/{fname}"
                except Exception:
                    pass
        logger.info(f"Extracted {len(img_dict)} product images.")

        # -------------------------------------------------------------
        # STEP 4: SYNC PRODUCTS MASTER CATALOG
        # -------------------------------------------------------------
        logger.info("STEP 4: Importing Products Master Catalog from inFlow...")
        mssql_cur.execute("""
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
            ORDER BY p.ProdId
        """)
        prod_rows = mssql_cur.fetchall()

        type_map = {1: 'Stockable', 2: 'Non-Stocked', 3: 'Service'}
        tax_map = {100: 'Taxable', 101: 'Non-Taxable'}
        costing_map = {1: 'Manual', 2: 'Average', 3: 'Standard', 4: 'FIFO'}

        # Pre-process SKUs to ensure uniqueness
        from collections import Counter
        sku_counter = Counter()
        pre_processed = []

        for p in prod_rows:
            prod_id = p[0]
            orig_name = (p[1] or f"Product {prod_id}").strip()

            # Extract SKU by deleting English prefix from start of name
            khmer_match = re.search(r'[\u1780-\u17FF]', orig_name)
            if khmer_match and khmer_match.start() > 0:
                prefix = orig_name[:khmer_match.start()].strip().rstrip(' -_:/')
                rem = orig_name[khmer_match.start():].strip()
                if prefix and re.search(r'[A-Za-z]', prefix):
                    raw_sku = prefix
                    clean_name = rem
                else:
                    raw_sku = f"SKU-{prod_id:04d}"
                    clean_name = orig_name
            else:
                raw_sku = f"SKU-{prod_id:04d}"
                clean_name = orig_name

            # UOM and Ratios
            base_uom = (p[5] or 'pcs').strip()
            so_uom = (p[23] or '').strip()
            so_ratio_std = float(p[24]) if p[24] is not None else 1.0
            so_ratio = float(p[25]) if p[25] is not None else 1.0
            m_pack = float(p[6]) if p[6] else 1.0

            if so_ratio_std <= 1.0:
                name_pack_match = re.search(r'(\d+)\s*(?:ចាន|ប្រអប់|កែវ|ដប|គ្រាប់|ថង់|កំប៉ុង|សន្លឹក|pcs|ដុំ|គូរ)?\s*[/／]\s*(កេស|Case|Pack|ដុំ|បេ)', orig_name, re.IGNORECASE)
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

            # Purchasing UOM is identical to Sales UOM
            po_uom = so_uom
            po_ratio = so_ratio
            po_ratio_std = so_ratio_std

            pre_processed.append({
                'p': p,
                'prod_id': prod_id,
                'raw_sku': raw_sku,
                'clean_name': clean_name,
                'base_uom': base_uom,
                'so_uom': so_uom,
                'so_ratio': so_ratio,
                'so_ratio_std': so_ratio_std,
                'po_uom': po_uom,
                'po_ratio': po_ratio,
                'po_ratio_std': po_ratio_std
            })

        prod_insert_data = []
        for item in pre_processed:
            p = item['p']
            prod_id = item['prod_id']
            raw_sku = item['raw_sku']
            sku_counter[raw_sku] += 1
            if sku_counter[raw_sku] > 1:
                final_sku = f"{raw_sku}-{sku_counter[raw_sku]}"
            else:
                final_sku = raw_sku

            name = item['clean_name']
            desc = (p[2] or '').strip()
            barcode = (p[3] or '').strip() or None
            cat_id = p[4]
            uom = item['base_uom']
            m_pack = float(p[6]) if p[6] else 1.0
            i_pack = float(p[7]) if p[7] else 1.0
            def_loc = p[8] if p[8] else 100
            reorder_pt = float(p[9]) if p[9] else 0.0
            reorder_qty = float(p[10]) if p[10] else 0.0
            std_cost = float(p[15]) if p[15] else 0.0
            avg_cost = float(p[16]) if p[16] else 0.0
            last_cost = float(p[17]) if p[17] else 0.0
            def_price = float(p[18]) if p[18] else 0.0
            sellable = bool(p[11])
            purchasable = bool(p[12])
            active = bool(p[13])
            item_type = type_map.get(p[19], 'Stockable')
            tax_code = tax_map.get(p[20], 'Taxable')
            costing_method = costing_map.get(p[21], 'Manual')
            img_url = img_dict.get(prod_id)
            custom_attr = f'{{"inflow_prod_id": {prod_id}}}'

            prod_insert_data.append((
                prod_id, final_sku, name, desc, barcode, cat_id, uom,
                m_pack, i_pack, def_loc, reorder_pt, reorder_qty,
                std_cost, avg_cost, last_cost, def_price,
                sellable, purchasable, active,
                item_type, tax_code, costing_method, img_url,
                item['so_uom'], item['so_ratio'], item['so_ratio_std'],
                item['po_uom'], item['po_ratio'], item['po_ratio_std'],
                custom_attr
            ))

        execute_values(pg_cur, """
            INSERT INTO products (
                id, sku, name, description, barcode, category_id, uom,
                master_pack_qty, inner_pack_qty, default_location_id, reorder_point, reorder_quantity,
                standard_cost, average_cost, last_purchase_cost, default_price,
                is_sellable, is_purchaseable, is_active,
                item_type, tax_code, costing_method, image_url,
                sales_uom, sales_uom_ratio, sales_uom_ratio_std,
                purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
                custom_attributes
            ) VALUES %s
        """, prod_insert_data, template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)")
        stats['products'] = len(prod_rows)
        logger.info(f"Inserted {stats['products']} products.")

        # 4b. Product Prices by Scheme
        mssql_cur.execute("SELECT ProdId, PricingSchemeId, UnitPrice FROM BASE_ItemPrice WHERE UnitPrice > 0")
        price_rows = mssql_cur.fetchall()
        price_insert_data = [(r[0], r[1], float(r[2])) for r in price_rows]
        if price_insert_data:
            execute_values(pg_cur, """
                INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                VALUES %s
            """, price_insert_data)
        stats['product_prices'] = len(price_rows)

        # 4c. Product Version History
        mssql_cur.execute("""
            SELECT pv.ProdId, pv.Version, pv.Name, ISNULL(pv.LastPurchasePrice, 0), pv.DateUpdated
            FROM BASE_Product_Version pv
            JOIN BASE_Product p ON pv.ProdId = p.ProdId
            ORDER BY pv.ProdId, pv.Version
        """)
        ver_rows = mssql_cur.fetchall()
        ver_insert_data = [
            (r[0], r[1], r[2], float(r[3] or 0), 'Migrated legacy revision from inFlow SQL Server', r[4] or datetime.now())
            for r in ver_rows
        ]
        if ver_insert_data:
            execute_values(pg_cur, """
                INSERT INTO product_versions (product_id, version_number, name, standard_cost, change_summary, created_at)
                VALUES %s
            """, ver_insert_data)
        stats['product_versions'] = len(ver_rows)

        # 4d. Product Vendors Catalog (BASE_VendorItem)
        mssql_cur.execute("""
            SELECT ProdId, VendorId, VendorItemCode, Cost
            FROM BASE_VendorItem
            WHERE ProdId IS NOT NULL AND VendorId IS NOT NULL
        """)
        vi_rows = mssql_cur.fetchall()
        vi_insert_data = [(r[0], r[1], (r[2] or '').strip(), float(r[3] or 0)) for r in vi_rows]
        if vi_insert_data:
            execute_values(pg_cur, """
                INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost)
                VALUES %s
            """, vi_insert_data)
        stats['product_vendors'] = len(vi_rows)

        # 4e. Inventory Stock Levels
        mssql_cur.execute("""
            SELECT ProdId, LocationId, ISNULL(Sublocation, ''), ISNULL(Quantity, 0)
            FROM BASE_Inventory
        """)
        inv_rows = mssql_cur.fetchall()
        inv_insert_data = [(r[0], r[1], r[2] or '', float(r[3])) for r in inv_rows]
        if inv_insert_data:
            execute_values(pg_cur, """
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES %s
            """, inv_insert_data)
        stats['inventory'] = len(inv_rows)
        logger.info(f"Synchronized product sub-tables: {stats['product_prices']} prices, {stats['product_versions']} versions, {stats['product_vendors']} vendor items, {stats['inventory']} stock records.")

        # -------------------------------------------------------------
        # STEP 5: SYNC CUSTOMERS CRM (HQ)
        # -------------------------------------------------------------
        logger.info("STEP 5: Importing Customer List from inFlow for HQ...")
        mssql_cur.execute("""
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
            ORDER BY c.CustomerId;
        """)
        cust_rows = mssql_cur.fetchall()
        cust_insert_data = []
        for c in cust_rows:
            cust_id = c[0]
            cname = (c[1] or f"Customer {cust_id}").strip()
            contact = (c[2] or '').strip()
            phone = (c[3] or '').strip()
            fax = (c[4] or '').strip()
            email = (c[5] or '').strip()
            addr1 = (c[6] or '').strip()
            addr2 = (c[7] or '').strip()
            city = (c[8] or '').strip()
            state = (c[9] or '').strip()
            country = (c[10] or 'Cambodia').strip() or 'Cambodia'
            postal = (c[11] or '').strip()
            billing = (c[12] or addr1).strip()
            shipping = (c[13] or addr1).strip()
            scheme_id = c[14]
            disc = float(c[15] or 0)
            active = bool(c[16])
            website = (c[17] or '').strip()
            balance = float(c[18] or 0)

            # branch_id is NULL for HQ!
            cust_insert_data.append((
                cust_id, cname, contact, phone, fax, email,
                addr1, addr2, city, state, country, postal,
                billing, shipping, scheme_id, disc,
                active, website, balance, None
            ))

        execute_values(pg_cur, """
            INSERT INTO customers (
                id, name, contact_name, phone, fax, email,
                address1, address2, city, state, country, postal_code,
                billing_address, shipping_address, default_pricing_scheme_id, discount_percent,
                is_active, website, balance, branch_id
            ) VALUES %s
        """, cust_insert_data)
        stats['customers'] = len(cust_rows)
        logger.info(f"Inserted {stats['customers']} HQ customers.")

        # -------------------------------------------------------------
        # STEP 6: SYNC PURCHASE ORDERS & LINES & PAYMENTS (HQ)
        # -------------------------------------------------------------
        logger.info("STEP 6: Importing Purchase Orders & Lines from inFlow for HQ...")
        mssql_cur.execute("""
            SELECT 
                po.PurchaseOrderId, po.OrderNumber, po.VendorId, po.LocationId, 
                po.OrderDate, po.DueDate, po.RequestShipDate, po.OrderStatus,
                po.OrderSubTotal, po.OrderTax1 + po.OrderTax2 as TaxAmount, po.OrderExtra as Freight,
                po.OrderTotal, po.AmountPaid, po.PaymentBalance, 
                po.ContactName, po.Phone, po.VendorAddress1, po.Carrier, 
                po.VendorOrderNumber, po.AncillaryExpenses, po.OrderRemarks
            FROM PO_PurchaseOrder po
            ORDER BY po.PurchaseOrderId
        """)
        po_rows = mssql_cur.fetchall()
        po_status_map = {1: 'ISSUED', 2: 'ISSUED', 5: 'RECEIVED', 6: 'PAID', 10: 'CANCELLED'}

        po_insert_data = []
        for po in po_rows:
            p_id = po[0]
            ord_num = (po[1] or f"PO-{p_id:06d}").strip()
            vend_id = po[2]
            loc_id = po[3] or 100
            ord_date = po[4].date() if po[4] else datetime.now().date()
            due_date = po[5].date() if po[5] else (po[6].date() if po[6] else None)
            st = po_status_map.get(po[7], 'ISSUED')

            subtotal = float(po[8] or 0)
            tax_amt = float(po[9] or 0)
            freight = float(po[10] or 0)
            total_amt = float(po[11] or 0)
            paid_amt = float(po[12] or 0)
            balance_due = float(po[13] or 0)

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

            # branch_id is NULL for HQ!
            po_insert_data.append((
                p_id, ord_num, vend_id, loc_id, ord_date, due_date,
                st, pay_st, subtotal, tax_amt, freight, total_amt, paid_amt, balance_due,
                contact, phone, addr, carrier, vendor_inv, non_vendor, 'USD', notes, None
            ))

        execute_values(pg_cur, """
            INSERT INTO purchase_orders (
                id, order_number, vendor_id, location_id, order_date, expected_date,
                status, payment_status, subtotal, tax_amount, shipping_fee, total_amount, paid_amount, balance_due,
                contact, phone, vendor_address, carrier, vendor_invoice_no, non_vendor_costs, currency_code, notes, branch_id
            ) VALUES %s
        """, po_insert_data)
        stats['purchase_orders'] = len(po_rows)

        # 6b. PO Lines (with receipts from PO_PurchaseOrderReceive_Line)
        mssql_cur.execute("""
            SELECT PurchaseOrderId, LineNum, SUM(Quantity) as RecvQty
            FROM PO_PurchaseOrderReceive_Line
            WHERE IsReceived = 1
            GROUP BY PurchaseOrderId, LineNum;
        """)
        recv_dict = {}
        for r in mssql_cur.fetchall():
            recv_dict[(r[0], r[1])] = float(r[2] or 0)

        mssql_cur.execute("""
            SELECT 
                pol.PurchaseOrderLineId, pol.PurchaseOrderId, pol.LineNum, pol.ProdId,
                pol.Description, pol.VendorItemCode, pol.Quantity, pol.UnitPrice, pol.Discount, pol.SubTotal,
                p.Name as ProductName
            FROM PO_PurchaseOrder_Line pol
            LEFT JOIN BASE_Product p ON pol.ProdId = p.ProdId
            ORDER BY pol.PurchaseOrderId, pol.LineNum
        """)
        po_line_rows = mssql_cur.fetchall()
        po_lines_insert = []
        for pol in po_line_rows:
            lid = pol[0]
            po_id = pol[1]
            line_num = pol[2]
            prod_id = pol[3]
            inflow_desc = (pol[4] or '').strip()
            vendor_code = (pol[5] or '').strip()
            qty = float(pol[6] or 0)
            cost = float(pol[7] or 0)
            disc = float(pol[8] or 0)
            subtot = float(pol[9] or 0)
            prod_name = (pol[10] or '').strip()

            final_desc = inflow_desc if inflow_desc else prod_name
            actual_recv = recv_dict.get((po_id, line_num), qty)

            po_lines_insert.append((
                lid, po_id, line_num, prod_id, final_desc, vendor_code,
                qty, cost, disc, subtot, actual_recv
            ))

        execute_values(pg_cur, """
            INSERT INTO purchase_order_lines (
                id, purchase_order_id, line_num, product_id, description, vendor_product_code,
                quantity, unit_cost, discount_percent, subtotal, received_qty
            ) VALUES %s
        """, po_lines_insert)
        stats['purchase_order_lines'] = len(po_line_rows)

        # 6c. PO Payments (PO_PurchaseOrderMoneyPayment_Line)
        mssql_cur.execute("""
            SELECT 
                PurchaseOrderId, DatePaid,
                PaymentMethod, ReferenceNumber, Remarks, Amount
            FROM PO_PurchaseOrderMoneyPayment_Line
            WHERE Amount IS NOT NULL AND Amount > 0
            ORDER BY PurchaseOrderId, DatePaid;
        """)
        po_pay_rows = mssql_cur.fetchall()
        po_pay_insert = []
        for pr in po_pay_rows:
            p_order_id = pr[0]
            p_date = pr[1] or datetime.now()
            p_method = (pr[2] or 'Bank Transfer').strip() or 'Bank Transfer'
            p_ref = (pr[3] or '').strip()
            p_rem = (pr[4] or '').strip()
            p_amt = float(pr[5] or 0)
            po_pay_insert.append((
                'PO', p_order_id, p_amt, p_method, p_date, p_ref, p_rem, None
            ))

        if po_pay_insert:
            execute_values(pg_cur, """
                INSERT INTO order_payments (
                    order_type, order_id, amount, payment_method, payment_date, reference, notes, branch_id
                ) VALUES %s
            """, po_pay_insert)
        stats['po_payments'] = len(po_pay_rows)
        logger.info(f"Inserted {stats['purchase_orders']} purchase orders, {stats['purchase_order_lines']} lines, {stats['po_payments']} payments.")

        # -------------------------------------------------------------
        # STEP 7: SYNC SALES ORDERS & LINES & PAYMENTS (HQ)
        # -------------------------------------------------------------
        logger.info("STEP 7: Importing Sales Orders & Lines from inFlow for HQ...")
        mssql_cur.execute("""
            SELECT 
                so.SalesOrderId, so.OrderNumber, so.CustomerId, so.LocationId, so.OrderDate, so.DueDate, so.OrderStatus,
                so.OrderSubTotal, so.OrderTax1 + so.OrderTax2 as TaxAmount, so.OrderTotal, so.AmountPaid, so.InvoiceBalance,
                so.SalesRep, so.OrderRemarks, so.PickedDate, so.PackedDate, so.InvoicedDate,
                so.ContactName, so.Phone, so.ShippingAddress1, so.ShippingCity, so.PricingSchemeId, so.PONumber
            FROM SO_SalesOrder so
            ORDER BY so.SalesOrderId
        """)
        so_rows = mssql_cur.fetchall()
        so_status_map = {1: 'QUOTE', 2: 'OPEN', 4: 'PICKED', 5: 'PACKED', 6: 'INVOICED', 10: 'CANCELLED'}

        so_insert_data = []
        for so in so_rows:
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
            if tot_amt > 0 and bal_due <= 0:
                pay_st = 'PAID'
            elif paid_amt > 0:
                pay_st = 'PARTIAL'
            else:
                pay_st = 'UNPAID'

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

            # branch_id is NULL for HQ!
            so_insert_data.append((
                s_id, ord_num, cust_id, loc_id, so_date, due_dt,
                st, pay_st, float(so[7] or 0), float(so[8] or 0), tot_amt, paid_amt, bal_due,
                sales_rep, notes, picked_dt, packed_dt, invoiced_dt,
                contact, phone, ship_addr, ship_city, scheme_id, po_num, None
            ))

        chunk_size = 5000
        logger.info(f"Inserting {len(so_insert_data)} sales orders in chunks of {chunk_size}...")
        for i in range(0, len(so_insert_data), chunk_size):
            chunk = so_insert_data[i:i + chunk_size]
            execute_values(pg_cur, """
                INSERT INTO sales_orders (
                    id, order_number, customer_id, location_id, order_date, due_date,
                    status, payment_status, subtotal, tax_amount, total_amount, paid_amount, balance_due,
                    sales_rep, notes, picked_date, packed_date, invoiced_date,
                    customer_contact, customer_phone, customer_address, destination_province, pricing_scheme_id, po_number, branch_id
                ) VALUES %s
            """, chunk)
        stats['sales_orders'] = len(so_rows)

        # 7b. Sales Order Lines
        logger.info("Fetching Sales Order Lines from inFlow...")
        mssql_cur.execute("""
            SELECT 
                sol.SalesOrderLineId, sol.SalesOrderId, sol.LineNum, sol.ProdId, sol.Description,
                sol.Quantity, sol.UnitPrice, sol.Discount, sol.SubTotal, sol.QuantityUom, sol.QuantityDisplay,
                p.Name as ProductName, ISNULL(c.StandardCost, ISNULL(c.AverageCost, 0)) as CostPrice
            FROM SO_SalesOrder_Line sol
            JOIN BASE_Product p ON sol.ProdId = p.ProdId
            LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
            ORDER BY sol.SalesOrderId, sol.LineNum
        """)
        sol_rows = mssql_cur.fetchall()
        sol_insert_data = []
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
            q_disp = (str(sol[10]).strip() if sol[10] is not None else f"{qty:.2f}")
            prod_name = (str(sol[11]).strip() if sol[11] else '')
            cost_price = float(sol[12] or 0)

            final_desc = inflow_desc if inflow_desc else prod_name

            sol_insert_data.append((
                lid, so_id, line_num, prod_id, final_desc,
                qty, uprice, disc, subtot, cost_price,
                qty, qty, qty, uom, q_disp
            ))

        logger.info(f"Inserting {len(sol_insert_data)} sales order lines in chunks of {chunk_size}...")
        for i in range(0, len(sol_insert_data), chunk_size):
            chunk = sol_insert_data[i:i + chunk_size]
            execute_values(pg_cur, """
                INSERT INTO sales_order_lines (
                    id, sales_order_id, line_num, product_id, description,
                    quantity, unit_price, discount_percent, subtotal, cost_price,
                    picked_qty, packed_qty, shipped_qty, uom, quantity_display
                ) VALUES %s
            """, chunk)
        stats['sales_order_lines'] = len(sol_rows)

        # 7c. Sales Order Payments (SO_SalesOrderPayment_Line)
        logger.info("Fetching Sales Order Payments from inFlow...")
        mssql_cur.execute("""
            SELECT 
                SalesOrderId, DatePaid,
                PaymentMethod, ReferenceNumber, Remarks, Amount
            FROM SO_SalesOrderPayment_Line
            WHERE Amount IS NOT NULL AND Amount > 0
            ORDER BY SalesOrderId, DatePaid;
        """)
        so_pay_rows = mssql_cur.fetchall()
        so_pay_insert = []
        for pr in so_pay_rows:
            s_order_id = pr[0]
            p_date = pr[1] or datetime.now()
            p_method = (pr[2] or 'Cash').strip() or 'Cash'
            p_ref = (pr[3] or '').strip()
            p_rem = (pr[4] or '').strip()
            p_amt = float(pr[5] or 0)
            so_pay_insert.append((
                'SO', s_order_id, p_amt, p_method, p_date, p_ref, p_rem, None
            ))

        logger.info(f"Inserting {len(so_pay_insert)} sales order payments in chunks of {chunk_size}...")
        for i in range(0, len(so_pay_insert), chunk_size):
            chunk = so_pay_insert[i:i + chunk_size]
            execute_values(pg_cur, """
                INSERT INTO order_payments (
                    order_type, order_id, amount, payment_method, payment_date, reference, notes, branch_id
                ) VALUES %s
            """, chunk)
        stats['so_payments'] = len(so_pay_rows)
        logger.info(f"Inserted {stats['sales_orders']} sales orders, {stats['sales_order_lines']} lines, {stats['so_payments']} payments.")

        # -------------------------------------------------------------
        # STEP 8: RESYNC AUTO-INCREMENT SEQUENCES
        # -------------------------------------------------------------
        logger.info("STEP 8: Resetting all PostgreSQL serial sequences...")
        pg_cur.execute("""
            DO $$
            DECLARE
                t text;
                s text;
                m bigint;
            BEGIN
                FOR t IN SELECT unnest(ARRAY[
                    'categories', 'locations', 'pricing_schemes', 'vendors',
                    'products', 'product_prices', 'product_versions', 'product_vendors', 'inventory',
                    'customers', 'purchase_orders', 'purchase_order_lines',
                    'sales_orders', 'sales_order_lines', 'order_payments'
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

        # Also update custom sequences if present
        pg_cur.execute("""
            DO $$
            DECLARE
                m_so bigint;
                m_po bigint;
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = 'so_number_seq') THEN
                    SELECT COALESCE(MAX(id), 0) FROM sales_orders INTO m_so;
                    IF m_so > 0 THEN
                        PERFORM setval('so_number_seq', m_so, true);
                    END IF;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = 'po_number_seq') THEN
                    SELECT COALESCE(MAX(id), 0) FROM purchase_orders INTO m_po;
                    IF m_po > 0 THEN
                        PERFORM setval('po_number_seq', m_po, true);
                    END IF;
                END IF;
            END $$;
        """)

        # Commit all changes to PostgreSQL!
        pg_conn.commit()
        stats['duration_seconds'] = round(time.time() - start_time, 2)
        logger.info(f"ETL completed in {stats['duration_seconds']} seconds!")
        return stats

    except Exception as e:
        pg_conn.rollback()
        logger.error(f"FATAL ERROR during ETL: {e}", exc_info=True)
        raise
    finally:
        mssql_cur.close()
        mssql_conn.close()
        pg_cur.close()
        pg_conn.close()

if __name__ == '__main__':
    res = sync_hq()
    print("\n=========================================================")
    print("        HQ DATABASE UPDATE COMPLETED SUCCESSFULLY        ")
    print("=========================================================")
    for k, v in res.items():
        print(f"  {k:22}: {v}")
    print("=========================================================\n")
