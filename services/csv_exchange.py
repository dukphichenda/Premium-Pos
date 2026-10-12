import csv
import io
import re
import logging
from datetime import datetime
import dateutil.parser
from database import query_all, query_one, execute, execute_returning_id, get_db_cursor

logger = logging.getLogger('inflow.csv_exchange')

DATA_TYPES_META = {
    'product': {
        'display_name': 'Product',
        'default_filename': 'inFlow_Product.csv',
        'description': 'Import product information, including item name/code, description, price, cost, etc., but not inventory/stock on hand.',
        'export_description': 'Export your product information, including item name/code, description, price, cost, barcode, etc.',
        'headers': ['Item Code', 'Item Name', 'Description', 'Category', 'Barcode', 'Default Price', 'Standard Cost', 'UOM', 'Remarks'],
        'sample_row': ['A1600-QP', 'Paper Box 1600ML', 'Paper Box 1600ML with transparent lid', 'Packaging', '8850123456789', '12.00', '8.50', 'pcs', 'Food grade material']
    },
    'customer': {
        'display_name': 'Customer',
        'default_filename': 'inFlow_Customer.csv',
        'description': 'Import customer information, including customer name, contact person, phone, email, address, etc.',
        'export_description': 'Export your customers, including contact information, addresses, phone numbers, and balances.',
        'headers': ['Customer Name', 'Contact Name', 'Phone', 'Email', 'Address', 'City', 'Country', 'Payment Terms', 'Remarks'],
        'sample_row': ['Angkor Supermarket', 'Mr. Sokha', '+855 12 345 678', 'sokha@angkor-market.com', '#124 Street 271, Toul Kork', 'Phnom Penh', 'Cambodia', 'Due on Receipt', 'VIP Wholesale Customer']
    },
    'vendor': {
        'display_name': 'Vendor',
        'default_filename': 'inFlow_Vendor.csv',
        'description': 'Import vendor/supplier details including company name, contact, phone, email, and address.',
        'export_description': 'Export your vendors and suppliers, including contact information and payment terms.',
        'headers': ['Vendor Name', 'Contact Name', 'Phone', 'Email', 'Address', 'Payment Terms'],
        'sample_row': ['Asia Packaging Co., Ltd', 'Ms. Lin', '+855 23 888 999', 'orders@asiapack.com', 'Russian Blvd, Sen Sok', 'Net 30']
    },
    'inventory': {
        'display_name': 'Stock (Inventory)',
        'default_filename': 'inFlow_Inventory_Stock.csv',
        'description': 'Import stock levels on hand for each product and warehouse location.',
        'export_description': 'Export your current stock levels on hand by product, warehouse location, and sublocation.',
        'headers': ['Item Code', 'Item Name', 'Location', 'Sublocation', 'Quantity on Hand'],
        'sample_row': ['A1600-QP', 'Paper Box 1600ML', 'Central Warehouse', 'Aisle 2 - Shelf B', '500']
    },
    'sales_order': {
        'display_name': 'Sales Order',
        'default_filename': 'inFlow_SalesOrder.csv',
        'description': 'Import your sales orders, including status (Paid, Open, Invoiced, Fully Shipped), customer information, and items ordered.',
        'export_description': 'Export your sales orders, including status, customer information, items, quantities, and totals.',
        'headers': ['Order Number', 'Status', 'Customer Name', 'Order Date', 'Item Code', 'Description', 'Quantity', 'Unit Price', 'Subtotal', 'Amount Paid', 'Payment Status'],
        'sample_row': ['SO-000101', 'Paid', 'Angkor Supermarket', '2026-10-10', 'A1600-QP', 'Paper Box 1600ML', '10', '12.00', '120.00', '120.00', 'PAID']
    },
    'purchase_order': {
        'display_name': 'Purchase Order',
        'default_filename': 'inFlow_PurchaseOrder.csv',
        'description': 'Import your purchase orders, including status, vendor information, and what was ordered.',
        'export_description': 'Export your purchase orders, including vendor information, items, quantities, and costs.',
        'headers': ['Order Number', 'Status', 'Vendor Name', 'Order Date', 'Item Code', 'Description', 'Quantity', 'Unit Cost', 'Subtotal'],
        'sample_row': ['PO-000050', 'Received', 'Asia Packaging Co., Ltd', '2026-10-09', 'A1600-QP', 'Paper Box 1600ML', '100', '8.50', '850.00']
    }
}


def get_meta(data_type):
    key = (data_type or '').lower().strip()
    if key in ['products', 'item', 'items']:
        key = 'product'
    elif key in ['customers', 'client', 'clients']:
        key = 'customer'
    elif key in ['vendors', 'supplier', 'suppliers']:
        key = 'vendor'
    elif key in ['stock', 'stocks', 'inventories']:
        key = 'inventory'
    elif key in ['sales', 'salesorder', 'sales_orders', 'sales orders']:
        key = 'sales_order'
    elif key in ['purchase', 'purchaseorder', 'purchase_orders', 'purchase orders', 'po']:
        key = 'purchase_order'
    return key, DATA_TYPES_META.get(key, DATA_TYPES_META['product'])


def generate_sample_csv(data_type):
    key, meta = get_meta(data_type)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(meta['headers'])
    writer.writerow(meta['sample_row'])
    return output.getvalue().encode('utf-8-sig'), meta['default_filename']


