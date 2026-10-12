import sys
import logging
import time
from datetime import datetime
try:
    import pyodbc
except ImportError:
    pyodbc = None
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from config import Config
from database import init_db

# Configure stdout for Unicode / Khmer text
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('inflow.migrate')

def get_sqlserver_connection():
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed in this environment. SQL Server migration requires a local Windows environment with pyodbc.")
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

def migrate_all(limit_orders=None, progress_callback=None):
    """
    Complete ETL migration pipeline from legacy inFlow SQL Server to PostgreSQL inflow_premium.
    """
    start_time = time.time()
    logger.info("Starting inFlow to inFlow Premium migration...")
    
    init_db()

    stats = {
        'company': 0,
        'categories': 0,
        'locations': 0,
        'pricing_schemes': 0,
        'products': 0,
        'product_prices': 0,
        'product_versions': 0,
        'product_vendors': 0,
        'inventory': 0,
        'customers': 0,
        'vendors': 0,
        'purchase_orders': 0,
        'purchase_order_lines': 0,
        'sales_orders': 0,
        'sales_order_lines': 0,
        'duration_seconds': 0
    }

    try:
        mssql_conn = get_sqlserver_connection()
        mssql_cur = mssql_conn.cursor()
    except Exception as e:
        logger.error(f"Cannot connect to SQL Server: {e}")
        raise RuntimeError(f"Failed to connect to legacy inFlow SQL Server: {e}")

    pg_conn = get_pg_connection()
    pg_cur = pg_conn.cursor()

    try:
        # 1. Company Profile
        if progress_callback: progress_callback("Migrating Company Information...", 5)
        logger.info("Migrating Company...")
        mssql_cur.execute("""
            SELECT TOP 1 CompanyId, Name, Phone, Fax, Email, Website, Address1, Address2, City, State, Country, PostalCode, TaxNumber
            FROM BASE_Company
        """)
        comp_row = mssql_cur.fetchone()
        if comp_row:
            pg_cur.execute("""
                INSERT INTO companies (id, name, phone, fax, email, website, address1, address2, city, state, country, postal_code, tax_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    phone = EXCLUDED.phone,
                    email = EXCLUDED.email,
                    address1 = EXCLUDED.address1;
            """, (
                comp_row[0], comp_row[1] or 'inFlow Premium Wholesale', comp_row[2], comp_row[3],
                comp_row[4], comp_row[5], comp_row[6], comp_row[7], comp_row[8],
                comp_row[9], comp_row[10] or 'Cambodia', comp_row[11], comp_row[12]
            ))
            stats['company'] = 1

        # 2. Categories (Two-pass to handle arbitrary parent-child ordering)
        if progress_callback: progress_callback("Migrating Categories...", 10)
        logger.info("Migrating Categories...")
        mssql_cur.execute("SELECT CategoryId, Name, ParentCategoryId, IsActive FROM BASE_Category ORDER BY CategoryId")
        cat_rows = mssql_cur.fetchall()
        for cat in cat_rows:
            pg_cur.execute("""
                INSERT INTO categories (id, name, parent_id, is_active)
                VALUES (%s, %s, NULL, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active;
            """, (cat[0], cat[1], bool(cat[3])))
        
        # Second pass: Link parent categories
        for cat in cat_rows:
            if cat[2] and cat[2] != cat[0]:
                pg_cur.execute("""
                    UPDATE categories SET parent_id = %s WHERE id = %s;
                """, (cat[2], cat[0]))
        stats['categories'] = len(cat_rows)

        # 3. Locations
        if progress_callback: progress_callback("Migrating Warehouses & Locations...", 15)
        logger.info("Migrating Locations...")
        mssql_cur.execute("SELECT LocationId, Name, IsActive, IsSpecialRecord FROM BASE_Location ORDER BY LocationId")
        loc_rows = mssql_cur.fetchall()
        for loc in loc_rows:
            is_def = (loc[0] == 100) # 100 is Main Warehouse in inFlow
            pg_cur.execute("""
                INSERT INTO locations (id, name, is_active, is_default)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    is_default = EXCLUDED.is_default;
            """, (loc[0], loc[1], bool(loc[2]), is_def))
        stats['locations'] = len(loc_rows)

        # 4. Pricing Schemes
        if progress_callback: progress_callback("Migrating Pricing Schemes...", 20)
        logger.info("Migrating Pricing Schemes...")
        mssql_cur.execute("SELECT PricingSchemeId, Name, IsActive FROM BASE_PricingScheme ORDER BY PricingSchemeId")
        scheme_rows = mssql_cur.fetchall()
        for s in scheme_rows:
            pg_cur.execute("""
                INSERT INTO pricing_schemes (id, name, is_active, is_default)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active;
            """, (s[0], s[1], bool(s[2]), s[0] == 1))
        stats['pricing_schemes'] = len(scheme_rows)

        # 5. Products Master (with costs from BASE_InventoryCost and default prices)
        if progress_callback: progress_callback("Migrating Products Master Catalog...", 30)
        logger.info("Migrating Products...")
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
                p.PictureFileAttachmentId
            FROM BASE_Product p
            LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
            LEFT JOIN BASE_ItemPrice pr ON p.ProdId = pr.ProdId AND pr.PricingSchemeId = 1
            ORDER BY p.ProdId
        """)
        prod_rows = mssql_cur.fetchall()
        
        # Pre-fetch pictures from BASE_FileAttachment
        import os
        img_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'products')
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

        type_map = {1: 'Stockable', 2: 'Non-Stocked', 3: 'Service'}
        tax_map = {100: 'Taxable', 101: 'Non-Taxable'}
        costing_map = {1: 'Manual', 2: 'Average', 3: 'Standard', 4: 'FIFO'}

        prod_insert_data = []
        for p in prod_rows:
            prod_id = p[0]
            sku = f"SKU-{prod_id:04d}"
            name = p[1].strip() if p[1] else f"Product {prod_id}"
            desc = p[2]
            barcode = p[3] if p[3] else None
            cat_id = p[4]
            uom = p[5] if p[5] else 'pcs'
            m_pack = float(p[6]) if p[6] else 1.0
            i_pack = float(p[7]) if p[7] else 1.0
            def_loc = p[8] if p[8] else 100
            reorder_pt = float(p[9]) if p[9] else 0.0
            reorder_qty = float(p[10]) if p[10] else 0.0
            sellable = bool(p[11])
            purchasable = bool(p[12])
            active = bool(p[13])
            std_cost = float(p[15]) if p[15] else 0.0
            avg_cost = float(p[16]) if p[16] else 0.0
            last_cost = float(p[17]) if p[17] else 0.0
            def_price = float(p[18]) if p[18] else 0.0
            item_type = type_map.get(p[19], 'Stockable')
            tax_code = tax_map.get(p[20], 'Taxable')
            costing_method = costing_map.get(p[21], 'Manual')
            img_url = img_dict.get(prod_id)

            prod_insert_data.append((
                prod_id, sku, name, desc, barcode, cat_id, uom,
                m_pack, i_pack, def_loc, reorder_pt, reorder_qty,
                std_cost, avg_cost, last_cost, def_price,
                sellable, purchasable, active,
                item_type, tax_code, costing_method, img_url
            ))

        execute_values(pg_cur, """
            INSERT INTO products (
                id, sku, name, description, barcode, category_id, uom,
                master_pack_qty, inner_pack_qty, default_location_id, reorder_point, reorder_quantity,
                standard_cost, average_cost, last_purchase_cost, default_price,
                is_sellable, is_purchaseable, is_active,
                item_type, tax_code, costing_method, image_url
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                sku = EXCLUDED.sku,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                barcode = EXCLUDED.barcode,
                category_id = EXCLUDED.category_id,
                uom = EXCLUDED.uom,
                master_pack_qty = EXCLUDED.master_pack_qty,
                inner_pack_qty = EXCLUDED.inner_pack_qty,
                default_location_id = EXCLUDED.default_location_id,
                reorder_point = EXCLUDED.reorder_point,
                reorder_quantity = EXCLUDED.reorder_quantity,
                standard_cost = EXCLUDED.standard_cost,
                average_cost = EXCLUDED.average_cost,
                last_purchase_cost = EXCLUDED.last_purchase_cost,
                default_price = EXCLUDED.default_price,
                is_sellable = EXCLUDED.is_sellable,
                is_purchaseable = EXCLUDED.is_purchaseable,
                is_active = EXCLUDED.is_active,
                item_type = EXCLUDED.item_type,
                tax_code = EXCLUDED.tax_code,
                costing_method = EXCLUDED.costing_method,
                image_url = COALESCE(EXCLUDED.image_url, products.image_url);
        """, prod_insert_data)
        stats['products'] = len(prod_rows)

        # 6. Product Prices (by scheme)
        if progress_callback: progress_callback("Migrating Pricing Tiers...", 40)
        logger.info("Migrating Product Prices...")
        mssql_cur.execute("SELECT ProdId, PricingSchemeId, UnitPrice FROM BASE_ItemPrice WHERE UnitPrice > 0")
        price_rows = mssql_cur.fetchall()
        price_insert_data = [(r[0], r[1], float(r[2])) for r in price_rows]
        if price_insert_data:
            execute_values(pg_cur, """
                INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                VALUES %s
                ON CONFLICT (product_id, pricing_scheme_id) DO UPDATE SET
                    unit_price = EXCLUDED.unit_price;
            """, price_insert_data)
        stats['product_prices'] = len(price_rows)

        # 6b. Product Version History
        logger.info("Migrating Product Version Revisions...")
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
                ON CONFLICT DO NOTHING;
            """, ver_insert_data)
        stats['product_versions'] = len(ver_rows)

        # 7. Inventory Stock Levels
        if progress_callback: progress_callback("Migrating Real-time Stock Levels...", 50)
        logger.info("Migrating Inventory Stocks...")
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
                ON CONFLICT (product_id, location_id, sublocation) DO UPDATE SET
                    quantity = EXCLUDED.quantity;
            """, inv_insert_data)
        stats['inventory'] = len(inv_rows)

        # 8. Customers
        if progress_callback: progress_callback("Migrating Customers CRM...", 60)
        logger.info("Migrating Customers...")
        mssql_cur.execute("""
            SELECT 
                CustomerId, Name, ContactName, Phone, Email,
                BillingAddress1, BillingAddress2, BillingCity, BillingState, BillingCountry, BillingPostalCode,
                ShippingAddress1, DefaultPricingSchemeId, Discount, IsActive
            FROM BASE_Customer
            ORDER BY CustomerId
        """)
        cust_rows = mssql_cur.fetchall()
        cust_insert_data = []
        for c in cust_rows:
            cust_insert_data.append((
                c[0], c[1] or f"Customer {c[0]}", c[2], c[3], c[4],
                c[5], c[6], c[7], c[8], c[9] or 'Cambodia', c[10],
                c[11], c[12], float(c[13]) if c[13] else 0.0, bool(c[14])
            ))
        execute_values(pg_cur, """
            INSERT INTO customers (
                id, name, contact_name, phone, email,
                address1, address2, city, state, country, postal_code,
                shipping_address, default_pricing_scheme_id, discount_percent, is_active
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                contact_name = EXCLUDED.contact_name,
                phone = EXCLUDED.phone,
                email = EXCLUDED.email,
                address1 = EXCLUDED.address1,
                city = EXCLUDED.city,
                default_pricing_scheme_id = EXCLUDED.default_pricing_scheme_id,
                discount_percent = EXCLUDED.discount_percent,
                is_active = EXCLUDED.is_active;
        """, cust_insert_data)
        stats['customers'] = len(cust_rows)

        # 9. Vendors
        if progress_callback: progress_callback("Migrating Vendors / Suppliers...", 70)
        logger.info("Migrating Vendors...")
        mssql_cur.execute("""
            SELECT 
                VendorId, Name, ContactName, Phone, Email, Address1, Address2, City, Country, PostalCode, IsActive
            FROM BASE_Vendor
            ORDER BY VendorId
        """)
        vend_rows = mssql_cur.fetchall()
        vend_insert_data = []
        for v in vend_rows:
            vend_insert_data.append((
                v[0], v[1] or f"Vendor {v[0]}", v[2], v[3], v[4],
                v[5], v[6], v[7], v[8] or 'Cambodia', v[9], bool(v[10])
            ))
        execute_values(pg_cur, """
            INSERT INTO vendors (
                id, name, contact_name, phone, email, address1, address2, city, country, postal_code, is_active
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                contact_name = EXCLUDED.contact_name,
                phone = EXCLUDED.phone,
                email = EXCLUDED.email,
                address1 = EXCLUDED.address1,
                is_active = EXCLUDED.is_active;
        """, vend_insert_data)
        stats['vendors'] = len(vend_rows)

        # 9b. Product Vendors Catalog (BASE_VendorItem)
        logger.info("Migrating Product Vendors...")
        mssql_cur.execute("""
            SELECT ProdId, VendorId, VendorItemCode, Cost
            FROM BASE_VendorItem
            WHERE ProdId IS NOT NULL AND VendorId IS NOT NULL
        """)
        vi_rows = mssql_cur.fetchall()
        vi_insert_data = [(r[0], r[1], r[2], float(r[3] or 0)) for r in vi_rows]
        if vi_insert_data:
            execute_values(pg_cur, """
                INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost)
                VALUES %s
                ON CONFLICT (product_id, vendor_id) DO UPDATE SET
                    vendor_item_code = EXCLUDED.vendor_item_code,
                    cost = EXCLUDED.cost;
            """, vi_insert_data)
        stats['product_vendors'] = len(vi_rows)

        # 10. Purchase Orders & Lines
        if progress_callback: progress_callback("Migrating Purchase Orders...", 75)
        logger.info("Migrating Purchase Orders...")
        mssql_cur.execute("""
            SELECT 
                PurchaseOrderId, OrderNumber, VendorId, LocationId, OrderDate, DueDate, OrderStatus,
                OrderSubTotal, OrderTax1 + OrderTax2 as TaxAmount, OrderTotal, AmountPaid, PaymentBalance, OrderRemarks
            FROM PO_PurchaseOrder
            ORDER BY PurchaseOrderId
        """)
        po_rows = mssql_cur.fetchall()
        po_status_map = {1: 'DRAFT', 2: 'ISSUED', 5: 'RECEIVED', 6: 'PAID', 10: 'CANCELLED'}
        po_insert_data = []
        for po in po_rows:
            st = po_status_map.get(po[6], 'ISSUED')
            paid_amt = float(po[10]) if po[10] else 0.0
            tot_amt = float(po[9]) if po[9] else 0.0
            bal_due = float(po[11]) if po[11] else 0.0
            pay_st = 'PAID' if (tot_amt > 0 and bal_due <= 0) else ('PARTIAL' if paid_amt > 0 else 'UNPAID')
            po_date = po[4].date() if po[4] else datetime.now().date()
            due_dt = po[5].date() if po[5] else None

            po_insert_data.append((
                po[0], po[1] or f"PO-{po[0]}", po[2], po[3] or 100, po_date, due_dt,
                st, pay_st, float(po[7] or 0), float(po[8] or 0), tot_amt, paid_amt, bal_due, po[12]
            ))
        execute_values(pg_cur, """
            INSERT INTO purchase_orders (
                id, order_number, vendor_id, location_id, order_date, expected_date,
                status, payment_status, subtotal, tax_amount, total_amount, paid_amount, balance_due, notes
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                order_number = EXCLUDED.order_number,
                vendor_id = EXCLUDED.vendor_id,
                location_id = EXCLUDED.location_id,
                status = EXCLUDED.status,
                payment_status = EXCLUDED.payment_status,
                total_amount = EXCLUDED.total_amount,
                paid_amount = EXCLUDED.paid_amount,
                balance_due = EXCLUDED.balance_due;
        """, po_insert_data)
        stats['purchase_orders'] = len(po_rows)

        # PO Lines
        logger.info("Migrating Purchase Order Lines...")
        mssql_cur.execute("""
            SELECT 
                PurchaseOrderLineId, PurchaseOrderId, LineNum, ProdId, Description, Quantity, UnitPrice, SubTotal
            FROM PO_PurchaseOrder_Line
            WHERE ProdId IN (SELECT ProdId FROM BASE_Product)
            ORDER BY PurchaseOrderId, LineNum
        """)
        po_line_rows = mssql_cur.fetchall()
        po_lines_insert = []
        for pol in po_line_rows:
            qty = float(pol[5] or 0)
            po_lines_insert.append((
                pol[0], pol[1], pol[2], pol[3], pol[4] or '', qty, float(pol[6] or 0), float(pol[7] or 0), qty
            ))
        execute_values(pg_cur, """
            INSERT INTO purchase_order_lines (
                id, purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal, received_qty
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                quantity = EXCLUDED.quantity,
                unit_cost = EXCLUDED.unit_cost,
                subtotal = EXCLUDED.subtotal;
        """, po_lines_insert)
        stats['purchase_order_lines'] = len(po_line_rows)

        # 11. Sales Orders & Lines
        if progress_callback: progress_callback("Migrating Sales Orders & History...", 85)
        logger.info("Migrating Sales Orders...")
        so_query = """
            SELECT 
                SalesOrderId, OrderNumber, CustomerId, LocationId, OrderDate, DueDate, OrderStatus,
                OrderSubTotal, OrderTax1 + OrderTax2 as TaxAmount, OrderTotal, AmountPaid, InvoiceBalance,
                SalesRep, OrderRemarks, PickedDate, PackedDate, InvoicedDate
            FROM SO_SalesOrder
        """
        if limit_orders:
            so_query += f" WHERE SalesOrderId IN (SELECT TOP {limit_orders} SalesOrderId FROM SO_SalesOrder ORDER BY OrderDate DESC)"
        so_query += " ORDER BY SalesOrderId"

        mssql_cur.execute(so_query)
        so_rows = mssql_cur.fetchall()
        so_status_map = {1: 'QUOTE', 2: 'OPEN', 4: 'PICKED', 5: 'PACKED', 6: 'INVOICED', 10: 'CANCELLED'}
        so_insert_data = []
        for so in so_rows:
            st = so_status_map.get(so[6], 'OPEN')
            tot_amt = float(so[9] or 0)
            paid_amt = float(so[10] or 0)
            bal_due = float(so[11] or 0)
            pay_st = 'PAID' if (tot_amt > 0 and bal_due <= 0) else ('PARTIAL' if paid_amt > 0 else 'UNPAID')
            so_date = so[4].date() if so[4] else datetime.now().date()
            due_dt = so[5].date() if so[5] else None

            so_insert_data.append((
                so[0], so[1] or f"SO-{so[0]}", so[2], so[3] or 100, so_date, due_dt,
                st, pay_st, float(so[7] or 0), float(so[8] or 0), tot_amt, paid_amt, bal_due,
                so[12], so[13], so[14], so[15], so[16]
            ))
        
        # Batch insert in chunks of 5000 for maximum throughput
        chunk_size = 5000
        for i in range(0, len(so_insert_data), chunk_size):
            chunk = so_insert_data[i:i + chunk_size]
            execute_values(pg_cur, """
                INSERT INTO sales_orders (
                    id, order_number, customer_id, location_id, order_date, due_date,
                    status, payment_status, subtotal, tax_amount, total_amount, paid_amount, balance_due,
                    sales_rep, notes, picked_date, packed_date, invoiced_date
                ) VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    order_number = EXCLUDED.order_number,
                    customer_id = EXCLUDED.customer_id,
                    location_id = EXCLUDED.location_id,
                    status = EXCLUDED.status,
                    payment_status = EXCLUDED.payment_status,
                    total_amount = EXCLUDED.total_amount,
                    paid_amount = EXCLUDED.paid_amount,
                    balance_due = EXCLUDED.balance_due;
            """, chunk)
        stats['sales_orders'] = len(so_rows)

        # Sales Order Lines
        if progress_callback: progress_callback("Migrating Sales Order Line Items...", 95)
        logger.info("Migrating Sales Order Lines...")
        sol_query = """
            SELECT 
                sol.SalesOrderLineId, sol.SalesOrderId, sol.LineNum, sol.ProdId, sol.Description,
                sol.Quantity, sol.UnitPrice, sol.Discount, sol.SubTotal
            FROM SO_SalesOrder_Line sol
            WHERE sol.ProdId IN (SELECT ProdId FROM BASE_Product)
        """
        if limit_orders:
            sol_query += f" AND sol.SalesOrderId IN (SELECT TOP {limit_orders} SalesOrderId FROM SO_SalesOrder ORDER BY OrderDate DESC)"
        sol_query += " ORDER BY sol.SalesOrderId, sol.LineNum"

        mssql_cur.execute(sol_query)
        sol_rows = mssql_cur.fetchall()
        sol_insert_data = []
        for sol in sol_rows:
            qty = float(sol[5] or 0)
            sol_insert_data.append((
                sol[0], sol[1], sol[2], sol[3], sol[4] or '', qty, float(sol[6] or 0),
                float(sol[7] or 0), float(sol[8] or 0), qty, qty, qty
            ))
        
        for i in range(0, len(sol_insert_data), chunk_size):
            chunk = sol_insert_data[i:i + chunk_size]
            execute_values(pg_cur, """
                INSERT INTO sales_order_lines (
                    id, sales_order_id, line_num, product_id, description,
                    quantity, unit_price, discount_percent, subtotal,
                    picked_qty, packed_qty, shipped_qty
                ) VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    unit_price = EXCLUDED.unit_price,
                    discount_percent = EXCLUDED.discount_percent,
                    subtotal = EXCLUDED.subtotal;
            """, chunk)
        stats['sales_order_lines'] = len(sol_rows)

        # 12. Reset auto-increment sequences so subsequent creates work seamlessly!
        pg_cur.execute("""
            DO $$
            DECLARE
                t text;
                s text;
                m bigint;
            BEGIN
                FOR t IN SELECT unnest(ARRAY['companies', 'categories', 'locations', 'pricing_schemes', 'products', 'customers', 'vendors', 'purchase_orders', 'purchase_order_lines', 'sales_orders', 'sales_order_lines']) LOOP
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

        # Commit all changes to PostgreSQL
        pg_conn.commit()
        stats['duration_seconds'] = round(time.time() - start_time, 2)
        logger.info(f"Migration completed in {stats['duration_seconds']} seconds! Stats: {stats}")
        if progress_callback: progress_callback("Migration successfully completed!", 100)
        return stats

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
    print("=========================================================")
    print("   inFlow Premium: Legacy SQL Server -> PostgreSQL ETL   ")
    print("=========================================================")
    res = migrate_all()
    print("\n--- Migration Results Summary ---")
    for k, v in res.items():
        print(f"  {k:22}: {v}")
    print("=========================================================")
