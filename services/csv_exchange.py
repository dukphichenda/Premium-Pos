import csv
import io
import json
import re
import logging
from datetime import datetime
import dateutil.parser
from database import query_all, query_one, execute, execute_returning_id, get_db_cursor, resync_all_sequences

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


UOM_HEADER_ALIASES = [
    'ItemQuantityUoM', 'Item Quantity UoM', 'Item Quantity UOM',
    'ItemQuantityUnit', 'Item Quantity Unit', 'ItemQuantityUOM',
    'ItemUoM', 'Item UoM', 'Item UOM', 'ItemUnit', 'Item Unit',
    'QuantityUoM', 'Quantity UoM', 'Quantity UOM',
    'QuantityUnit', 'Quantity Unit',
    'OrderUoM', 'Order UoM', 'Order Unit',
    'SalesUoM', 'Sales UoM', 'Sales UOM', 'SalesUnit', 'Sales Unit',
    'PurchasingUoM', 'Purchasing UoM', 'Purchasing Unit',
    'Unit of Measure', 'UnitOfMeasure',
    'UOM', 'UoM', 'Unit', 'Units', 'Meas.', 'Measure', 'ខ្នាត', 'ឯកតា'
]


def extract_packaging_spec(text):
    """
    Extracts packaging specifications such as '300ចាន/កេស' (case), '900សន្លឹក/ដុំ' (pack),
    '1000pcs/case', '50/pack' from product name or description.
    Returns dict: {'type': 'case'|'pack', 'ratio': float|None} or None
    """
    if not text:
        return None
    text_str = str(text)

    # 1. Regex for Case patterns (e.g. 300ចាន/កេស, 180ចាន/កេស, 90ចាន/កេស, 600pcs/កេស, 400ប្រអប់/កេស, 500/case, 1000 pcs / ctn)
    m_case = re.search(r'(\d+(?:\.\d+)?)\s*(?:[^\w\s/]|ចាន|ប្រអប់|កែវ|សន្លឹក|ដុំ|គ្រាប់|pcs|pc|ea)?\s*/\s*(?:កេស|case|cs|carton|ctn|box)\b', text_str, re.IGNORECASE)
    if not m_case:
        m_case = re.search(r'\(?\s*(\d+(?:\.\d+)?)\s*(?:pcs|pc|ea|ចាន|ដុំ)?\s*/\s*(?:កេស|case|cs|ctn|box)\s*\)?', text_str, re.IGNORECASE)

    # 2. Regex for Pack patterns (e.g. 900សន្លឹក/ដុំ, 500pcs/pack, 50/pk, 100/កញ្ចប់)
    m_pack = re.search(r'(\d+(?:\.\d+)?)\s*(?:[^\w\s/]|ចាន|ប្រអប់|កែវ|សន្លឹក|ដុំ|គ្រាប់|pcs|pc|ea)?\s*/\s*(?:កញ្ចប់|pack|pk|pkg|packet|ដុំ)\b', text_str, re.IGNORECASE)
    if not m_pack:
        m_pack = re.search(r'\(?\s*(\d+(?:\.\d+)?)\s*(?:pcs|pc|ea|ចាន|សន្លឹក)?\s*/\s*(?:កញ្ចប់|pack|pk|pkg|packet|ដុំ)\s*\)?', text_str, re.IGNORECASE)

    if m_case:
        try:
            r_val = float(m_case.group(1))
            if r_val > 1:
                return {'type': 'case', 'ratio': r_val}
        except Exception:
            pass

    if m_pack:
        try:
            r_val = float(m_pack.group(1))
            if r_val > 1:
                return {'type': 'pack', 'ratio': r_val}
        except Exception:
            pass

    # Keyword check without explicit ratio number
    t_lower = text_str.lower()
    if 'កេស' in text_str or '/case' in t_lower or '/cs' in t_lower or 'per case' in t_lower or 'per ctn' in t_lower or 'per box' in t_lower:
        return {'type': 'case', 'ratio': None}
    if 'កញ្ចប់' in text_str or '/pack' in t_lower or '/pk' in t_lower or 'per pack' in t_lower:
        return {'type': 'pack', 'ratio': None}

    return None