def export_data_to_csv(data_type):
    key, meta = get_meta(data_type)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(meta['headers'])

    if key == 'product':
        rows = query_all("""
            SELECT p.sku, p.name, p.description, c.name as category_name, p.barcode,
                   p.default_price, p.standard_cost, p.uom, p.remarks
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active = TRUE
            ORDER BY p.name ASC;
        """)
        for r in rows:
            writer.writerow([
                r['sku'] or '',
                r['name'] or '',
                r['description'] or '',
                r['category_name'] or '',
                r['barcode'] or '',
                f"{float(r['default_price'] or 0):.2f}",
                f"{float(r['standard_cost'] or 0):.2f}",
                r['uom'] or 'pcs',
                r['remarks'] or ''
            ])

    elif key == 'customer':
        rows = query_all("""
            SELECT name, contact_name, phone, email, address1, city, country, payment_terms, balance
            FROM customers
            WHERE is_active = TRUE
            ORDER BY name ASC;
        """)
        for r in rows:
            writer.writerow([
                r['name'] or '',
                r['contact_name'] or '',
                r['phone'] or '',
                r['email'] or '',
                r['address1'] or '',
                r['city'] or '',
                r['country'] or 'Cambodia',
                r['payment_terms'] or 'Due on Receipt',
                f"Balance: {float(r['balance'] or 0):.2f}"
            ])

    elif key == 'vendor':
        rows = query_all("""
            SELECT name, contact_name, phone, email, address1, payment_terms
            FROM vendors
            WHERE is_active = TRUE
            ORDER BY name ASC;
        """)
        for r in rows:
            writer.writerow([
                r['name'] or '',
                r['contact_name'] or '',
                r['phone'] or '',
                r['email'] or '',
                r['address1'] or '',
                r['payment_terms'] or 'Net 30'
            ])

    elif key == 'inventory':
        rows = query_all("""
            SELECT p.sku, p.name, l.name as location_name, inv.sublocation, inv.quantity
            FROM inventory inv
            JOIN products p ON inv.product_id = p.id
            JOIN locations l ON inv.location_id = l.id
            ORDER BY l.name ASC, p.name ASC;
        """)
        for r in rows:
            writer.writerow([
                r['sku'] or '',
                r['name'] or '',
                r['location_name'] or 'Main Warehouse',
                r['sublocation'] or '',
                f"{float(r['quantity'] or 0):g}"
            ])

    elif key == 'sales_order':
        rows = query_all("""
            SELECT so.order_number, to_char(so.order_date, 'YYYY-MM-DD') as order_date,
                   c.name as customer_name, p.sku, sol.description, sol.quantity,
                   sol.unit_price, sol.subtotal, so.paid_amount, so.status, so.payment_status
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            ORDER BY so.id DESC, sol.line_num ASC;
        """)
        for r in rows:
            writer.writerow([
                r['order_number'] or '',
                r['status'] or 'OPEN',
                r['customer_name'] or '',
                r['order_date'] or '',
                r['sku'] or '',
                r['description'] or '',
                f"{float(r['quantity'] or 0):g}",
                f"{float(r['unit_price'] or 0):.2f}",
                f"{float(r['subtotal'] or 0):.2f}",
                f"{float(r['paid_amount'] or 0):.2f}",
                r['payment_status'] or 'UNPAID'
            ])

    elif key == 'purchase_order':
        rows = query_all("""
            SELECT po.order_number, to_char(po.order_date, 'YYYY-MM-DD') as order_date,
                   v.name as vendor_name, p.sku, pol.description, pol.quantity,
                   pol.unit_cost, pol.subtotal, po.status
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id
            LEFT JOIN products p ON pol.product_id = p.id
            ORDER BY po.id DESC, pol.line_num ASC;
        """)
        for r in rows:
            writer.writerow([
                r['order_number'] or '',
                r['status'] or 'DRAFT',
                r['vendor_name'] or '',
                r['order_date'] or '',
                r['sku'] or '',
                r['description'] or '',
                f"{float(r['quantity'] or 0):g}",
                f"{float(r['unit_cost'] or 0):.2f}",
                f"{float(r['subtotal'] or 0):.2f}"
            ])

    # Return encoded bytes with UTF-8 BOM for Microsoft Excel compatibility
    csv_bytes = output.getvalue().encode('utf-8-sig')
    return csv_bytes, meta['default_filename']


def parse_csv_content(csv_text_or_bytes, has_headers=True):
    if isinstance(csv_text_or_bytes, bytes):
        text = csv_text_or_bytes.decode('utf-8-sig', errors='replace')
    else:
        text = str(csv_text_or_bytes)
    
    # Strip carriage returns and normalize newlines
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    
    cleaned_rows = []
    for r in rows:
        cleaned_cells = [re.sub(r'[\u200b\u200c\u200d\ufeff]', '', cell).strip() for cell in r]
        if any(cleaned_cells):
            cleaned_rows.append(cleaned_cells)

    if not cleaned_rows:
        return [], []

    if has_headers:
        headers = cleaned_rows[0]
        data_rows = cleaned_rows[1:]
    else:
        headers = [f"Column {i+1}" for i in range(len(cleaned_rows[0]))]
        data_rows = cleaned_rows

    return headers, data_rows


def normalize_header(h):
    return re.sub(r'[^a-z0-9]', '', str(h).lower())