def resolve_order_line_uom(raw_uom, item_name, desc, p_info, unit_price, qty):
    """
    Intelligently checks and resolves whether the line's unit is 'cases', 'packs', or 'pcs.'.
    Returns a 3-tuple: (final_uom, display_qty, std_qty)
    - final_uom: normalized canonical UOM ('cases', 'packs', or product's base uom e.g. 'pcs.')
    - display_qty: display quantity for the line item (e.g. 1.0 case)
    - std_qty: standard base inventory quantity (display_qty * ratio, e.g. 300.0 pcs)
    """
    u_str = (raw_uom or '').strip().lower().rstrip('.')
    combined_text = f"{item_name or ''} {desc or ''}".strip()
    pkg_spec = extract_packaging_spec(combined_text)

    # Catalog product attributes
    base_uom = (p_info.get('uom') or 'pcs.').strip() if p_info else 'pcs.'
    sales_uom = (p_info.get('sales_uom') or '').strip() if p_info else ''
    purch_uom = (p_info.get('purchasing_uom') or '').strip() if p_info else ''
    cat_sales_ratio = float(p_info.get('sales_uom_ratio_std') or 1.0) if p_info else 1.0
    cat_purch_ratio = float(p_info.get('purchasing_uom_ratio_std') or 1.0) if p_info else 1.0
    cat_price = float(p_info.get('default_price') or 0.0) if p_info else 0.0

    CASE_KEYWORDS = {
        'case', 'cases', 'cs', 'box', 'boxes', 'bx', 'carton', 'cartons',
        'ctn', 'ctns', 'កេស', 'បាវ', 'ធុង'
    }
    PACK_KEYWORDS = {
        'pack', 'packs', 'pk', 'pks', 'pkg', 'pkgs', 'packet', 'packets',
        'bundle', 'bundles', 'កញ្ចប់'
    }
    PCS_KEYWORDS = {
        'pcs', 'pc', 'piece', 'pieces', 'ea', 'each', 'unit', 'units',
        'ដុំ', 'ចាន', 'កែវ', 'សន្លឹក', 'គ្រាប់'
    }

    target_category = None  # 'case', 'pack', 'pcs', or 'custom'

    # Step 1: Explicit keyword matching in raw_uom
    if u_str:
        if u_str in CASE_KEYWORDS or any(kw in u_str for kw in ('case', 'ctn', 'carton', 'កេស')):
            target_category = 'case'
        elif u_str in PACK_KEYWORDS or any(kw in u_str for kw in ('pack', 'pkg', 'កញ្ចប់')):
            target_category = 'pack'
        elif u_str in PCS_KEYWORDS:
            # Could be genuine loose pieces, OR default 'pcs' export when item packaging/pricing dictates otherwise
            target_category = None
        else:
            target_category = 'custom'

    # Step 2: Contextual detection if raw_uom is missing, empty, or generic 'pcs'
    if not target_category:
        # Check packaging spec in item name / description
        if pkg_spec and pkg_spec['type'] == 'case':
            ratio_val = pkg_spec['ratio'] or cat_sales_ratio
            if cat_price > 0 and ratio_val > 1:
                if unit_price >= (cat_price * 0.35) or unit_price >= 5.0:
                    target_category = 'case'
                elif unit_price <= ((cat_price / ratio_val) * 1.5):
                    target_category = 'pcs'
                else:
                    target_category = 'case'
            else:
                if unit_price >= 1.0 or not u_str:
                    target_category = 'case'
                else:
                    target_category = 'pcs'

        elif pkg_spec and pkg_spec['type'] == 'pack':
            ratio_val = pkg_spec['ratio'] or cat_purch_ratio or cat_sales_ratio
            if cat_price > 0 and ratio_val > 1:
                if unit_price >= (cat_price * 0.35) or unit_price >= 3.0:
                    target_category = 'pack'
                else:
                    target_category = 'pcs'
            else:
                if unit_price >= 1.0 or not u_str:
                    target_category = 'pack'
                else:
                    target_category = 'pcs'

        elif sales_uom and cat_sales_ratio > 1 and any(kw in sales_uom.lower() for kw in CASE_KEYWORDS):
            # Product in catalog is configured with sales_uom = 'cases'
            if cat_price > 0:
                if unit_price >= (cat_price * 0.35) or unit_price >= 5.0:
                    target_category = 'case'
                else:
                    target_category = 'pcs'
            else:
                if unit_price >= 5.0:
                    target_category = 'case'
                else:
                    target_category = 'pcs' if (u_str and u_str in PCS_KEYWORDS) else 'case'

        elif sales_uom and cat_sales_ratio > 1 and any(kw in sales_uom.lower() for kw in PACK_KEYWORDS):
            target_category = 'pack'

        else:
            target_category = 'pcs'

    # Step 3: Compute final canonical UOM and ratio
    display_qty = max(0.0001, float(qty or 1.0))
    ratio = 1.0
    final_uom = base_uom

    if target_category == 'case':
        if sales_uom and any(kw in sales_uom.lower() for kw in ('case', 'កេស', 'box', 'ctn')):
            final_uom = sales_uom
        else:
            final_uom = 'cases'

        if cat_sales_ratio > 1:
            ratio = cat_sales_ratio
        elif pkg_spec and pkg_spec['ratio'] and pkg_spec['ratio'] > 1:
            ratio = pkg_spec['ratio']
        elif p_info and p_info.get('packs_per_case') and p_info.get('pcs_per_pack'):
            p_case = float(p_info.get('packs_per_case') or 0)
            p_pack = float(p_info.get('pcs_per_pack') or 0)
            if p_case > 0 and p_pack > 0:
                ratio = p_case * p_pack
        else:
            ratio = 1.0

    elif target_category == 'pack':
        if sales_uom and any(kw in sales_uom.lower() for kw in ('pack', 'កញ្ចប់', 'pk')):
            final_uom = sales_uom
        elif purch_uom and any(kw in purch_uom.lower() for kw in ('pack', 'កញ្ចប់', 'pk')):
            final_uom = purch_uom
        else:
            final_uom = 'packs'

        if cat_sales_ratio > 1 and sales_uom and 'pack' in sales_uom.lower():
            ratio = cat_sales_ratio
        elif cat_purch_ratio > 1 and purch_uom and 'pack' in purch_uom.lower():
            ratio = cat_purch_ratio
        elif pkg_spec and pkg_spec['ratio'] and pkg_spec['ratio'] > 1:
            ratio = pkg_spec['ratio']
        elif p_info and p_info.get('pcs_per_pack') and float(p_info.get('pcs_per_pack') or 0) > 1:
            ratio = float(p_info.get('pcs_per_pack'))
        else:
            ratio = 1.0

    elif target_category == 'custom':
        final_uom = (raw_uom or base_uom).strip()
        if sales_uom and final_uom.lower() == sales_uom.lower():
            ratio = cat_sales_ratio
        elif purch_uom and final_uom.lower() == purch_uom.lower():
            ratio = cat_purch_ratio
        else:
            ratio = 1.0

    else:  # 'pcs'
        final_uom = base_uom if base_uom else 'pcs.'
        ratio = 1.0

    std_qty = display_qty * ratio
    return final_uom, display_qty, std_qty


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
    
    result = {
        'data_type': key,
        'data_type_name': meta['display_name'],
        'headers': headers,
        'expected_headers': meta['headers'],
        'preview_rows': preview,
        'total_rows': len(data_rows),
        'import_mode': import_mode
    }

    # For Sales Orders and Purchase Orders, group rows by order number
    # and provide order summary metadata with existing database checks for user selection
    if key in ('sales_order', 'purchase_order') and data_rows:
        norm_headers = [normalize_header(h) for h in headers]

        def get_val_preview(row, header_aliases, default=''):
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

        existing_order_nums = set()
        try:
            if key == 'sales_order':
                rows = query_all("SELECT order_number FROM sales_orders WHERE order_number IS NOT NULL;")
            else:
                rows = query_all("SELECT order_number FROM purchase_orders WHERE order_number IS NOT NULL;")
            for r in (rows or []):
                if r.get('order_number'):
                    existing_order_nums.add(str(r['order_number']).strip().lower())
        except Exception as e:
            logger.warning(f"Could not load existing {key} numbers for preview: {e}")

        orders_grouped = {}
        for r in data_rows:
            if key == 'sales_order':
                ord_num = get_val_preview(r, ['OrderNumber', 'Order Number', 'SO Number', 'Invoice Number', 'Order #'])
                if not ord_num:
                    continue
                if ord_num not in orders_grouped:
                    orders_grouped[ord_num] = {
                        'order_number': ord_num,
                        'party_name': get_val_preview(r, ['Customer', 'CustomerName', 'Customer Name', 'Client'], 'Walk-in Customer'),
                        'order_date': get_val_preview(r, ['OrderDate', 'Order Date', 'Date'], ''),
                        'status': get_val_preview(r, ['OrderStatus', 'Order Status', 'Status', 'State'], 'OPEN').upper(),
                        'freight': clean_num_val(get_val_preview(r, ['Freight', 'Shipping Fee', 'OrderFreight', 'Shipping']), 0.0),
                        'line_subtotals': 0.0,
                        'total_line_count': 0,
                        'items': []
                    }
                item_name = get_val_preview(r, ['ItemName', 'Item Name', 'Item Code', 'ItemCode', 'SKU', 'Product Name'], 'Item')
                qty = clean_num_val(get_val_preview(r, ['ItemQuantity', 'Quantity', 'Qty']), 1.0)
                price = clean_num_val(get_val_preview(r, ['ItemUnitPrice', 'Unit Price', 'Price']), 0.0)
                disc_raw = str(get_val_preview(r, ['ItemDiscount', 'Discount'], '')).strip()
                disc_pct = clean_num_val(disc_raw.replace('%', ''), 0.0) if disc_raw else 0.0
                subtot_raw = clean_num_val(get_val_preview(r, ['ItemSubtotal', 'Subtotal']), None)
                if subtot_raw is not None:
                    line_sub = subtot_raw
                else:
                    line_sub = qty * price * (1.0 - (disc_pct / 100.0))
                orders_grouped[ord_num]['line_subtotals'] += line_sub
                orders_grouped[ord_num]['total_line_count'] += 1
                if len(orders_grouped[ord_num]['items']) < 3:
                    raw_uom = get_val_preview(r, UOM_HEADER_ALIASES, '')
                    p_desc = get_val_preview(r, ['ItemDescription', 'Description', 'Item Description'], '')
                    uom_tag, _, _ = resolve_order_line_uom(raw_uom, item_name, p_desc, None, price, qty)
                    orders_grouped[ord_num]['items'].append(f"{item_name} ({qty:g} {uom_tag})")
            else:  # purchase_order
                ord_num = get_val_preview(r, ['OrderNumber', 'Order Number', 'PO Number', 'Order #'])
                if not ord_num:
                    continue
                if ord_num not in orders_grouped:
                    orders_grouped[ord_num] = {
                        'order_number': ord_num,
                        'party_name': get_val_preview(r, ['Vendor', 'VendorName', 'Vendor Name', 'Supplier'], 'General Supplier'),
                        'order_date': get_val_preview(r, ['OrderDate', 'Order Date', 'Date'], ''),
                        'status': get_val_preview(r, ['OrderStatus', 'Order Status', 'Status'], 'DRAFT').upper(),
                        'freight': 0.0,
                        'line_subtotals': 0.0,
                        'total_line_count': 0,
                        'items': []
                    }
                item_name = get_val_preview(r, ['ItemName', 'Item Name', 'Item Code', 'ItemCode', 'SKU', 'VendorItemCode'], 'Item')
                qty = clean_num_val(get_val_preview(r, ['ItemQuantity', 'Quantity', 'Qty']), 1.0)
                cost = clean_num_val(get_val_preview(r, ['ItemUnitPrice', 'Unit Cost', 'Cost']), 0.0)
                subtot_raw = clean_num_val(get_val_preview(r, ['ItemSubtotal', 'Subtotal']), None)
                line_sub = subtot_raw if subtot_raw is not None else (qty * cost)
                orders_grouped[ord_num]['line_subtotals'] += line_sub
                orders_grouped[ord_num]['total_line_count'] += 1
                if len(orders_grouped[ord_num]['items']) < 3:
                    raw_uom = get_val_preview(r, UOM_HEADER_ALIASES, '')
                    p_desc = get_val_preview(r, ['ItemDescription', 'Description', 'Item Description'], '')
                    uom_tag, _, _ = resolve_order_line_uom(raw_uom, item_name, p_desc, None, cost, qty)
                    orders_grouped[ord_num]['items'].append(f"{item_name} ({qty:g} {uom_tag})")

        orders_summary = []
        for ord_num, odata in orders_grouped.items():
            total = round(odata['line_subtotals'] + odata['freight'], 2)
            is_exist = (str(ord_num).strip().lower() in existing_order_nums)
            items_str = ", ".join(odata['items'])
            if odata['total_line_count'] > len(odata['items']):
                items_str += f", +{odata['total_line_count'] - len(odata['items'])} more"
            orders_summary.append({
                'order_number': ord_num,
                'party_name': odata['party_name'],
                'order_date': odata['order_date'] or '-',
                'status': odata['status'],
                'item_count': odata['total_line_count'],
                'total_amount': total,
                'is_existing': is_exist,
                'items_summary': items_str
            })

        result['orders_summary'] = orders_summary
        result['total_orders'] = len(orders_summary)

    return result