def parse_date_val(val_str):
    if not val_str:
        return None
    val_clean = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', str(val_str)).strip()
    if not val_clean:
        return None
    try:
        return dateutil.parser.parse(val_clean)
    except Exception:
        pass
    for fmt in ('%d-%b-%y %I:%M:%S %p', '%d-%b-%Y %I:%M:%S %p', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%b-%y', '%d-%b-%Y'):
        try:
            return datetime.strptime(val_clean, fmt)
        except ValueError:
            continue
    return None


def clean_num_val(val_str, default=0.0):
    if not val_str:
        return default
    cleaned = re.sub(r'[^\d.-]', '', str(val_str)).strip()
    try:
        return float(cleaned) if cleaned else default
    except Exception:
        return default


def erase_existing_data(data_type_key):
    """
    Safely deletes all records for the chosen data type before importing.
    Handles cascading relationships and foreign key constraints cleanly.
    """
    key = data_type_key.lower().strip()
    with get_db_cursor(commit=True) as cur:
        if key == 'sales_order':
            cur.execute("DELETE FROM order_payments WHERE order_type = 'SO';")
            cur.execute("DELETE FROM sales_order_lines;")
            cur.execute("DELETE FROM sales_orders;")
            cur.execute("ALTER SEQUENCE IF EXISTS sales_orders_id_seq RESTART WITH 1;")
            logger.info("Erased all sales_orders, sales_order_lines, and SO payments.")

        elif key == 'purchase_order':
            cur.execute("DELETE FROM order_payments WHERE order_type = 'PO';")
            cur.execute("DELETE FROM purchase_order_lines;")
            cur.execute("DELETE FROM purchase_orders;")
            cur.execute("ALTER SEQUENCE IF EXISTS purchase_orders_id_seq RESTART WITH 1;")
            logger.info("Erased all purchase_orders, purchase_order_lines, and PO payments.")

        elif key == 'product':
            # Detach product foreign keys that have RESTRICT rules
            cur.execute("UPDATE sales_order_lines SET product_id = NULL;")
            cur.execute("UPDATE purchase_order_lines SET product_id = NULL;")
            cur.execute("UPDATE stock_adjustment_lines SET product_id = NULL;")
            cur.execute("UPDATE stock_transfer_lines SET product_id = NULL;")
            cur.execute("DELETE FROM product_boms;")
            cur.execute("DELETE FROM product_prices;")
            cur.execute("DELETE FROM product_vendors;")
            cur.execute("DELETE FROM product_attachments;")
            cur.execute("DELETE FROM product_versions;")
            cur.execute("DELETE FROM inventory_logs;")
            cur.execute("DELETE FROM inventory;")
            cur.execute("DELETE FROM products;")
            cur.execute("ALTER SEQUENCE IF EXISTS products_id_seq RESTART WITH 1;")
            logger.info("Erased all products, inventory, and product pricing/vendors.")

        elif key == 'customer':
            cur.execute("UPDATE sales_orders SET customer_id = NULL;")
            cur.execute("DELETE FROM customers;")
            cur.execute("ALTER SEQUENCE IF EXISTS customers_id_seq RESTART WITH 1;")
            logger.info("Erased all customers.")

        elif key == 'vendor':
            cur.execute("UPDATE purchase_orders SET vendor_id = NULL;")
            cur.execute("UPDATE products SET last_vendor_id = NULL;")
            cur.execute("DELETE FROM product_vendors;")
            cur.execute("DELETE FROM vendors;")
            cur.execute("ALTER SEQUENCE IF EXISTS vendors_id_seq RESTART WITH 1;")
            logger.info("Erased all vendors.")

        elif key == 'inventory':
            cur.execute("DELETE FROM inventory;")
            cur.execute("DELETE FROM inventory_logs WHERE reference_type = 'CSV_IMPORT' OR movement_type = 'INITIAL';")
            logger.info("Erased all inventory stock records.")


def preview_import_data(data_type, file_content, has_headers=True, import_mode='keep'):
    key, meta = get_meta(data_type)
    headers, data_rows = parse_csv_content(file_content, has_headers=has_headers)
    
    preview_limit = 6
    preview = data_rows[:preview_limit]
    
    return {
        'data_type': key,
        'data_type_name': meta['display_name'],
        'headers': headers,
        'expected_headers': meta['headers'],
        'preview_rows': preview,
        'total_rows': len(data_rows),
        'import_mode': import_mode
    }


def execute_import_data(data_type, file_content, has_headers=True, import_mode='keep'):
    key, meta = get_meta(data_type)
    headers, data_rows = parse_csv_content(file_content, has_headers=has_headers)

    if not data_rows:
        return {
            'success': False,
            'imported': 0,
            'updated': 0,
            'errors': ['The provided CSV file contains no data rows.'],
            'message': 'No data rows found to import.'
        }

    # 1. If Erase Mode was chosen, clean out existing records first
    is_erase_mode = (str(import_mode).lower().strip() == 'erase')
    if is_erase_mode:
        try:
            erase_existing_data(key)
        except Exception as e:
            logger.error(f"Failed to erase existing data for {key}: {e}", exc_info=True)
            return {
                'success': False,
                'imported': 0,
                'updated': 0,
                'errors': [f"Database error while clearing old records: {str(e)}"],
                'message': 'Failed to erase existing data before import.'
            }

    imported_cnt = 0
    updated_cnt = 0
    errors = []

    # Fast header getter helper
    norm_headers = [normalize_header(h) for h in headers]

    def get_val(row, header_aliases, default=''):
        norm_aliases = [normalize_header(a) for a in header_aliases]
        for target in norm_aliases:
            if target in norm_headers:
                idx = norm_headers.index(target)
                if idx < len(row):
                    val = row[idx].strip()
                    val = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', val).strip()
                    if val != '':
                        return val
        return default

    # =========================================================================
    # 1. PRODUCT IMPORT
    # =========================================================================
    if key == 'product':
        # In-memory category and product caching
        cat_map = {c['name'].lower().strip(): c['id'] for c in query_all("SELECT id, name FROM categories;")}
        prod_map = {}
        for p in query_all("SELECT id, sku, name FROM products;"):
            if p.get('sku'):
                prod_map[p['sku'].lower().strip()] = p['id']
            if p.get('name'):
                prod_map[p['name'].lower().strip()] = p['id']

        with get_db_cursor(commit=True) as cur:
            for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
                name = get_val(r, ['Item Name', 'Name', 'ProductName', 'Product Name', 'ItemName', 'Item'])
                sku = get_val(r, ['Item Code', 'ItemCode', 'SKU', 'Code', 'Product Code', 'ItemNumber'])
                desc = get_val(r, ['Description', 'Desc', 'Item Description', 'ItemDescription'])
                cat_name = get_val(r, ['Category', 'Category Name', 'CategoryName'])
                barcode = get_val(r, ['Barcode', 'BarCode', 'UPC', 'EAN'])
                price_val = clean_num_val(get_val(r, ['UnitPrice', 'Unit Price', 'Default Price', 'Price', 'Sale Price']), 0.0)
                cost_val = clean_num_val(get_val(r, ['ManualCost', 'Standard Cost', 'StandardCost', 'Cost', 'Unit Cost', 'MovingAverageCost', 'LastPurchaseCost']), 0.0)
                uom = get_val(r, ['Uom', 'UOM', 'Unit', 'Unit of Measure', 'SalesUom'], 'pcs')
                remarks = get_val(r, ['Remarks', 'Note', 'Notes'])
                is_active_raw = get_val(r, ['IsActive', 'Active', 'Status'], 'True')
                is_active = str(is_active_raw).lower() in ('true', '1', 'yes', 't')

                if not name and not sku:
                    errors.append(f"Row {row_idx}: Missing product name or item code.")
                    continue

                if not name:
                    name = sku
                if not sku:
                    sku = name[:50]

                # Resolve Category
                cat_id = None
                if cat_name:
                    cn_clean = cat_name.lower().strip()
                    if cn_clean in cat_map:
                        cat_id = cat_map[cn_clean]
                    else:
                        cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING id;", (cat_name.strip(),))
                        cat_id = cur.fetchone()['id']
                        cat_map[cn_clean] = cat_id

                # Match product
                existing_id = None
                if not is_erase_mode:
                    existing_id = prod_map.get(sku.lower().strip()) or prod_map.get(name.lower().strip())

                if existing_id:
                    cur.execute("""
                        UPDATE products
                        SET name = COALESCE(NULLIF(%s, ''), name),
                            description = COALESCE(NULLIF(%s, ''), description),
                            category_id = COALESCE(%s, category_id),
                            barcode = COALESCE(NULLIF(%s, ''), barcode),
                            default_price = %s,
                            standard_cost = %s,
                            uom = COALESCE(NULLIF(%s, ''), uom),
                            remarks = COALESCE(NULLIF(%s, ''), remarks),
                            is_active = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (name, desc, cat_id, barcode, price_val, cost_val, uom, remarks, is_active, existing_id))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO products (sku, name, description, category_id, barcode, default_price, standard_cost, uom, remarks, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (sku, name, desc, cat_id, barcode, price_val, cost_val, uom, remarks, is_active))
                    new_id = cur.fetchone()['id']
                    prod_map[sku.lower().strip()] = new_id
                    prod_map[name.lower().strip()] = new_id
                    imported_cnt += 1

    # =========================================================================
    # 2. CUSTOMER IMPORT
    # =========================================================================
    elif key == 'customer':
        cust_map = {c['name'].lower().strip(): c['id'] for c in query_all("SELECT id, name FROM customers;")}
        with get_db_cursor(commit=True) as cur:
            for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
                name = get_val(r, ['Customer Name', 'CustomerName', 'Customer', 'Name', 'Company Name'])
                contact = get_val(r, ['Contact Name', 'ContactName', 'Contact', 'Contact Person'])
                phone = get_val(r, ['Phone', 'Telephone', 'Mobile'])
                email = get_val(r, ['Email', 'Email Address'])
                address = get_val(r, ['Address', 'BillingAddress1', 'Billing Address', 'Street'])
                city = get_val(r, ['City', 'BillingCity'])
                country = get_val(r, ['Country', 'BillingCountry'], 'Cambodia')
                terms = get_val(r, ['Payment Terms', 'PaymentTerms', 'Terms'], 'Due on Receipt')

                if not name:
                    errors.append(f"Row {row_idx}: Missing customer name.")
                    continue

                existing_id = None
                if not is_erase_mode:
                    existing_id = cust_map.get(name.lower().strip())

                if existing_id:
                    cur.execute("""
                        UPDATE customers
                        SET contact_name = COALESCE(NULLIF(%s, ''), contact_name),
                            phone = COALESCE(NULLIF(%s, ''), phone),
                            email = COALESCE(NULLIF(%s, ''), email),
                            address1 = COALESCE(NULLIF(%s, ''), address1),
                            city = COALESCE(NULLIF(%s, ''), city),
                            country = COALESCE(NULLIF(%s, ''), country),
                            payment_terms = COALESCE(NULLIF(%s, ''), payment_terms),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (contact, phone, email, address, city, country, terms, existing_id))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO customers (name, contact_name, phone, email, address1, city, country, payment_terms, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING id;
                    """, (name, contact, phone, email, address, city, country, terms))
                    new_id = cur.fetchone()['id']
                    cust_map[name.lower().strip()] = new_id
                    imported_cnt += 1

    # =========================================================================
    # 3. VENDOR IMPORT
    # =========================================================================
    elif key == 'vendor':
        vend_map = {v['name'].lower().strip(): v['id'] for v in query_all("SELECT id, name FROM vendors;")}
        with get_db_cursor(commit=True) as cur:
            for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
                name = get_val(r, ['Vendor Name', 'VendorName', 'Vendor', 'Supplier Name', 'Name'])
                contact = get_val(r, ['Contact Name', 'ContactName', 'Contact'])
                phone = get_val(r, ['Phone', 'Telephone'])
                email = get_val(r, ['Email'])
                address = get_val(r, ['Address', 'VendorAddress1'])
                terms = get_val(r, ['Payment Terms', 'PaymentTerms'], 'Net 30')

                if not name:
                    errors.append(f"Row {row_idx}: Missing vendor name.")
                    continue

                existing_id = None
                if not is_erase_mode:
                    existing_id = vend_map.get(name.lower().strip())

                if existing_id:
                    cur.execute("""
                        UPDATE vendors
                        SET contact_name = COALESCE(NULLIF(%s, ''), contact_name),
                            phone = COALESCE(NULLIF(%s, ''), phone),
                            email = COALESCE(NULLIF(%s, ''), email),
                            address1 = COALESCE(NULLIF(%s, ''), address1),
                            payment_terms = COALESCE(NULLIF(%s, ''), payment_terms),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (contact, phone, email, address, terms, existing_id))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO vendors (name, contact_name, phone, email, address1, payment_terms, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING id;
                    """, (name, contact, phone, email, address, terms))
                    new_id = cur.fetchone()['id']
                    vend_map[name.lower().strip()] = new_id
                    imported_cnt += 1

    # =========================================================================
    # 4. INVENTORY / STOCK IMPORT
    # =========================================================================
    elif key == 'inventory':
        prod_map = {p['sku'].lower().strip(): p['id'] for p in query_all("SELECT id, sku FROM products WHERE sku IS NOT NULL;")}
        for p in query_all("SELECT id, name FROM products;"):
            prod_map[p['name'].lower().strip()] = p['id']

        loc_map = {l['name'].lower().strip(): l['id'] for l in query_all("SELECT id, name FROM locations;")}
        
        with get_db_cursor(commit=True) as cur:
            for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
                item_code = get_val(r, ['Item Code', 'ItemCode', 'SKU', 'Item Name', 'Name'])
                loc_name = get_val(r, ['Location', 'Warehouse', 'DefaultLocation'], 'Main Warehouse')
                subloc = get_val(r, ['Sublocation', 'DefaultSublocation', 'Bin', 'Shelf', 'Aisle'])
                qty = clean_num_val(get_val(r, ['Quantity on Hand', 'Quantity', 'Qty', 'Stock', 'OnHand']), 0.0)

                prod_id = prod_map.get(item_code.lower().strip()) if item_code else None
                if not prod_id:
                    errors.append(f"Row {row_idx}: Product '{item_code}' not found in catalog.")
                    continue

                # Location lookup
                ln_clean = loc_name.lower().strip()
                if ln_clean in loc_map:
                    loc_id = loc_map[ln_clean]
                else:
                    cur.execute("INSERT INTO locations (name, code) VALUES (%s, %s) RETURNING id;",
                                (loc_name.strip(), loc_name.strip().upper()[:10]))
                    loc_id = cur.fetchone()['id']
                    loc_map[ln_clean] = loc_id

                cur.execute("""
                    SELECT id, quantity FROM inventory
                    WHERE product_id = %s AND location_id = %s AND COALESCE(sublocation, '') = COALESCE(%s, '');
                """, (prod_id, loc_id, subloc))
                existing_inv = cur.fetchone()

                if existing_inv:
                    cur.execute("UPDATE inventory SET quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                                (qty, existing_inv['id']))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                        VALUES (%s, %s, %s, %s);
                    """, (prod_id, loc_id, subloc, qty))
                    imported_cnt += 1

                cur.execute("""
                    INSERT INTO inventory_logs (product_id, movement_type, reference_type, quantity, qty_before, qty_after, reason)
                    VALUES (%s, 'INITIAL', 'CSV_IMPORT', %s, 0, %s, 'Imported from CSV');
                """, (prod_id, qty, qty))

    # =========================================================================
    # 5. SALES ORDER IMPORT (With Authentic inFlow Status, Amounts & Lines)
    # =========================================================================
    elif key == 'sales_order':
        orders_map = {}
        for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
            so_num = get_val(r, ['OrderNumber', 'Order Number', 'SO Number', 'Invoice Number', 'Order #'])
            if not so_num:
                errors.append(f"Row {row_idx}: Missing Order Number.")
                continue

            if so_num not in orders_map:
                orders_map[so_num] = {
                    'order_date_raw': get_val(r, ['OrderDate', 'Order Date', 'Date']),
                    'due_date_raw': get_val(r, ['DueDate', 'Due Date']),
                    'invoiced_date_raw': get_val(r, ['InvoicedDate', 'Invoiced Date']),
                    'date_paid_raw': get_val(r, ['DatePaid', 'Date Paid']),
                    'status_raw': get_val(r, ['OrderStatus', 'Order Status', 'Status', 'State'], 'OPEN'),
                    'customer_name': get_val(r, ['Customer', 'CustomerName', 'Customer Name', 'Client'], 'Walk-in Customer'),
                    'contact_name': get_val(r, ['ContactName', 'Contact Name']),
                    'phone': get_val(r, ['Phone', 'Telephone', 'Mobile']),
                    'email': get_val(r, ['Email', 'Email Address']),
                    'address': get_val(r, ['BillingAddress1', 'Address', 'Billing Address']),
                    'city': get_val(r, ['BillingCity', 'City']),
                    'country': get_val(r, ['BillingCountry', 'Country'], 'Cambodia'),
                    'sales_rep': get_val(r, ['SalesRep', 'Sales Rep', 'Salesperson']),
                    'po_number': get_val(r, ['PONumber', 'PO Number', 'Customer PO']),
                    'freight': clean_num_val(get_val(r, ['Freight', 'Shipping Fee', 'OrderFreight', 'Shipping']), 0.0),
                    'amount_paid_raw': clean_num_val(get_val(r, ['AmountPaid', 'Paid Amount', 'Amount Paid']), 0.0),
                    'payment_terms': get_val(r, ['PaymentTerms', 'Payment Terms', 'PaymentTermsName']),
                    'payment_method': get_val(r, ['PaymentMethod', 'Payment Method']),
                    'remarks': get_val(r, ['OrderRemarks', 'Order Remarks', 'Remarks', 'Notes', 'Note']),
                    'location': get_val(r, ['Location', 'Warehouse']),
                    'lines': []
                }

            orders_map[so_num]['lines'].append({
                'item_name': get_val(r, ['ItemName', 'Item Name', 'Item Code', 'ItemCode', 'SKU', 'Product Name']),
                'desc': get_val(r, ['ItemDescription', 'Description', 'Item Description']),
                'qty': clean_num_val(get_val(r, ['ItemQuantity', 'Quantity', 'Qty']), 1.0),
                'uom': get_val(r, ['ItemQuantityUoM', 'UOM', 'Unit'], 'pcs'),
                'price': clean_num_val(get_val(r, ['ItemUnitPrice', 'Unit Price', 'Price']), 0.0),
                'discount_raw': get_val(r, ['ItemDiscount', 'Discount']),
                'subtotal_raw': clean_num_val(get_val(r, ['ItemSubtotal', 'Subtotal']), None)
            })

        # Cache existing customers, products, and locations
        cust_map = {c['name'].lower().strip(): c['id'] for c in query_all("SELECT id, name FROM customers;")}
        prod_map = {}
        for p in query_all("SELECT id, sku, name, default_price FROM products;"):
            if p.get('sku'):
                prod_map[p['sku'].lower().strip()] = p
            if p.get('name'):
                prod_map[p['name'].lower().strip()] = p

        loc_map = {l['name'].lower().strip(): l['id'] for l in query_all("SELECT id, name FROM locations;")}

        with get_db_cursor(commit=True) as cur:
            for so_num, order_data in orders_map.items():
                # Customer handling
                cust_name = (order_data['customer_name'] or 'Walk-in Customer').strip()
                cn_clean = cust_name.lower()
                if cn_clean in cust_map:
                    cust_id = cust_map[cn_clean]
                else:
                    cur.execute("""
                        INSERT INTO customers (name, contact_name, phone, email, address1, city, country, payment_terms, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING id;
                    """, (cust_name, order_data['contact_name'], order_data['phone'], order_data['email'],
                          order_data['address'], order_data['city'], order_data['country'], order_data['payment_terms']))
                    cust_id = cur.fetchone()['id']
                    cust_map[cn_clean] = cust_id

                # Location handling
                loc_id = None
                if order_data['location']:
                    loc_name = order_data['location'].strip()
                    ln_clean = loc_name.lower()
                    if ln_clean in loc_map:
                        loc_id = loc_map[ln_clean]
                    else:
                        cur.execute("INSERT INTO locations (name, code) VALUES (%s, %s) RETURNING id;",
                                    (loc_name, loc_name.upper()[:10]))
                        loc_id = cur.fetchone()['id']
                        loc_map[ln_clean] = loc_id

                # Robust Date parsing
                dt_order = parse_date_val(order_data['order_date_raw'])
                ord_date = dt_order.date() if dt_order else datetime.now().date()

                dt_due = parse_date_val(order_data['due_date_raw'])
                due_date = dt_due.date() if dt_due else None

                dt_invoiced = parse_date_val(order_data['invoiced_date_raw'])
                dt_paid = parse_date_val(order_data['date_paid_raw'])

                # Compute line subtotals first to calculate order total
                calculated_subtotal = 0.0
                parsed_lines = []
                for line in order_data['lines']:
                    item_name = (line['item_name'] or '').strip()
                    p_info = prod_map.get(item_name.lower()) if item_name else None
                    prod_id = p_info['id'] if p_info else None

                    # Auto-create missing product in catalog
                    if not prod_id and item_name:
                        cur.execute("""
                            INSERT INTO products (sku, name, default_price, uom, is_active)
                            VALUES (%s, %s, %s, %s, TRUE)
                            RETURNING id, default_price;
                        """, (item_name[:50], item_name, line['price'], line['uom']))
                        created_p = cur.fetchone()
                        prod_id = created_p['id']
                        prod_map[item_name.lower()] = {'id': prod_id, 'sku': item_name[:50], 'name': item_name, 'default_price': line['price']}

                    qty = line['qty']
                    unit_p = line['price'] if line['price'] > 0 else (float(p_info['default_price']) if p_info and p_info.get('default_price') else 0.0)
                    
                    # Discount parsing
                    disc_pct = 0.0
                    disc_raw = str(line['discount_raw'] or '').strip()
                    if '%' in disc_raw:
                        disc_pct = clean_num_val(disc_raw.replace('%', ''), 0.0)
                    elif disc_raw:
                        disc_pct = clean_num_val(disc_raw, 0.0)

                    if line['subtotal_raw'] is not None:
                        subtot = line['subtotal_raw']
                    else:
                        subtot = qty * unit_p * (1.0 - (disc_pct / 100.0))

                    calculated_subtotal += subtot
                    desc = line['desc'] or (p_info['name'] if p_info else item_name)
                    parsed_lines.append({
                        'prod_id': prod_id,
                        'desc': desc,
                        'qty': qty,
                        'unit_price': unit_p,
                        'discount': disc_pct,
                        'subtotal': subtot
                    })

                total_amount = calculated_subtotal + order_data['freight']
                amount_paid_raw = order_data['amount_paid_raw']

                # =================================================================
                # STATUS & PAYMENT STATUS RESOLUTION (Matching inFlow exactly)
                # =================================================================
                raw_st = (order_data['status_raw'] or '').strip()
                raw_upper = raw_st.upper()

                if raw_upper in ('PAID',):
                    so_status = 'PAID'
                    payment_status = 'PAID'
                    paid_amount = amount_paid_raw if amount_paid_raw > 0 else total_amount
                    balance_due = 0.0
                elif raw_upper in ('INVOICED',):
                    so_status = 'INVOICED'
                    paid_amount = amount_paid_raw
                    if (paid_amount >= total_amount and total_amount > 0) or dt_paid:
                        payment_status = 'PAID'
                        balance_due = 0.0
                    elif paid_amount > 0:
                        payment_status = 'PARTIAL'
                        balance_due = max(0.0, total_amount - paid_amount)
                    else:
                        payment_status = 'UNPAID'
                        balance_due = total_amount
                elif raw_upper in ('FULLY SHIPPED', 'SHIPPED'):
                    so_status = 'SHIPPED'
                    paid_amount = amount_paid_raw
                    if (paid_amount >= total_amount and total_amount > 0) or dt_paid:
                        payment_status = 'PAID'
                        balance_due = 0.0
                    elif paid_amount > 0:
                        payment_status = 'PARTIAL'
                        balance_due = max(0.0, total_amount - paid_amount)
                    else:
                        payment_status = 'UNPAID'
                        balance_due = total_amount
                elif raw_upper in ('OPEN', 'UNINVOICED'):
                    so_status = 'OPEN'
                    paid_amount = amount_paid_raw
                    if paid_amount >= total_amount and total_amount > 0:
                        payment_status = 'PAID'
                        balance_due = 0.0
                    elif paid_amount > 0:
                        payment_status = 'PARTIAL'
                        balance_due = max(0.0, total_amount - paid_amount)
                    else:
                        payment_status = 'UNPAID'
                        balance_due = total_amount
                elif raw_upper in ('QUOTE', 'QUOTED'):
                    so_status = 'QUOTE'
                    payment_status = 'UNPAID'
                    paid_amount = 0.0
                    balance_due = total_amount
                elif raw_upper in ('CANCELLED', 'CANCELED'):
                    so_status = 'CANCELLED'
                    payment_status = 'UNPAID'
                    paid_amount = 0.0
                    balance_due = 0.0
                elif raw_upper in ('IN PROGRESS', 'IN_PROGRESS', 'PICKED', 'PACKED'):
                    so_status = raw_upper.replace(' ', '_')
                    paid_amount = amount_paid_raw
                    payment_status = 'PAID' if paid_amount >= total_amount and total_amount > 0 else 'UNPAID'
                    balance_due = max(0.0, total_amount - paid_amount)
                else:
                    so_status = raw_upper or 'OPEN'
                    paid_amount = amount_paid_raw
                    payment_status = 'PAID' if (paid_amount >= total_amount and total_amount > 0) or dt_paid else 'UNPAID'
                    balance_due = 0.0 if payment_status == 'PAID' else max(0.0, total_amount - paid_amount)

                # Set invoiced date if Paid or Invoiced
                invoiced_date = dt_invoiced
                if not invoiced_date and so_status in ('PAID', 'INVOICED'):
                    invoiced_date = dt_order or datetime.now()

                # Upsert Sales Order
                cur.execute("SELECT id FROM sales_orders WHERE order_number = %s;", (so_num,))
                existing_so = cur.fetchone()

                if existing_so and not is_erase_mode:
                    so_id = existing_so['id']
                    cur.execute("""
                        UPDATE sales_orders
                        SET customer_id = %s,
                            location_id = COALESCE(%s, location_id),
                            order_date = %s,
                            due_date = %s,
                            status = %s,
                            payment_status = %s,
                            subtotal = %s,
                            shipping_fee = %s,
                            total_amount = %s,
                            paid_amount = %s,
                            balance_due = %s,
                            sales_rep = COALESCE(NULLIF(%s, ''), sales_rep),
                            po_number = COALESCE(NULLIF(%s, ''), po_number),
                            notes = COALESCE(NULLIF(%s, ''), notes),
                            invoiced_date = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (cust_id, loc_id, ord_date, due_date, so_status, payment_status,
                          calculated_subtotal, order_data['freight'], total_amount, paid_amount, balance_due,
                          order_data['sales_rep'], order_data['po_number'], order_data['remarks'], invoiced_date, so_id))
                    cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s;", (so_id,))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO sales_orders (
                            order_number, customer_id, location_id, order_date, due_date,
                            status, payment_status, subtotal, shipping_fee, total_amount,
                            paid_amount, balance_due, sales_rep, po_number, notes, invoiced_date
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (so_num, cust_id, loc_id, ord_date, due_date, so_status, payment_status,
                          calculated_subtotal, order_data['freight'], total_amount, paid_amount, balance_due,
                          order_data['sales_rep'], order_data['po_number'], order_data['remarks'], invoiced_date))
                    so_id = cur.fetchone()['id']
                    imported_cnt += 1

                # Insert lines
                for l_idx, pline in enumerate(parsed_lines, start=1):
                    cur.execute("""
                        INSERT INTO sales_order_lines (
                            sales_order_id, line_num, product_id, description,
                            quantity, unit_price, discount_percent, subtotal
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """, (so_id, l_idx, pline['prod_id'], pline['desc'], pline['qty'], pline['unit_price'], pline['discount'], pline['subtotal']))

    # =========================================================================
    # 6. PURCHASE ORDER IMPORT
    # =========================================================================
    elif key == 'purchase_order':
        orders_map = {}
        for row_idx, r in enumerate(data_rows, start=2 if has_headers else 1):
            po_num = get_val(r, ['OrderNumber', 'Order Number', 'PO Number', 'Order #'])
            if not po_num:
                errors.append(f"Row {row_idx}: Missing PO Order Number.")
                continue

            if po_num not in orders_map:
                orders_map[po_num] = {
                    'order_date_raw': get_val(r, ['OrderDate', 'Order Date', 'Date']),
                    'vendor_name': get_val(r, ['Vendor', 'VendorName', 'Vendor Name', 'Supplier'], 'General Supplier'),
                    'status_raw': get_val(r, ['OrderStatus', 'Order Status', 'Status'], 'DRAFT'),
                    'lines': []
                }

            orders_map[po_num]['lines'].append({
                'item_name': get_val(r, ['ItemName', 'Item Name', 'Item Code', 'ItemCode', 'SKU', 'VendorItemCode']),
                'desc': get_val(r, ['ItemDescription', 'Description', 'Item Description']),
                'qty': clean_num_val(get_val(r, ['ItemQuantity', 'Quantity', 'Qty']), 1.0),
                'cost': clean_num_val(get_val(r, ['ItemUnitPrice', 'Unit Cost', 'Cost']), 0.0),
                'subtotal_raw': clean_num_val(get_val(r, ['ItemSubtotal', 'Subtotal']), None)
            })

        vend_map = {v['name'].lower().strip(): v['id'] for v in query_all("SELECT id, name FROM vendors;")}
        prod_map = {p['sku'].lower().strip(): p for p in query_all("SELECT id, sku, name, standard_cost FROM products WHERE sku IS NOT NULL;")}
        for p in query_all("SELECT id, name, standard_cost FROM products;"):
            prod_map[p['name'].lower().strip()] = p

        with get_db_cursor(commit=True) as cur:
            for po_num, order_data in orders_map.items():
                v_name = order_data['vendor_name'].strip()
                vn_clean = v_name.lower()
                if vn_clean in vend_map:
                    vend_id = vend_map[vn_clean]
                else:
                    cur.execute("INSERT INTO vendors (name, is_active) VALUES (%s, TRUE) RETURNING id;", (v_name,))
                    vend_id = cur.fetchone()['id']
                    vend_map[vn_clean] = vend_id

                dt_order = parse_date_val(order_data['order_date_raw'])
                ord_date = dt_order.date() if dt_order else datetime.now().date()
                po_status = (order_data['status_raw'] or 'DRAFT').upper()

                cur.execute("SELECT id FROM purchase_orders WHERE order_number = %s;", (po_num,))
                existing_po = cur.fetchone()

                if existing_po and not is_erase_mode:
                    po_id = existing_po['id']
                    cur.execute("""
                        UPDATE purchase_orders
                        SET vendor_id = %s, order_date = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (vend_id, ord_date, po_status, po_id))
                    cur.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s;", (po_id,))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO purchase_orders (order_number, vendor_id, order_date, status)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id;
                    """, (po_num, vend_id, ord_date, po_status))
                    po_id = cur.fetchone()['id']
                    imported_cnt += 1

                total_subtotal = 0.0
                for l_idx, line in enumerate(order_data['lines'], start=1):
                    item_name = (line['item_name'] or '').strip()
                    p_info = prod_map.get(item_name.lower()) if item_name else None
                    prod_id = p_info['id'] if p_info else None
                    qty = line['qty']
                    cost = line['cost'] if line['cost'] > 0 else (float(p_info['standard_cost']) if p_info and p_info.get('standard_cost') else 0.0)
                    subtot = line['subtotal_raw'] if line['subtotal_raw'] is not None else (qty * cost)
                    total_subtotal += subtot
                    desc = line['desc'] or (p_info['name'] if p_info else item_name)

                    cur.execute("""
                        INSERT INTO purchase_order_lines (purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """, (po_id, l_idx, prod_id, desc, qty, cost, subtot))

                cur.execute("UPDATE purchase_orders SET subtotal = %s, total_amount = %s WHERE id = %s;",
                            (total_subtotal, total_subtotal, po_id))

    mode_text = "cleanly replaced" if is_erase_mode else "processed"
    return {
        'success': True,
        'imported': imported_cnt,
        'updated': updated_cnt,
        'mode': import_mode,
        'errors': errors[:50],  # cap returned error messages
        'message': f"Import completed successfully! {imported_cnt} records added, {updated_cnt} updated ({mode_text} under '{import_mode}' mode)."
    }