def execute_import_data(data_type, file_content, has_headers=True, import_mode='keep', selected_orders=None, selected_rows=None):
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
    skipped_orders_cnt = 0
    errors = []

    # Parse and normalize selected_orders filter if provided
    selected_orders_set = None
    if selected_orders is not None:
        if isinstance(selected_orders, (str, bytes)):
            try:
                selected_orders = json.loads(selected_orders)
            except Exception:
                selected_orders = [s.strip() for s in str(selected_orders).split(',') if s.strip()]
        if isinstance(selected_orders, (list, tuple, set)):
            selected_orders_set = {str(x).strip().lower() for x in selected_orders if str(x).strip()}

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
                uom = get_val(r, ['Uom', 'UOM', 'Unit', 'Unit of Measure', 'BaseUom', 'Base UOM'], 'pcs.')
                sales_uom_val = get_val(r, ['SalesUom', 'Sales UoM', 'Sales Unit', 'SalesUOM'])
                sales_ratio_val = clean_num_val(get_val(r, ['SalesUomRatio', 'Sales UoM Ratio', 'Sales Ratio', 'PcsPerCase']), 0.0)
                pkg_spec = extract_packaging_spec(f"{name} {desc or ''}")
                if not sales_uom_val and pkg_spec:
                    sales_uom_val = 'cases' if pkg_spec['type'] == 'case' else 'packs'
                if sales_ratio_val <= 1 and pkg_spec and pkg_spec['ratio']:
                    sales_ratio_val = pkg_spec['ratio']

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
                            sales_uom = COALESCE(NULLIF(%s, ''), sales_uom),
                            sales_uom_ratio_std = CASE WHEN %s > 1 THEN %s ELSE sales_uom_ratio_std END,
                            purchasing_uom = COALESCE(NULLIF(%s, ''), purchasing_uom),
                            purchasing_uom_ratio_std = CASE WHEN %s > 1 THEN %s ELSE purchasing_uom_ratio_std END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (name, desc, cat_id, barcode, price_val, cost_val, uom, remarks, is_active,
                          sales_uom_val, sales_ratio_val, sales_ratio_val,
                          sales_uom_val, sales_ratio_val, sales_ratio_val, existing_id))
                    updated_cnt += 1
                else:
                    cur.execute("""
                        INSERT INTO products (
                            sku, name, description, category_id, barcode, default_price, standard_cost,
                            uom, remarks, is_active, sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (sku, name, desc, cat_id, barcode, price_val, cost_val, uom, remarks, is_active,
                          sales_uom_val, sales_ratio_val if sales_ratio_val > 1 else 1.0,
                          sales_uom_val, sales_ratio_val if sales_ratio_val > 1 else 1.0))
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
        BATCH_SIZE = 500  # Commit every N orders to avoid timeout on large imports
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
                'uom': get_val(r, UOM_HEADER_ALIASES, ''),
                'price': clean_num_val(get_val(r, ['ItemUnitPrice', 'Unit Price', 'Price']), 0.0),
                'discount_raw': get_val(r, ['ItemDiscount', 'Discount']),
                'subtotal_raw': clean_num_val(get_val(r, ['ItemSubtotal', 'Subtotal']), None)
            })

        # Filter orders if user selected specific orders to import
        if selected_orders_set is not None:
            filtered_orders = {}
            for so_num, ord_data in orders_map.items():
                if str(so_num).strip().lower() in selected_orders_set:
                    filtered_orders[so_num] = ord_data
                else:
                    skipped_orders_cnt += 1
            orders_map = filtered_orders

        # Cache existing customers, products, and locations
        cust_map = {c['name'].lower().strip(): c['id'] for c in query_all("SELECT id, name FROM customers;")}
        prod_map = {}
        for p in query_all("""
            SELECT id, sku, name, default_price, standard_cost, average_cost, uom,
                   sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std,
                   packs_per_case, pcs_per_pack
            FROM products;
        """):
            if p.get('sku'):
                prod_map[p['sku'].lower().strip()] = p
            if p.get('name'):
                prod_map[p['name'].lower().strip()] = p

        loc_map = {l['name'].lower().strip(): l['id'] for l in query_all("SELECT id, name FROM locations;")}

        batch_count = 0
        total_orders = len(orders_map)
        with get_db_cursor(commit=True) as cur:
            for so_num, order_data in orders_map.items():
                batch_count += 1
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

                    # Check packaging spec from item_name and desc
                    pkg_spec = extract_packaging_spec(f"{item_name} {line['desc'] or ''}")

                    # Auto-create missing product in catalog
                    if not prod_id and item_name:
                        if pkg_spec and pkg_spec['type'] == 'case' and pkg_spec['ratio']:
                            new_base = 'pcs.'
                            new_sales = 'cases'
                            new_ratio = pkg_spec['ratio']
                        elif pkg_spec and pkg_spec['type'] == 'pack' and pkg_spec['ratio']:
                            new_base = 'pcs.'
                            new_sales = 'packs'
                            new_ratio = pkg_spec['ratio']
                        else:
                            new_base = 'pcs.'
                            new_sales = None
                            new_ratio = 1.0

                        cur.execute("""
                            INSERT INTO products (
                                sku, name, default_price, uom, sales_uom, sales_uom_ratio_std,
                                purchasing_uom, purchasing_uom_ratio_std, is_active
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                            RETURNING id, default_price, uom, sales_uom, sales_uom_ratio_std;
                        """, (item_name[:50], item_name, line['price'], new_base, new_sales, new_ratio, new_sales, new_ratio))
                        created_p = cur.fetchone()
                        prod_id = created_p['id']
                        prod_map[item_name.lower()] = {
                            'id': prod_id,
                            'sku': item_name[:50],
                            'name': item_name,
                            'default_price': line['price'],
                            'standard_cost': 0.0,
                            'average_cost': 0.0,
                            'uom': new_base,
                            'sales_uom': new_sales,
                            'sales_uom_ratio_std': new_ratio,
                            'purchasing_uom': new_sales,
                            'purchasing_uom_ratio_std': new_ratio,
                            'packs_per_case': 3,
                            'pcs_per_pack': 50
                        }
                        p_info = prod_map[item_name.lower()]
                    elif p_info:
                        # If product exists in catalog but had sales_uom empty/null and ratio <= 1, self-heal it
                        if pkg_spec and pkg_spec['ratio'] and pkg_spec['ratio'] > 1:
                            curr_ratio = float(p_info.get('sales_uom_ratio_std') or 1.0)
                            curr_sales = (p_info.get('sales_uom') or '').strip()
                            if not curr_sales or curr_ratio <= 1:
                                u_name = 'cases' if pkg_spec['type'] == 'case' else 'packs'
                                cur.execute("""
                                    UPDATE products
                                    SET sales_uom = %s,
                                        sales_uom_ratio_std = %s,
                                        purchasing_uom = COALESCE(NULLIF(purchasing_uom, ''), %s),
                                        purchasing_uom_ratio_std = CASE WHEN (purchasing_uom_ratio_std IS NULL OR purchasing_uom_ratio_std <= 1) THEN %s ELSE purchasing_uom_ratio_std END
                                    WHERE id = %s;
                                """, (u_name, pkg_spec['ratio'], u_name, pkg_spec['ratio'], prod_id))
                                p_info['sales_uom'] = u_name
                                p_info['sales_uom_ratio_std'] = pkg_spec['ratio']

                    qty = line['qty']
                    unit_p = line['price'] if line['price'] > 0 else (float(p_info['default_price']) if p_info and p_info.get('default_price') else 0.0)

                    # Intelligently resolve unit: pcs, case, or pack
                    final_uom, display_qty, std_qty = resolve_order_line_uom(
                        raw_uom=line['uom'],
                        item_name=item_name,
                        desc=line['desc'],
                        p_info=p_info,
                        unit_price=unit_p,
                        qty=qty
                    )

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
                        subtot = display_qty * unit_p * (1.0 - (disc_pct / 100.0))

                    calculated_subtotal += subtot
                    desc = line['desc'] or (p_info['name'] if p_info else item_name)
                    cost_p = float(p_info.get('standard_cost') or p_info.get('average_cost') or 0.0) if p_info else 0.0
                    parsed_lines.append({
                        'prod_id': prod_id,
                        'desc': desc,
                        'qty': qty,
                        'display_qty': display_qty,
                        'std_qty': std_qty,
                        'uom': final_uom,
                        'unit_price': unit_p,
                        'cost_price': cost_p,
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
                            quantity, unit_price, discount_percent, subtotal, cost_price,
                            uom, quantity_display, pricing_scheme_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 100);
                    """, (
                        so_id, l_idx, pline['prod_id'], pline['desc'],
                        pline['std_qty'], pline['unit_price'], pline['discount'], pline['subtotal'], pline['cost_price'],
                        pline['uom'], pline['display_qty']
                    ))

                # Periodic batch commit to avoid timeout on large imports
                if batch_count % BATCH_SIZE == 0:
                    cur.connection.commit()
                    logger.info(f"Sales order import progress: {batch_count}/{total_orders} orders committed.")

            # Automatically resynchronize sequences after importing sales orders
            resync_all_sequences(cur=cur)

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
                'uom': get_val(r, UOM_HEADER_ALIASES, ''),
                'cost': clean_num_val(get_val(r, ['ItemUnitPrice', 'Unit Cost', 'Cost']), 0.0),
                'subtotal_raw': clean_num_val(get_val(r, ['ItemSubtotal', 'Subtotal']), None)
            })

        # Filter orders if user selected specific orders to import
        if selected_orders_set is not None:
            filtered_orders = {}
            for po_num, ord_data in orders_map.items():
                if str(po_num).strip().lower() in selected_orders_set:
                    filtered_orders[po_num] = ord_data
                else:
                    skipped_orders_cnt += 1
            orders_map = filtered_orders

        vend_map = {v['name'].lower().strip(): v['id'] for v in query_all("SELECT id, name FROM vendors;")}
        prod_map = {}
        for p in query_all("""
            SELECT id, sku, name, standard_cost, average_cost, uom,
                   sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std,
                   packs_per_case, pcs_per_pack
            FROM products;
        """):
            if p.get('sku'):
                prod_map[p['sku'].lower().strip()] = p
            if p.get('name'):
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

                    final_uom, display_qty, std_qty = resolve_order_line_uom(
                        raw_uom=line.get('uom', ''),
                        item_name=item_name,
                        desc=desc,
                        p_info=p_info,
                        unit_price=cost,
                        qty=qty
                    )

                    cur.execute("""
                        INSERT INTO purchase_order_lines (purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal, uom)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """, (po_id, l_idx, prod_id, desc, qty, cost, subtot, final_uom))

                cur.execute("UPDATE purchase_orders SET subtotal = %s, total_amount = %s WHERE id = %s;",
                            (total_subtotal, total_subtotal, po_id))

            # Automatically resynchronize sequences after importing purchase orders
            resync_all_sequences(cur=cur)

    mode_text = "cleanly replaced" if is_erase_mode else "processed"
    msg = f"Import completed successfully! {imported_cnt} records added, {updated_cnt} updated"
    if skipped_orders_cnt > 0:
        msg += f", {skipped_orders_cnt} skipped"
    msg += f" ({mode_text} under '{import_mode}' mode)."

    return {
        'success': True,
        'imported': imported_cnt,
        'updated': updated_cnt,
        'skipped': skipped_orders_cnt,
        'mode': import_mode,
        'errors': errors[:50],  # cap returned error messages
        'message': msg
    }
