from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, send_file
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val, get_next_order_number, preview_order_number
from datetime import datetime, date
import os
import time
from werkzeug.utils import secure_filename
from services.po_exporter import generate_po_excel, process_po_lines_for_export

def _match_uom(uom1, uom2):
    """Checks whether two UOM strings refer to the same unit (case vs cases, pack vs packs, pcs vs pcs.)."""
    if not uom1 or not uom2:
        return False
    u1 = str(uom1).strip().lower().rstrip('.')
    u2 = str(uom2).strip().lower().rstrip('.')
    if u1 == u2:
        return True
    if u1 in ('case', 'cases', 'box', 'boxes', 'carton', 'cartons', 'កេស', 'កាតុង') and u2 in ('case', 'cases', 'box', 'boxes', 'carton', 'cartons', 'កេស', 'កាតុង'):
        return True
    if u1 in ('pack', 'packs', 'packet', 'packets', 'ដុំ', 'កញ្ចប់') and u2 in ('pack', 'packs', 'packet', 'packets', 'ដុំ', 'កញ្ចប់'):
        return True
    if u1 in ('pc', 'pcs', 'piece', 'pieces', 'each', 'ea', 'ចាន', 'កែវ', 'ដប', 'កំប៉ុង', 'គ្រាប់', 'សន្លឹក') and u2 in ('pc', 'pcs', 'piece', 'pieces', 'each', 'ea', 'ចាន', 'កែវ', 'ដប', 'កំប៉ុង', 'គ្រាប់', 'សន្លឹក'):
        return True
    return False

purchase_orders_bp = Blueprint('purchase_orders', __name__)

@purchase_orders_bp.route('/purchases')
def list_purchases():
    if request.args.get('view') == 'table':
        return _render_table_list_purchases()

    selected_id = request.args.get('id', type=int)
    if not selected_id:
        latest = query_one("SELECT id FROM purchase_orders ORDER BY order_date DESC, id DESC LIMIT 1")
        if latest:
            selected_id = latest['id']
    if selected_id:
        return detail_purchase(selected_id)
    return create_purchase()

def _render_table_list_purchases():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    offset = (page - 1) * per_page

    status = request.args.get('status', '').strip()
    payment_status = request.args.get('payment_status', '').strip()
    search = request.args.get('search', '').strip()
    vendor_id = request.args.get('vendor_id', '').strip()
    location_id = request.args.get('location_id', '').strip()

    where_clauses = ["1=1"]
    params = []

    if status:
        where_clauses.append("po.status = %s")
        params.append(status)

    if payment_status:
        where_clauses.append("po.payment_status = %s")
        params.append(payment_status)

    if vendor_id and vendor_id.isdigit():
        where_clauses.append("po.vendor_id = %s")
        params.append(int(vendor_id))

    if location_id and location_id.isdigit():
        where_clauses.append("po.location_id = %s")
        params.append(int(location_id))

    if search:
        where_clauses.append("(po.order_number ILIKE %s OR v.name ILIKE %s OR v.phone ILIKE %s OR COALESCE(po.vendor_invoice_no, '') ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp, sp])

    where_sql = " AND ".join(where_clauses)

    count_sql = f"""
        SELECT COUNT(*) as cnt 
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        WHERE {where_sql}
    """
    total_count = query_one(count_sql, tuple(params))['cnt']
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    list_sql = f"""
        SELECT 
            po.*,
            v.name as vendor_name,
            v.phone as vendor_phone,
            l.name as location_name,
            COUNT(pol.id) as line_count,
            COALESCE(SUM(pol.quantity), 0) as total_qty_ordered,
            COALESCE(SUM(pol.received_qty), 0) as total_qty_received
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        LEFT JOIN purchase_order_lines pol ON po.id = pol.purchase_order_id
        WHERE {where_sql}
        GROUP BY po.id, v.name, v.phone, l.name
        ORDER BY po.order_date DESC, po.id DESC
        LIMIT %s OFFSET %s
    """
    rows_params = params.copy()
    rows_params.extend([per_page, offset])
    orders = query_all(list_sql, tuple(rows_params))

    # Comprehensive Global KPI Stats for the top cards
    kpi_raw = query_one("""
        SELECT 
            COUNT(*) as total_orders,
            COUNT(CASE WHEN status IN ('ISSUED', 'PARTIAL_RECEIVED') THEN 1 END) as pending_receiving,
            COUNT(CASE WHEN status = 'RECEIVED' THEN 1 END) as received_orders,
            COUNT(CASE WHEN status = 'PAID' OR payment_status = 'PAID' THEN 1 END) as paid_orders,
            COUNT(CASE WHEN status = 'CANCELLED' THEN 1 END) as cancelled_orders,
            COALESCE(SUM(CASE WHEN status != 'CANCELLED' THEN total_amount ELSE 0 END), 0) as total_spend,
            COALESCE(SUM(CASE WHEN status != 'CANCELLED' THEN balance_due ELSE 0 END), 0) as total_payables
        FROM purchase_orders;
    """)

    status_counts = query_all("SELECT status, COUNT(*) as cnt FROM purchase_orders GROUP BY status")
    stats_dict = {r['status']: r['cnt'] for r in status_counts}

    vendors = query_all("SELECT id, name FROM vendors WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")

    return render_template('purchases/list.html',
                           orders=orders,
                           status=status,
                           payment_status=payment_status,
                           search=search,
                           vendor_id=vendor_id,
                           location_id=location_id,
                           vendors=vendors,
                           locations=locations,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           stats_dict=stats_dict,
                           kpi=kpi_raw)

def _get_po_drawer_data(date_filter='All', status_filter='All', vendor_search='', order_search=''):
    where_clauses = ["1=1"]
    params = []

    if order_search:
        where_clauses.append("(po.order_number ILIKE %s OR COALESCE(po.vendor_invoice_no, '') ILIKE %s)")
        sp = f"%{order_search}%"
        params.extend([sp, sp])

    if vendor_search:
        if str(vendor_search).isdigit():
            where_clauses.append("po.vendor_id = %s")
            params.append(int(vendor_search))
        else:
            where_clauses.append("v.name ILIKE %s")
            params.append(f"%{vendor_search}%")

    if date_filter == 'Today':
        where_clauses.append("po.order_date = CURRENT_DATE")
    elif date_filter == 'This Week':
        where_clauses.append("date_trunc('week', po.order_date::timestamp) = date_trunc('week', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Month':
        where_clauses.append("date_trunc('month', po.order_date::timestamp) = date_trunc('month', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Quarter':
        where_clauses.append("date_trunc('quarter', po.order_date::timestamp) = date_trunc('quarter', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Year':
        where_clauses.append("date_trunc('year', po.order_date::timestamp) = date_trunc('year', CURRENT_DATE::timestamp)")
    elif date_filter == 'Yesterday':
        where_clauses.append("po.order_date = CURRENT_DATE - INTERVAL '1 day'")
    elif date_filter == 'Last Week':
        where_clauses.append("date_trunc('week', po.order_date::timestamp) = date_trunc('week', CURRENT_DATE::timestamp - INTERVAL '1 week')")
    elif date_filter == 'Last Month':
        where_clauses.append("date_trunc('month', po.order_date::timestamp) = date_trunc('month', CURRENT_DATE::timestamp - INTERVAL '1 month')")
    elif date_filter == 'Last Quarter':
        where_clauses.append("date_trunc('quarter', po.order_date::timestamp) = date_trunc('quarter', CURRENT_DATE::timestamp - INTERVAL '3 months')")
    elif date_filter == 'Last Year':
        where_clauses.append("date_trunc('year', po.order_date::timestamp) = date_trunc('year', CURRENT_DATE::timestamp - INTERVAL '1 year')")
    elif date_filter == 'Last 7 Days':
        where_clauses.append("po.order_date >= CURRENT_DATE - INTERVAL '7 days' AND po.order_date <= CURRENT_DATE")
    elif date_filter == 'Last 30 Days':
        where_clauses.append("po.order_date >= CURRENT_DATE - INTERVAL '30 days' AND po.order_date <= CURRENT_DATE")

    if status_filter and status_filter.strip() not in ('All', ''):
        parts = [p.strip() for p in status_filter.split(',') if p.strip()]
        status_clauses = []
        for p in parts:
            if p == 'Open':
                status_clauses.append("po.status IN ('ISSUED', 'OPEN')")
            elif p in ('In Progress', 'Partial'):
                status_clauses.append("po.status IN ('PARTIAL_RECEIVED', 'IN_PROGRESS', 'PARTIAL')")
            elif p == 'Received':
                status_clauses.append("po.status IN ('RECEIVED', 'FULFILLED')")
            elif p == 'Paid':
                status_clauses.append("(po.status = 'PAID' OR po.payment_status = 'PAID')")
            elif p == 'Cancelled':
                status_clauses.append("po.status IN ('CANCELLED', 'VOID')")
        if status_clauses:
            where_clauses.append("(" + " OR ".join(status_clauses) + ")")

    sql = f"""
        SELECT 
            po.id, po.order_number, po.order_date, po.status, po.payment_status,
            po.vendor_id, po.location_id, po.vendor_invoice_no, po.expected_date,
            po.subtotal, po.shipping_fee, po.discount_amount, po.total_amount,
            po.paid_amount, po.balance_due,
            v.name as vendor_name,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY po.order_date DESC, po.id DESC
        LIMIT 1000;
    """
    sidebar_orders = query_all(sql, tuple(params))

    vendors_sql = """
        SELECT 
            v.id, v.name, v.phone, v.contact_name, v.balance, v.address1, v.payment_terms,
            last_po.order_number as last_order_number,
            last_po.order_date as last_order_date,
            last_po.status as last_order_status,
            last_po.total_amount as last_order_total
        FROM vendors v
        LEFT JOIN LATERAL (
            SELECT order_number, order_date, status, total_amount
            FROM purchase_orders
            WHERE vendor_id = v.id
            ORDER BY order_date DESC, id DESC
            LIMIT 1
        ) last_po ON TRUE
        WHERE v.is_active = TRUE
        ORDER BY v.name ASC;
    """
    all_vendors = query_all(vendors_sql)

    all_locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC;")

    products_sql = """
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.image_url,
            COALESCE(p.uom, 'pcs.') as uom,
            COALESCE(p.purchasing_uom, p.uom, 'pcs.') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, p.master_pack_qty, p.inner_pack_qty, 1.0) as purchasing_ratio,
            COALESCE(p.sales_uom, p.uom, 'pcs.') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_ratio,
            COALESCE(p.costing_sheet_cost, p.standard_cost, p.last_purchase_cost, p.average_cost, 0) as cost_price,
            COALESCE(p.standard_cost, 0) as standard_cost,
            COALESCE(p.costing_sheet_cost, 0) as costing_sheet_cost,
            COALESCE(p.default_price, 0) as unit_price,
            COALESCE(inv.total_qty, 0) as on_hand,
            COALESCE(inv.reserved_qty, 0) as reserved_qty,
            (COALESCE(inv.total_qty, 0) - COALESCE(inv.reserved_qty, 0)) as avail_qty,
            COALESCE(po_ord.on_order_qty, 0) as on_order_qty
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty, SUM(COALESCE(reserved_quantity, 0)) as reserved_qty 
            FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        LEFT JOIN (
            SELECT pol.product_id, SUM(pol.quantity - pol.received_qty) as on_order_qty
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            WHERE po.status IN ('ISSUED', 'PARTIAL_RECEIVED')
            GROUP BY pol.product_id
        ) po_ord ON p.id = po_ord.product_id
        WHERE p.is_active = TRUE
        ORDER BY p.name ASC;
    """
    all_products = query_all(products_sql)

    return {
        'sidebar_orders': sidebar_orders,
        'all_vendors': all_vendors,
        'all_locations': all_locations,
        'all_products': all_products
    }

@purchase_orders_bp.route('/api/vendors/<int:id>/summary')
def api_vendor_summary(id):
    v = query_one("""
        SELECT 
            v.id, v.name, v.phone, v.contact_name, v.balance, v.address1, v.payment_terms,
            last_po.order_number as last_order_number,
            last_po.order_date as last_order_date,
            last_po.status as last_order_status,
            last_po.total_amount as last_order_total
        FROM vendors v
        LEFT JOIN LATERAL (
            SELECT order_number, order_date, status, total_amount
            FROM purchase_orders
            WHERE vendor_id = v.id
            ORDER BY order_date DESC, id DESC
            LIMIT 1
        ) last_po ON TRUE
        WHERE v.id = %s;
    """, (id,))
    if not v:
        return jsonify({'success': False, 'message': 'Vendor not found'}), 404
    
    last_status = v['last_order_status']
    if last_status == 'ISSUED':
        last_status = 'Open'
    elif last_status == 'PARTIAL_RECEIVED':
        last_status = 'In Progress'

    return jsonify({
        'success': True,
        'vendor': {
            'id': v['id'],
            'name': v['name'],
            'contact_name': v['contact_name'] or '',
            'phone': v['phone'] or '',
            'address': v['address1'] or '',
            'balance': float(v['balance'] or 0),
            'payment_terms': v['payment_terms'] or 'Net 30',
            'last_order_number': v['last_order_number'] or '',
            'last_order_date': v['last_order_date'].strftime('%d-%b-%y') if v['last_order_date'] else '',
            'last_order_status': last_status or '',
            'last_order_total': float(v['last_order_total'] or 0)
        }
    })

def _format_po_status_label(o):
    st = o.get('status') or ''
    if st in ('RECEIVED', 'FULFILLED'):
        return 'Fulfilled'
    if st in ('PARTIAL_RECEIVED', 'IN_PROGRESS', 'PARTIAL'):
        return 'Partial'
    if st in ('CANCELLED', 'VOID'):
        return 'Cancelled'
    return 'Unfulfilled'

@purchase_orders_bp.route('/api/purchases/drawer')
def api_purchases_drawer():
    date_filter = request.args.get('date_filter', 'All')
    status_filter = request.args.get('status_filter', 'All')
    vendor_search = request.args.get('vendor_search', '') or request.args.get('vendor_id', '')
    order_search = request.args.get('order_search', '')
    data = _get_po_drawer_data(date_filter, status_filter, vendor_search, order_search)
    return jsonify({
        'success': True,
        'orders': [{
            'id': o['id'],
            'order_number': o['order_number'],
            'order_date': o['order_date'].strftime('%b %d, %Y') if o['order_date'] else '',
            'raw_date': o['order_date'].strftime('%Y-%m-%d') if o['order_date'] else '',
            'status': _format_po_status_label(o),
            'status_badge': _format_po_status_label(o),
            'raw_status': o['status'],
            'payment_status': o['payment_status'] or 'UNPAID',
            'vendor_id': o['vendor_id'],
            'vendor_name': o['vendor_name'] or '',
            'vendor_invoice_no': o['vendor_invoice_no'] or '',
            'location_name': o['location_name'] or '',
            'expected_date': o['expected_date'].strftime('%b %d, %Y') if o['expected_date'] else '',
            'total_amount': float(o['total_amount'] or 0),
            'paid_amount': float(o['paid_amount'] or 0),
            'balance_due': float(o['balance_due'] or 0)
        } for o in data['sidebar_orders']]
    })

@purchase_orders_bp.route('/api/purchases/<int:id>/data')
def api_purchase_data(id):
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            COALESCE(po.contact, v.contact_name, '') as contact,
            COALESCE(po.phone, v.phone, '') as phone,
            COALESCE(po.vendor_address, v.address1, '') as vendor_address,
            v.balance as vendor_balance,
            v.payment_terms as vendor_payment_terms,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE po.id = %s
    """, (id,))
    if not order:
        return jsonify({'success': False, 'message': 'Purchase order not found'}), 404

    lines = query_all("""
        SELECT 
            pol.*,
            COALESCE(pol.uom, p.purchasing_uom, p.uom, 'pcs.') as line_uom,
            p.name as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            p.image_url as product_image,
            COALESCE(p.uom, 'pcs.') as product_uom,
            COALESCE(p.purchasing_uom, p.uom, 'pcs.') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, p.master_pack_qty, p.inner_pack_qty, 1.0) as purchasing_ratio,
            COALESCE(p.sales_uom, p.uom, 'pcs.') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_ratio,
            COALESCE(p.costing_sheet_cost, p.standard_cost, p.last_purchase_cost, p.average_cost, 0) as cost_price,
            p.average_cost as product_avg_cost,
            p.last_purchase_cost as product_last_cost
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    total_qty_ordered = sum(float(l['quantity'] or 0) for l in lines)
    total_qty_received = sum(float(l['received_qty'] or 0) for l in lines)
    receiving_percent = int((total_qty_received / total_qty_ordered * 100) if total_qty_ordered > 0 else 0)

    att_row = query_one("SELECT COUNT(*) as cnt FROM purchase_order_attachments WHERE purchase_order_id = %s", (id,))
    attachment_count = att_row['cnt'] if att_row else 0

    st = order.get('status') or ''
    if st in ('RECEIVED', 'FULFILLED'):
        badge = 'Fulfilled'
    elif st in ('PARTIAL_RECEIVED', 'IN_PROGRESS', 'PARTIAL'):
        badge = 'Partial'
    elif st in ('CANCELLED', 'VOID'):
        badge = 'Cancelled'
    else:
        badge = 'Unfulfilled'

    # Check if this PO is already linked to an expense
    linked_expense = query_one("""
        SELECT id, expense_date, total_price, category, paid_by, month_key 
        FROM expenses 
        WHERE notes ILIKE %s OR item ILIKE %s
        ORDER BY id DESC LIMIT 1
    """, (f"%{order['order_number']}%", f"%{order['order_number']}%"))

    linked_expense_data = None
    if linked_expense:
        linked_expense_data = {
            'id': linked_expense['id'],
            'expense_date': linked_expense['expense_date'].strftime('%Y-%m-%d') if linked_expense['expense_date'] else '',
            'total_price': float(linked_expense['total_price'] or 0),
            'category': linked_expense['category'] or 'Purchases',
            'paid_by': linked_expense['paid_by'] or 'ABA Bank',
            'month_key': linked_expense['month_key'] or ''
        }

    return jsonify({
        'success': True,
        'order': {
            'id': order['id'],
            'order_number': order['order_number'],
            'order_date': order['order_date'].strftime('%b %d, %Y') if order['order_date'] else '',
            'order_date_raw': order['order_date'].strftime('%Y-%m-%d') if order['order_date'] else '',
            'order_date_inflow': order['order_date'].strftime('%d-%b-%Y') if order['order_date'] else '',
            'expected_date': order['expected_date'].strftime('%b %d, %Y') if order['expected_date'] else '',
            'expected_date_raw': order['expected_date'].strftime('%Y-%m-%d') if order['expected_date'] else '',
            'status': order['status'],
            'status_badge': badge,
            'payment_status': order['payment_status'] or 'UNPAID',
            'vendor_id': order['vendor_id'],
            'vendor_name': order['vendor_name'] or 'None',
            'contact': order['contact'] or '',
            'phone': order['phone'] or '',
            'vendor_address': order['vendor_address'] or '',
            'location_id': order['location_id'],
            'location_name': order['location_name'] or 'Main Warehouse',
            'carrier': order['carrier'] or '',
            'vendor_invoice_no': order['vendor_invoice_no'] or '',
            'subtotal': float(order['subtotal'] or 0),
            'shipping_fee': float(order['shipping_fee'] or 0),
            'discount_amount': float(order['discount_amount'] or 0),
            'total_amount': float(order['total_amount'] or 0),
            'paid_amount': float(order['paid_amount'] or 0),
            'balance_due': float(order['balance_due'] or 0),
            'currency_code': order['currency_code'] or 'USD',
            'notes': order['notes'] or '',
            'sales_rep': order.get('sales_rep') or 'Admin',
            'payment_terms': order.get('vendor_payment_terms') or 'Net 30',
            'attachment_count': attachment_count
        },
        'lines': [{
            'id': l['id'],
            'product_id': l['product_id'],
            'product_name': l['product_name'],
            'product_sku': l['product_sku'],
            'product_barcode': l['product_barcode'],
            'product_image': l.get('product_image') or '',
            'vendor_product_code': l.get('vendor_product_code') or '',
            'quantity': float(l['quantity'] or 0),
            'unit_cost': float(l['unit_cost'] or 0),
            'discount_percent': float(l['discount_percent'] or 0),
            'subtotal': float(l['subtotal'] or 0),
            'line_uom': l['line_uom'],
            'received_qty': float(l['received_qty'] or 0),
            'product_uom': l['product_uom'],
            'purchasing_uom': l['purchasing_uom'],
            'purchasing_ratio': float(l['purchasing_ratio'] or 1.0),
            'sales_uom': l['sales_uom'],
            'sales_ratio': float(l['sales_ratio'] or 1.0),
            'cost_price': float(l['cost_price'] or 0.0)
        } for l in lines],
        'total_qty_ordered': total_qty_ordered,
        'total_qty_received': total_qty_received,
        'receiving_percent': receiving_percent,
        'attachment_count': attachment_count,
        'linked_expense': linked_expense_data
    })

@purchase_orders_bp.route('/purchases/new')
@purchase_orders_bp.route('/purchases/create', methods=['GET', 'POST'])
def create_purchase():
    if request.method == 'GET':
        date_filter = request.args.get('date_filter', 'All')
        status_filter = request.args.get('status_filter', 'All')
        vendor_search = request.args.get('vendor_search', '')
        order_search = request.args.get('order_search', '')

        drawer_data = _get_po_drawer_data(date_filter, status_filter, vendor_search, order_search)

        # Calculate preview PO number
        preview_po_number = preview_order_number('PO')

        prefill_vendor_id = request.args.get('vendor_id')
        prefill_vendor = None
        if prefill_vendor_id and str(prefill_vendor_id).isdigit():
            prefill_vendor = next((v for v in drawer_data['all_vendors'] if v['id'] == int(prefill_vendor_id)), None)

        prefill_prod_id = request.args.get('product_id')
        prefill_prod = None
        if prefill_prod_id:
            prefill_prod = query_one("""
                SELECT p.*, 
                       COALESCE(p.last_purchase_cost, p.average_cost, p.standard_cost, 0) as purchase_cost,
                       COALESCE(inv.total_qty, 0) as on_hand
                FROM products p
                LEFT JOIN (SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id) inv ON p.id = inv.product_id
                WHERE p.id = %s
            """, (prefill_prod_id,))

        default_location = next((l['id'] for l in drawer_data['all_locations'] if l.get('is_default')), drawer_data['all_locations'][0]['id'] if drawer_data['all_locations'] else 1)

        draft_order = {
            'id': 0,
            'order_number': preview_po_number,
            'order_date': date.today(),
            'status': 'ISSUED',
            'payment_status': 'UNPAID',
            'vendor_id': prefill_vendor['id'] if prefill_vendor else None,
            'vendor_name': prefill_vendor['name'] if prefill_vendor else '',
            'contact': prefill_vendor['contact_name'] if prefill_vendor else '',
            'phone': prefill_vendor['phone'] if prefill_vendor else '',
            'vendor_address': prefill_vendor['address1'] if prefill_vendor else '',
            'location_id': default_location,
            'carrier': '',
            'vendor_invoice_no': '',
            'subtotal': 0.0,
            'shipping_fee': 0.0,
            'discount_amount': 0.0,
            'total_amount': 0.0,
            'paid_amount': 0.0,
            'balance_due': 0.0,
            'notes': '',
            'non_vendor_costs': 0.0,
            'currency_code': 'USD'
        }

        lines = []
        if prefill_prod:
            base_u = prefill_prod.get('uom') or 'pcs.'
            purch_u = prefill_prod.get('purchasing_uom') or base_u
            purch_r = float(prefill_prod.get('purchasing_uom_ratio_std') or prefill_prod.get('master_pack_qty') or 1.0)
            sales_u = prefill_prod.get('sales_uom') or base_u
            sales_r = float(prefill_prod.get('sales_uom_ratio_std') or 1.0)
            lines.append({
                'id': 0,
                'line_num': 1,
                'product_id': prefill_prod['id'],
                'product_sku': prefill_prod['sku'],
                'product_name': prefill_prod['name'],
                'product_barcode': prefill_prod['barcode'],
                'product_uom': base_u,
                'base_uom': base_u,
                'line_uom': purch_u,
                'purchasing_uom': purch_u,
                'purchasing_ratio': purch_r,
                'sales_uom': sales_u,
                'sales_ratio': sales_r,
                'vendor_product_code': '',
                'description': prefill_prod['name'],
                'quantity': 1,
                'unit_cost': float(prefill_prod['purchase_cost']),
                'discount_percent': 0.0,
                'subtotal': float(prefill_prod['purchase_cost']),
                'received_qty': 0.0,
                'on_hand_stock': float(prefill_prod['on_hand']),
                'stock_on_hand': float(prefill_prod['on_hand']),
                'stock_reserved': 0.0,
                'stock_avail': float(prefill_prod['on_hand']),
                'stock_on_order': 0.0
            })
            draft_order['subtotal'] = float(prefill_prod['purchase_cost'])
            draft_order['total_amount'] = float(prefill_prod['purchase_cost'])
            draft_order['balance_due'] = float(prefill_prod['purchase_cost'])

        company = query_one("SELECT * FROM companies LIMIT 1")

        return render_template('purchases/detail.html',
                               is_new=True,
                               order=draft_order,
                               lines=lines,
                               payments=[],
                               inventory_logs=[],
                               total_qty_ordered=sum(l['quantity'] for l in lines),
                               total_qty_received=0,
                               receiving_percent=0,
                               attachments=[],
                               attachment_count=0,
                               linked_expense=None,
                               expense_categories=['Purchases', 'Inventory', 'Packaging', 'Raw Materials', 'General'],
                               expense_payers=['ABA Bank', 'Cash', 'Bank Transfer'],
                               company=company,
                               date_filter=date_filter,
                               status_filter=status_filter,
                               vendor_search=vendor_search,
                               order_search=order_search,
                               preview_po_number=preview_po_number,
                               **drawer_data)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    try:
        data = request.get_json(silent=True) or request.form

        vendor_id = int(data.get('vendor_id'))
        location_id = int(data.get('location_id'))
        raw_order_date = data.get('order_date')
        order_date = datetime.now().date()
        if raw_order_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    order_date = datetime.strptime(str(raw_order_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        raw_expected_date = data.get('expected_date')
        expected_date = None
        if raw_expected_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    expected_date = datetime.strptime(str(raw_expected_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        carrier = (data.get('carrier') or '').strip()
        vendor_invoice_no = (data.get('vendor_invoice_no') or '').strip()
        notes = (data.get('notes') or '').strip()
        contact = (data.get('contact') or '').strip()
        phone = (data.get('phone') or '').strip()
        vendor_address = (data.get('vendor_address') or '').strip()
        non_vendor_costs = max(0.0, float(data.get('non_vendor_costs') or 0))
        currency_code = (data.get('currency_code') or 'USD').strip()
        shipping_fee = max(0.0, float(data.get('shipping_fee') or 0))
        discount_amount = max(0.0, float(data.get('discount_amount') or 0))

        # Flexible line parsing supporting lines_json, JSON payload, or form arrays
        lines_json_raw = data.get('lines_json')
        if lines_json_raw:
            try:
                import json
                raw_lines = json.loads(lines_json_raw)
            except Exception:
                raw_lines = []
        elif isinstance(data, dict) and 'lines' in data:
            raw_lines = data.get('lines', [])
        else:
            raw_lines = None

        if raw_lines is not None:
            prod_ids = [l.get('product_id') for l in raw_lines]
            quantities = [l.get('quantity') for l in raw_lines]
            unit_costs = [l.get('unit_cost') if l.get('unit_cost') is not None else (l.get('unit_price') if l.get('unit_price') is not None else l.get('cost', 0)) for l in raw_lines]
            discounts = [l.get('discount_percent', 0) for l in raw_lines]
            descriptions = [l.get('description', '') for l in raw_lines]
            vendor_codes = [l.get('vendor_product_code', '') for l in raw_lines]
            uoms = [l.get('uom', 'pcs.') for l in raw_lines]
        else:
            prod_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            unit_costs = request.form.getlist('unit_cost[]') or request.form.getlist('unit_price[]') or request.form.getlist('cost[]')
            discounts = request.form.getlist('discount_percent[]')
            descriptions = request.form.getlist('description[]')
            vendor_codes = request.form.getlist('vendor_product_code[]')
            uoms = request.form.getlist('uom[]')

        if not prod_ids:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Please add at least one line item.'}), 400
            flash("Please add at least one line item.", "error")
            return redirect(url_for('purchase_orders.create_purchase'))

        order_number = get_next_order_number('PO')

        subtotal = 0.0
        lines_data = []

        for idx in range(len(prod_ids)):
            if not prod_ids[idx]:
                continue
            pid = int(prod_ids[idx])
            qty = max(0.0001, float(quantities[idx] or 1))
            cost = max(0.0, float(unit_costs[idx] or 0))
            disc_pct = max(0.0, min(100.0, float(discounts[idx] if idx < len(discounts) and discounts[idx] else 0)))
            desc = descriptions[idx] if idx < len(descriptions) else ''
            vcode = vendor_codes[idx] if idx < len(vendor_codes) else ''
            uom = (uoms[idx] if idx < len(uoms) and uoms[idx] else 'pcs.').strip()
            
            line_sub = qty * cost * (1.0 - (disc_pct / 100.0))
            subtotal += line_sub
            lines_data.append((idx + 1, pid, desc, vcode, qty, cost, disc_pct, line_sub, uom))

        total_amount = max(0.0, subtotal + shipping_fee - discount_amount)
        balance_due = total_amount

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO purchase_orders (
                    order_number, vendor_id, location_id, order_date, expected_date,
                    carrier, vendor_invoice_no, contact, phone, vendor_address, non_vendor_costs, currency_code,
                    status, payment_status, subtotal, shipping_fee, discount_amount, total_amount, paid_amount, balance_due, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ISSUED', 'UNPAID', %s, %s, %s, %s, 0, %s, %s)
                RETURNING id;
            """, (order_number, vendor_id, location_id, order_date, expected_date, 
                  carrier, vendor_invoice_no, contact, phone, vendor_address, non_vendor_costs, currency_code,
                  subtotal, shipping_fee, discount_amount, total_amount, balance_due, notes))
            po_id = cur.fetchone()['id']

            for line in lines_data:
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, vendor_product_code, quantity, unit_cost, discount_percent, subtotal, received_qty, uom
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s);
                """, (po_id, line[0], line[1], line[2], line[3], line[4], line[5], line[6], line[7], line[8]))

            # Update vendor open balance
            cur.execute("""
                UPDATE vendors 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (balance_due, vendor_id))

        if is_ajax:
            return jsonify({
                'success': True,
                'po_id': po_id,
                'order_number': order_number,
                'redirect_url': url_for('purchase_orders.detail_purchase', id=po_id)
            })

        flash(f"Purchase Order {order_number} created successfully!", "success")
        return redirect(url_for('purchase_orders.detail_purchase', id=po_id))

    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error creating PO: {e}", "error")
        return redirect(url_for('purchase_orders.create_purchase'))

@purchase_orders_bp.route('/purchases/<int:id>')
def detail_purchase(id):
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            COALESCE(po.contact, v.contact_name, '') as contact,
            COALESCE(po.phone, v.phone, '') as phone,
            COALESCE(po.vendor_address, v.address1, '') as vendor_address,
            v.balance as vendor_balance,
            v.payment_terms as vendor_payment_terms,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE po.id = %s
    """, (id,))

    if not order:
        flash("Purchase order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    date_filter = request.args.get('date_filter', 'All')
    status_filter = request.args.get('status_filter', 'All')
    vendor_search = request.args.get('vendor_search', '')
    order_search = request.args.get('order_search', '')

    drawer_data = _get_po_drawer_data(date_filter, status_filter, vendor_search, order_search)

    lines = query_all("""
        SELECT 
            pol.*,
            COALESCE(pol.uom, p.purchasing_uom, p.uom, 'pcs.') as line_uom,
            p.name as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            p.image_url as product_image,
            COALESCE(p.uom, 'pcs.') as product_uom,
            COALESCE(p.uom, 'pcs.') as base_uom,
            COALESCE(p.purchasing_uom, p.uom, 'pcs.') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, p.master_pack_qty, p.inner_pack_qty, 1.0) as purchasing_ratio,
            COALESCE(p.sales_uom, p.uom, 'pcs.') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_ratio,
            p.average_cost as product_avg_cost,
            p.last_purchase_cost as product_last_cost,
            COALESCE(inv.qty, 0) as on_hand_stock,
            COALESCE(inv.qty, 0) as stock_on_hand,
            COALESCE(inv.reserved_qty, 0) as stock_reserved,
            (COALESCE(inv.qty, 0) - COALESCE(inv.reserved_qty, 0)) as stock_avail,
            COALESCE(po_ord.on_order_qty, 0) as stock_on_order
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as qty, SUM(COALESCE(reserved_quantity, 0)) as reserved_qty
            FROM inventory 
            GROUP BY product_id
        ) inv ON pol.product_id = inv.product_id
        LEFT JOIN (
            SELECT pol2.product_id, SUM(pol2.quantity - pol2.received_qty) as on_order_qty
            FROM purchase_order_lines pol2
            JOIN purchase_orders po2 ON pol2.purchase_order_id = po2.id
            WHERE po2.status IN ('ISSUED', 'PARTIAL_RECEIVED')
            GROUP BY pol2.product_id
        ) po_ord ON pol.product_id = po_ord.product_id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    payments = query_all("""
        SELECT * FROM order_payments 
        WHERE order_type = 'PO' AND order_id = %s 
        ORDER BY payment_date DESC, id DESC
    """, (id,))

    inventory_logs = query_all("""
        SELECT il.*, p.name as product_name, p.sku as product_sku
        FROM inventory_logs il
        JOIN products p ON il.product_id = p.id
        WHERE il.reference_type = 'PO' AND il.reference_id = %s
        ORDER BY il.id DESC
    """, (order['order_number'],))

    company = query_one("SELECT * FROM companies LIMIT 1")

    # Receiving summary
    total_qty_ordered = sum(float(l['quantity'] or 0) for l in lines)
    total_qty_received = sum(float(l['received_qty'] or 0) for l in lines)
    receiving_percent = int((total_qty_received / total_qty_ordered * 100) if total_qty_ordered > 0 else 0)

    # Attachments
    attachments = query_all("""
        SELECT * FROM purchase_order_attachments
        WHERE purchase_order_id = %s
        ORDER BY id DESC
    """, (id,))

    # Check if this PO is already linked to an expense
    linked_expense = query_one("""
        SELECT id, expense_date, total_price, category, paid_by, month_key 
        FROM expenses 
        WHERE notes ILIKE %s OR item ILIKE %s
        ORDER BY id DESC LIMIT 1
    """, (f"%{order['order_number']}%", f"%{order['order_number']}%"))

    # Expense categories and payers for the Add to Expenses modal
    exp_cats_rows = query_all("SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
    expense_categories = [r['category'] for r in exp_cats_rows] if exp_cats_rows else []
    if 'Purchases' not in expense_categories:
        expense_categories.insert(0, 'Purchases')

    exp_payers_rows = query_all("SELECT DISTINCT paid_by FROM expenses WHERE paid_by IS NOT NULL AND paid_by != '' ORDER BY paid_by ASC")
    expense_payers = [r['paid_by'] for r in exp_payers_rows] if exp_payers_rows else []
    if 'ABA Bank' not in expense_payers:
        expense_payers.insert(0, 'ABA Bank')

    return render_template('purchases/detail.html', 
                           is_new=False,
                           order=order, 
                           lines=lines, 
                           payments=payments,
                           inventory_logs=inventory_logs,
                           attachments=attachments,
                           attachment_count=len(attachments),
                           linked_expense=linked_expense,
                           expense_categories=expense_categories,
                           expense_payers=expense_payers,
                           company=company,
                           total_qty_ordered=total_qty_ordered,
                           total_qty_received=total_qty_received,
                           receiving_percent=receiving_percent,
                           date_filter=date_filter,
                           status_filter=status_filter,
                           vendor_search=vendor_search,
                           order_search=order_search,
                           preview_po_number=order['order_number'],
                           **drawer_data)

@purchase_orders_bp.route('/purchases/<int:id>/save', methods=['POST'])
@purchase_orders_bp.route('/purchases/<int:id>/update', methods=['POST'])
def update_purchase(id):
    if id == 0:
        return create_purchase()

    order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        return jsonify({'success': False, 'message': 'Purchase order not found.'}), 404

    if order['status'] == 'CANCELLED':
        return jsonify({'success': False, 'message': 'Cannot update a cancelled purchase order.'}), 400

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    try:
        data = request.get_json(silent=True) or request.form

        notes = (data.get('notes') or '').strip()
        carrier = (data.get('carrier') or '').strip()
        vendor_invoice_no = (data.get('vendor_invoice_no') or '').strip()
        contact = (data.get('contact') or '').strip()
        phone = (data.get('phone') or '').strip()
        vendor_address = (data.get('vendor_address') or '').strip()
        non_vendor_costs = max(0.0, float(data.get('non_vendor_costs') or 0))
        currency_code = (data.get('currency_code') or 'USD').strip()
        raw_expected_date = data.get('expected_date')
        expected_date = None
        if raw_expected_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    expected_date = datetime.strptime(str(raw_expected_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        # If PO is already RECEIVED, only non-inventory fields can be updated
        if order['status'] in ('RECEIVED', 'PAID'):
            execute("""
                UPDATE purchase_orders 
                SET expected_date = %s, carrier = %s, vendor_invoice_no = %s, notes = %s,
                    contact = %s, phone = %s, vendor_address = %s, non_vendor_costs = %s, currency_code = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (expected_date, carrier, vendor_invoice_no, notes, contact, phone, vendor_address, non_vendor_costs, currency_code, id))

            linked_exp = query_one("""
                SELECT id, month_key, total_price, branch_id 
                FROM expenses 
                WHERE notes ILIKE %s OR item ILIKE %s
                ORDER BY id DESC LIMIT 1
            """, (f"%{order['order_number']}%", f"%{order['order_number']}%"))
            cur_po_total = float(order.get('total_amount') or 0)
            if linked_exp and float(linked_exp['total_price'] or 0) != cur_po_total:
                execute("""
                    UPDATE expenses 
                    SET unit_price = %s, total_price = %s, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (cur_po_total, cur_po_total, linked_exp['id']))
                try:
                    from routes.expenses import _get_or_create_monthly_summary
                    _get_or_create_monthly_summary(linked_exp['month_key'], branch_id=str(linked_exp.get('branch_id') or 'main'))
                except Exception:
                    pass

            if is_ajax:
                return jsonify({
                    'success': True,
                    'message': 'Purchase order updated successfully!',
                    'total_amount': cur_po_total,
                    'linked_expense': {
                        'id': linked_exp['id'],
                        'total_price': cur_po_total,
                        'month_key': linked_exp['month_key']
                    } if linked_exp else None
                })
            flash("Purchase order notes and details updated.", "success")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        # PO is ISSUED or DRAFT: full edit of vendor, location, items, shipping, discount
        vendor_id = int(data.get('vendor_id', order['vendor_id']))
        location_id = int(data.get('location_id', order['location_id']))
        raw_order_date = data.get('order_date')
        order_date = order['order_date']
        if raw_order_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    order_date = datetime.strptime(str(raw_order_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        shipping_fee = max(0.0, float(data.get('shipping_fee') or 0))
        discount_amount = max(0.0, float(data.get('discount_amount') or 0))

        lines_json_raw = data.get('lines_json')
        if lines_json_raw:
            try:
                import json
                raw_lines = json.loads(lines_json_raw)
            except Exception:
                raw_lines = []
        elif isinstance(data, dict) and 'lines' in data:
            raw_lines = data.get('lines', [])
        else:
            raw_lines = None

        if raw_lines is not None:
            prod_ids = [l.get('product_id') for l in raw_lines]
            quantities = [l.get('quantity') for l in raw_lines]
            unit_costs = [l.get('unit_cost') if l.get('unit_cost') is not None else (l.get('unit_price') if l.get('unit_price') is not None else l.get('cost', 0)) for l in raw_lines]
            discounts = [l.get('discount_percent', 0) for l in raw_lines]
            descriptions = [l.get('description', '') for l in raw_lines]
            vendor_codes = [l.get('vendor_product_code', '') for l in raw_lines]
            uoms = [l.get('uom', 'pcs.') for l in raw_lines]
        else:
            prod_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            unit_costs = request.form.getlist('unit_cost[]') or request.form.getlist('unit_price[]') or request.form.getlist('cost[]')
            discounts = request.form.getlist('discount_percent[]')
            descriptions = request.form.getlist('description[]')
            vendor_codes = request.form.getlist('vendor_product_code[]')
            uoms = request.form.getlist('uom[]')

        if not prod_ids:
            if is_ajax:
                return jsonify({'success': False, 'message': 'PO must have at least one line item.'}), 400
            flash("PO must have at least one line item.", "error")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        subtotal = 0.0
        lines_data = []
        for idx in range(len(prod_ids)):
            if not prod_ids[idx]:
                continue
            pid = int(prod_ids[idx])
            qty = max(0.0001, float(quantities[idx] or 1))
            cost = max(0.0, float(unit_costs[idx] or 0))
            disc_pct = max(0.0, min(100.0, float(discounts[idx] if idx < len(discounts) and discounts[idx] else 0)))
            desc = descriptions[idx] if idx < len(descriptions) else ''
            vcode = vendor_codes[idx] if idx < len(vendor_codes) else ''
            uom = (uoms[idx] if idx < len(uoms) and uoms[idx] else 'pcs.').strip()
            
            line_sub = qty * cost * (1.0 - (disc_pct / 100.0))
            subtotal += line_sub
            lines_data.append((idx + 1, pid, desc, vcode, qty, cost, disc_pct, line_sub, uom))

        total_amount = max(0.0, subtotal + shipping_fee - discount_amount)
        paid_amount = float(order['paid_amount'] or 0)
        new_balance_due = max(0.0, total_amount - paid_amount)
        new_pay_status = 'PAID' if new_balance_due <= 0 and paid_amount > 0 else ('PARTIAL' if paid_amount > 0 else 'UNPAID')

        with get_db_cursor(commit=True) as cur:
            # Revert old vendor balance difference
            old_balance_due = float(order['balance_due'] or 0)
            old_vendor_id = order['vendor_id']
            if old_vendor_id == vendor_id:
                diff = new_balance_due - old_balance_due
                cur.execute("UPDATE vendors SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (diff, vendor_id))
            else:
                cur.execute("UPDATE vendors SET balance = GREATEST(0, balance - %s), updated_at = CURRENT_TIMESTAMP WHERE id = %s", (old_balance_due, old_vendor_id))
                cur.execute("UPDATE vendors SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_balance_due, vendor_id))

            # Update PO
            cur.execute("""
                UPDATE purchase_orders 
                SET vendor_id = %s, location_id = %s, order_date = %s, expected_date = %s,
                    carrier = %s, vendor_invoice_no = %s, contact = %s, phone = %s, vendor_address = %s,
                    non_vendor_costs = %s, currency_code = %s,
                    subtotal = %s, shipping_fee = %s,
                    discount_amount = %s, total_amount = %s, balance_due = %s, payment_status = %s,
                    notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (vendor_id, location_id, order_date, expected_date, carrier, vendor_invoice_no,
                  contact, phone, vendor_address, non_vendor_costs, currency_code,
                  subtotal, shipping_fee, discount_amount, total_amount, new_balance_due, new_pay_status, notes, id))

            # Preserve received_qty if lines already partially received
            cur.execute("SELECT product_id, received_qty FROM purchase_order_lines WHERE purchase_order_id = %s", (id,))
            old_lines_rcv = {r['product_id']: float(r['received_qty'] or 0) for r in cur.fetchall()}

            cur.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (id,))
            for line in lines_data:
                rcv_qty = old_lines_rcv.get(line[1], 0.0)
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, vendor_product_code, quantity, unit_cost, discount_percent, subtotal, received_qty, uom
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (id, line[0], line[1], line[2], line[3], line[4], line[5], line[6], line[7], rcv_qty, line[8]))

            # If this PO is linked to an expense in expenses table, sync its amount to the updated total_amount
            cur.execute("""
                SELECT id, month_key, total_price, branch_id 
                FROM expenses 
                WHERE notes ILIKE %s OR item ILIKE %s
                ORDER BY id DESC LIMIT 1
            """, (f"%{order['order_number']}%", f"%{order['order_number']}%"))
            linked_exp = cur.fetchone()
            if linked_exp and float(linked_exp['total_price'] or 0) != total_amount:
                cur.execute("""
                    UPDATE expenses 
                    SET unit_price = %s, total_price = %s, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (total_amount, total_amount, linked_exp['id']))
                try:
                    from routes.expenses import _get_or_create_monthly_summary
                    _get_or_create_monthly_summary(linked_exp['month_key'], branch_id=str(linked_exp.get('branch_id') or 'main'))
                except Exception:
                    pass

        if is_ajax:
            return jsonify({
                'success': True,
                'message': 'Purchase order saved successfully!',
                'total_amount': total_amount,
                'linked_expense': {
                    'id': linked_exp['id'],
                    'total_price': total_amount,
                    'month_key': linked_exp['month_key']
                } if linked_exp else None
            })
        flash("Purchase order updated successfully!", "success")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error updating PO: {e}", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error updating PO: {e}", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/copy', methods=['GET', 'POST'])
def copy_purchase(id):
    try:
        order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
        if not order:
            flash("Original purchase order not found.", "error")
            return redirect(url_for('purchase_orders.list_purchases'))

        lines = query_all("SELECT * FROM purchase_order_lines WHERE purchase_order_id = %s ORDER BY line_num ASC", (id,))
        
        new_order_number = get_next_order_number('PO')
        
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO purchase_orders (
                    order_number, vendor_id, location_id, order_date, expected_date,
                    carrier, vendor_invoice_no, status, payment_status,
                    subtotal, shipping_fee, discount_amount, total_amount, paid_amount, balance_due, notes
                ) VALUES (%s, %s, %s, CURRENT_DATE, NULL, %s, %s, 'ISSUED', 'UNPAID', %s, %s, %s, %s, 0, %s, %s)
                RETURNING id;
            """, (new_order_number, order['vendor_id'], order['location_id'], order['carrier'], '',
                  order['subtotal'], order['shipping_fee'], order.get('discount_amount') or 0, order['total_amount'], order['total_amount'],
                  f"Duplicate of {order['order_number']}. " + (order['notes'] or '')))
            new_po_id = cur.fetchone()['id']

            for idx, line in enumerate(lines):
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, quantity, unit_cost, discount_percent, subtotal, received_qty, uom
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s);
                """, (new_po_id, line.get('line_num') or (idx + 1), line['product_id'], line.get('description') or '', line['quantity'], line['unit_cost'], line.get('discount_percent') or 0, line['subtotal'], line.get('uom') or 'pcs.'))

            if order['vendor_id']:
                cur.execute("UPDATE vendors SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (order['total_amount'], order['vendor_id']))

        flash(f"New Purchase Order {new_order_number} duplicated from {order['order_number']}!", "success")
        return redirect(url_for('purchase_orders.detail_purchase', id=new_po_id))
    except Exception as e:
        flash(f"Error copying purchase order: {e}", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/receive', methods=['POST'])
def receive_goods(id):
    order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Order not found.'}), 404
        flash("Order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    if order['status'] in ('RECEIVED', 'PAID'):
        msg = "Purchase order has already been fully received. Duplicate inventory increment was prevented."
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "warning")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    if order['status'] == 'CANCELLED':
        msg = "Cannot receive goods for a cancelled purchase order."
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    data = request.get_json(silent=True) or request.form
    receive_all = (str(data.get('receive_all', '')).lower() in ('1', 'true', 'yes'))
    line_receives = {}
    
    if request.is_json and 'items' in data:
        for it in data['items']:
            lid = int(it.get('line_id'))
            rq = float(it.get('received_qty') or 0)
            if rq > 0:
                line_receives[lid] = rq
    elif not receive_all:
        for key in request.form:
            if key.startswith('receive_qty_'):
                try:
                    lid = int(key.replace('receive_qty_', ''))
                    rq = float(request.form.get(key) or 0)
                    if rq > 0:
                        line_receives[lid] = rq
                except ValueError:
                    pass

    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id, product_id, quantity, unit_cost, received_qty, uom FROM purchase_order_lines WHERE purchase_order_id = %s FOR UPDATE", (id,))
        lines = cur.fetchall()

        any_received = False
        all_lines_complete = True
        total_items_received_now = 0

        for l in lines:
            lid = l['id']
            pid = l['product_id']
            ordered_qty = float(l['quantity'])
            already_rcv = float(l['received_qty'] or 0)
            cost = float(l['unit_cost'])
            line_uom = (l.get('uom') or 'pcs.').strip()
            remaining = max(0.0, ordered_qty - already_rcv)

            if receive_all:
                qty_to_receive = remaining
            elif lid in line_receives:
                qty_to_receive = max(0.0, float(line_receives[lid]))
            elif not line_receives:
                qty_to_receive = remaining
            else:
                qty_to_receive = 0.0

            if qty_to_receive > 0:
                any_received = True
                total_items_received_now += qty_to_receive
                new_rcv_total = already_rcv + qty_to_receive

                # Check product for packaging UOM ratio
                cur.execute("""
                    SELECT uom, purchasing_uom, purchasing_uom_ratio_std, sales_uom, sales_uom_ratio_std,
                           standard_cost, average_cost, last_purchase_cost, costing_sheet_cost, name
                    FROM products WHERE id = %s FOR UPDATE
                """, (pid,))
                cur_p = cur.fetchone()

                ratio = 1.0
                if cur_p:
                    if line_uom and cur_p.get('purchasing_uom') and _match_uom(line_uom, cur_p.get('purchasing_uom')):
                        ratio = float(cur_p.get('purchasing_uom_ratio_std') or 1.0)
                    elif line_uom and cur_p.get('sales_uom') and _match_uom(line_uom, cur_p.get('sales_uom')):
                        ratio = float(cur_p.get('sales_uom_ratio_std') or 1.0)
                    elif _match_uom(line_uom, 'case'):
                        ratio = float(cur_p.get('purchasing_uom_ratio_std') or cur_p.get('sales_uom_ratio_std') or 1.0)

                base_qty_to_receive = qty_to_receive * ratio
                base_unit_cost = (cost / ratio) if ratio > 0 else cost

                # Check if kit product (has BOM components)
                cur.execute("""
                    SELECT pb.component_product_id, pb.quantity, pb.cost,
                           cp.name as comp_name, cp.sku as comp_sku, cp.uom as comp_uom,
                           cp.average_cost as comp_avg_cost, cp.standard_cost as comp_std_cost
                    FROM product_boms pb
                    JOIN products cp ON pb.component_product_id = cp.id
                    WHERE pb.product_id = %s
                    ORDER BY pb.id ASC
                """, (pid,))
                kit_comps = cur.fetchall()

                if kit_comps:
                    total_bom_weight = sum(float(c.get('cost') or c.get('comp_std_cost') or 0.0) * float(c.get('quantity') or 1.0) for c in kit_comps)
                    for c in kit_comps:
                        c_pid = c['component_product_id']
                        c_ratio = float(c.get('quantity') or 1.0)
                        comp_qty = base_qty_to_receive * c_ratio

                        c_bom_cost = float(c.get('cost') or c.get('comp_std_cost') or 0.0)
                        if total_bom_weight > 0 and c_bom_cost > 0:
                            comp_unit_cost = (c_bom_cost / total_bom_weight) * base_unit_cost / c_ratio
                        else:
                            comp_unit_cost = (base_unit_cost / len(kit_comps)) / c_ratio

                        cur.execute("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (c_pid, order['location_id']))
                        cur_c_inv = cur.fetchone()
                        old_c_qty = float(cur_c_inv['qty']) if cur_c_inv else 0.0

                        # Increment stock for component in warehouse
                        cur.execute("""
                            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                            VALUES (%s, %s, '', %s)
                            ON CONFLICT (product_id, location_id, sublocation)
                            DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                        """, (c_pid, order['location_id'], comp_qty))

                        # Recalculate moving average cost for component
                        cur_c_avg = float(c['comp_avg_cost'] or comp_unit_cost)
                        new_c_total_qty = old_c_qty + comp_qty
                        if new_c_total_qty > 0:
                            new_c_avg = ((old_c_qty * cur_c_avg) + (comp_qty * comp_unit_cost)) / new_c_total_qty
                        else:
                            new_c_avg = comp_unit_cost

                        cur.execute("""
                            UPDATE products 
                            SET last_purchase_cost = %s,
                                average_cost = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s;
                        """, (comp_unit_cost, new_c_avg, c_pid))

                        # Audit ledger for component
                        comp_name = c.get('comp_name') or f"Product #{c_pid}"
                        parent_name = cur_p.get('name') if cur_p else f"Kit #{pid}"
                        comp_uom = c.get('comp_uom') or 'pcs.'
                        comp_log_reason = f"Purchase Order Received (Kit Component for {parent_name}: {comp_name} x{comp_qty:g} {comp_uom})"

                        cur.execute("""
                            INSERT INTO inventory_logs (
                                product_id, movement_type, reference_type, reference_id,
                                to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                            ) VALUES (%s, 'PO_RECEIVE', 'PO', %s, %s, %s, %s, %s, %s, %s);
                        """, (c_pid, order['order_number'], order['location_id'], comp_qty, old_c_qty, old_c_qty + comp_qty, comp_unit_cost, comp_log_reason))

                    # Update parent kit's last_purchase_cost for reference (no inventory added to parent)
                    cur.execute("""
                        UPDATE products 
                        SET last_purchase_cost = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (base_unit_cost, pid))
                else:
                    cur.execute("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (pid, order['location_id']))
                    cur_inv = cur.fetchone()
                    old_qty = float(cur_inv['qty']) if cur_inv else 0.0

                    # Increment stock in warehouse (standard base units)
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                        VALUES (%s, %s, '', %s)
                        ON CONFLICT (product_id, location_id, sublocation)
                        DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                    """, (pid, order['location_id'], base_qty_to_receive))

                    # Recalculate moving average cost (cost per base unit = cost / ratio)
                    cur_avg = float(cur_p['average_cost'] or base_unit_cost) if cur_p else base_unit_cost
                    new_total_qty = old_qty + base_qty_to_receive
                    if new_total_qty > 0:
                        new_avg = ((old_qty * cur_avg) + (base_qty_to_receive * base_unit_cost)) / new_total_qty
                    else:
                        new_avg = base_unit_cost

                    cur.execute("""
                        UPDATE products 
                        SET last_purchase_cost = %s,
                            average_cost = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                    """, (base_unit_cost, new_avg, pid))

                    # Audit ledger
                    log_reason = f"Purchase Order Received ({qty_to_receive} {line_uom}" + (f" = {base_qty_to_receive} {cur_p.get('uom','pcs.')})" if ratio > 1 else ")")
                    cur.execute("""
                        INSERT INTO inventory_logs (
                            product_id, movement_type, reference_type, reference_id,
                            to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                        ) VALUES (%s, 'PO_RECEIVE', 'PO', %s, %s, %s, %s, %s, %s, %s);
                    """, (pid, order['order_number'], order['location_id'], base_qty_to_receive, old_qty, old_qty + base_qty_to_receive, base_unit_cost, log_reason))

                # Update line received_qty
                cur.execute("UPDATE purchase_order_lines SET received_qty = %s WHERE id = %s", (new_rcv_total, lid))

                if new_rcv_total < ordered_qty:
                    all_lines_complete = False
            else:
                if already_rcv < ordered_qty:
                    all_lines_complete = False

        if not any_received:
            # If all lines are already complete or receive_all was clicked on an unfulfilled PO, mark as RECEIVED (Fulfilled)!
            if all_lines_complete or receive_all:
                new_status = 'RECEIVED'
                cur.execute("""
                    UPDATE purchase_orders 
                    SET status = %s, received_date = COALESCE(received_date, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (new_status, id))
                all_lines_complete = True
            else:
                msg = "No remaining quantities to receive for this order."
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': msg}), 400
                flash(msg, "warning")
                return redirect(url_for('purchase_orders.detail_purchase', id=id))
        else:
            new_status = 'RECEIVED' if all_lines_complete else 'PARTIAL_RECEIVED'
            cur.execute("""
                UPDATE purchase_orders 
                SET status = %s, received_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (new_status, id))

    badge = 'Fulfilled' if new_status == 'RECEIVED' else 'Partial'
    success_msg = f"Purchase Order {order['order_number']} goods successfully received into warehouse! Inventory updated." if all_lines_complete else f"Partial shipment for Purchase Order {order['order_number']} received! Inventory updated."

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': success_msg,
            'new_status': new_status,
            'status_badge': badge,
            'all_lines_complete': all_lines_complete
        })

    flash(success_msg, "success")
    return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/unfulfill', methods=['POST'])
def unfulfill_purchase(id):
    order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Order not found.'}), 404
        flash("Order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id, product_id, quantity, unit_cost, received_qty, uom FROM purchase_order_lines WHERE purchase_order_id = %s FOR UPDATE", (id,))
        lines = cur.fetchall()

        for l in lines:
            rcv = float(l['received_qty'] or 0)
            if rcv > 0:
                pid = l['product_id']
                line_uom = (l.get('uom') or 'pcs.').strip()
                cur.execute("SELECT name, uom, purchasing_uom, purchasing_uom_ratio_std, sales_uom, sales_uom_ratio_std FROM products WHERE id = %s", (pid,))
                cur_p = cur.fetchone()
                ratio = 1.0
                if cur_p:
                    if line_uom and cur_p.get('purchasing_uom') and _match_uom(line_uom, cur_p.get('purchasing_uom')):
                        ratio = float(cur_p.get('purchasing_uom_ratio_std') or 1.0)
                    elif line_uom and cur_p.get('sales_uom') and _match_uom(line_uom, cur_p.get('sales_uom')):
                        ratio = float(cur_p.get('sales_uom_ratio_std') or 1.0)
                    elif _match_uom(line_uom, 'case'):
                        ratio = float(cur_p.get('purchasing_uom_ratio_std') or cur_p.get('sales_uom_ratio_std') or 1.0)

                base_qty = rcv * ratio

                # Check if kit product (has BOM components)
                cur.execute("""
                    SELECT pb.component_product_id, pb.quantity, pb.cost,
                           cp.name as comp_name, cp.sku as comp_sku, cp.uom as comp_uom
                    FROM product_boms pb
                    JOIN products cp ON pb.component_product_id = cp.id
                    WHERE pb.product_id = %s
                    ORDER BY pb.id ASC
                """, (pid,))
                kit_comps = cur.fetchall()

                if kit_comps:
                    for c in kit_comps:
                        c_pid = c['component_product_id']
                        c_ratio = float(c.get('quantity') or 1.0)
                        comp_qty = base_qty * c_ratio
                        cur.execute("UPDATE inventory SET quantity = GREATEST(0, quantity - %s), updated_at = CURRENT_TIMESTAMP WHERE product_id = %s AND location_id = %s", (comp_qty, c_pid, order['location_id']))
                        comp_name = c.get('comp_name') or f"Product #{c_pid}"
                        parent_name = cur_p.get('name') if cur_p else f"Kit #{pid}"
                        cur.execute("""
                            INSERT INTO inventory_logs (
                                product_id, movement_type, reference_type, reference_id,
                                from_location_id, quantity, unit_cost, reason
                            ) VALUES (%s, 'PO_UNRECEIVE', 'PO', %s, %s, %s, %s, %s);
                        """, (c_pid, order['order_number'], order['location_id'], comp_qty, c.get('cost') or 0.0, f"PO Receiving Reversal (Kit Component for {parent_name}: {comp_name} x{comp_qty:g})"))
                else:
                    cur.execute("UPDATE inventory SET quantity = GREATEST(0, quantity - %s), updated_at = CURRENT_TIMESTAMP WHERE product_id = %s AND location_id = %s", (base_qty, pid, order['location_id']))
                    cur.execute("""
                        INSERT INTO inventory_logs (
                            product_id, movement_type, reference_type, reference_id,
                            from_location_id, quantity, unit_cost, reason
                        ) VALUES (%s, 'PO_UNRECEIVE', 'PO', %s, %s, %s, %s, 'PO Receiving Reversal (Unfulfilled)');
                    """, (pid, order['order_number'], order['location_id'], base_qty, l['unit_cost']))

                cur.execute("UPDATE purchase_order_lines SET received_qty = 0 WHERE id = %s", (l['id'],))

        cur.execute("UPDATE purchase_orders SET status = 'ISSUED', received_date = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': f"Purchase Order {order['order_number']} unfulfilled. Received stock reversed from inventory.",
            'new_status': 'ISSUED',
            'status_badge': 'Unfulfilled'
        })

    flash(f"Purchase Order {order['order_number']} unfulfilled. Received stock reversed from inventory.", "info")
    return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/attachments', methods=['GET'])
def get_po_attachments(id):
    order = query_one("SELECT id FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404
    atts = query_all("""
        SELECT id, purchase_order_id, file_name, file_path, file_size, file_type, caption, uploaded_by, created_at
        FROM purchase_order_attachments
        WHERE purchase_order_id = %s
        ORDER BY id DESC
    """, (id,))
    res = []
    for a in atts:
        d = dict(a)
        if d.get('created_at'):
            d['created_at_fmt'] = d['created_at'].strftime('%Y-%m-%d %H:%M')
        else:
            d['created_at_fmt'] = ''
        res.append(d)
    return jsonify({'success': True, 'attachments': res, 'count': len(res)})

@purchase_orders_bp.route('/purchases/<int:id>/attachments/upload', methods=['POST'])
def upload_po_attachments(id):
    order = query_one("SELECT id, order_number FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    files = request.files.getlist('files') or request.files.getlist('attachment_files')
    if not files and 'file' in request.files:
        files = [request.files['file']]
    if not files and 'attachment_file' in request.files:
        files = [request.files['attachment_file']]

    if not files:
        return jsonify({'success': False, 'message': 'No files provided for upload.'}), 400

    upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'purchase_attachments')
    os.makedirs(upload_dir, exist_ok=True)

    saved_items = []
    current_username = 'Admin'
    try:
        if session.get('username'):
            current_username = session.get('username')
    except Exception:
        pass

    with get_db_cursor(commit=True) as cur:
        for f in files:
            if not f or not f.filename:
                continue
            orig_name = f.filename
            clean_name = secure_filename(orig_name) or 'po_attachment'
            ext = os.path.splitext(orig_name)[1].lower()
            unique_name = f"po_{id}_{int(time.time())}_{clean_name}"
            save_path = os.path.join(upload_dir, unique_name)
            f.save(save_path)

            file_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
            file_url = f"/static/uploads/purchase_attachments/{unique_name}"
            file_type = f.content_type or ('image' if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif') else 'document')

            cur.execute("""
                INSERT INTO purchase_order_attachments (
                    purchase_order_id, file_name, file_path, file_size, file_type, caption, uploaded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (id, orig_name, file_url, file_size, file_type, request.form.get('caption', ''), current_username))
            new_id = cur.fetchone()['id']
            saved_items.append({
                'id': new_id,
                'file_name': orig_name,
                'file_path': file_url,
                'file_size': file_size,
                'file_type': file_type
            })

    total_count = query_one("SELECT COUNT(*) as cnt FROM purchase_order_attachments WHERE purchase_order_id = %s", (id,))['cnt']
    return jsonify({
        'success': True,
        'message': f"Uploaded {len(saved_items)} file(s) successfully!",
        'uploaded': saved_items,
        'total_count': total_count
    })

@purchase_orders_bp.route('/purchases/<int:id>/attachments/<int:att_id>/delete', methods=['POST'])
def delete_po_attachment(id, att_id):
    att = query_one("SELECT * FROM purchase_order_attachments WHERE id = %s AND purchase_order_id = %s", (att_id, id))
    if not att:
        return jsonify({'success': False, 'message': 'Attachment not found'}), 404

    try:
        full_path = os.path.join(os.path.dirname(__file__), '..', att['file_path'].lstrip('/'))
        if os.path.exists(full_path):
            os.remove(full_path)
    except Exception:
        pass

    execute("DELETE FROM purchase_order_attachments WHERE id = %s AND purchase_order_id = %s", (att_id, id))
    total_count = query_one("SELECT COUNT(*) as cnt FROM purchase_order_attachments WHERE purchase_order_id = %s", (id,))['cnt']
    return jsonify({'success': True, 'message': 'Attachment deleted.', 'total_count': total_count})

@purchase_orders_bp.route('/purchases/<int:id>/pay', methods=['POST'])
def record_payment(id):
    try:
        amount = float(request.form.get('amount', 0) or 0)
        if amount <= 0:
            flash("Payment amount must be greater than zero.", "error")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        method = (request.form.get('payment_method') or request.form.get('method') or 'Bank Transfer (ABA / Prasac)').strip()
        reference = (request.form.get('reference_no') or request.form.get('reference') or '').strip()
        notes = (request.form.get('payment_notes') or request.form.get('notes') or '').strip()
        payment_date = (request.form.get('payment_date') or '').strip() or None

        order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for('purchase_orders.list_purchases'))

        if order['status'] == 'CANCELLED':
            flash("Cannot record payment for a cancelled purchase order.", "error")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        new_paid = float(order['paid_amount'] or 0) + amount
        new_balance = max(0.0, float(order['total_amount'] or 0) - new_paid)
        new_pay_status = 'PAID' if new_balance <= 0 else 'PARTIAL'

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE purchase_orders 
                SET paid_amount = %s,
                    balance_due = %s,
                    payment_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (new_paid, new_balance, new_pay_status, id))

            cur.execute("""
                INSERT INTO order_payments (
                    order_type, order_id, amount, payment_method, reference, notes, payment_date, branch_id
                ) VALUES ('PO', %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s);
            """, (id, amount, method, reference, notes, payment_date, order.get('branch_id')))

            # Deduct from vendor balance
            if order['vendor_id']:
                cur.execute("""
                    UPDATE vendors 
                    SET balance = GREATEST(0, balance - %s), updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s;
                """, (amount, order['vendor_id']))

        flash(f"Payment of ${amount:.2f} ({method}) to vendor recorded! Balance remaining: ${new_balance:.2f}", "success")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    except Exception as e:
        flash(f"Error recording payment: {e}", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/add-to-expenses', methods=['POST'])
def add_po_to_expenses(id):
    order = query_one("""
        SELECT po.*, v.name as vendor_name 
        FROM purchase_orders po 
        LEFT JOIN vendors v ON po.vendor_id = v.id 
        WHERE po.id = %s
    """, (id,))
    if not order:
        return jsonify({'success': False, 'message': 'Purchase order not found.'}), 404

    try:
        data = request.get_json(silent=True) or request.form
        
        vendor_name = order.get('vendor_name') or 'Vendor'
        default_item = f"{order['order_number']} - {vendor_name}"
        item = (data.get('item') or default_item).strip()
        if not item:
            item = default_item

        raw_date = data.get('expense_date')
        exp_date = None
        if raw_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    exp_date = datetime.strptime(str(raw_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass
        if not exp_date:
            if order.get('order_date'):
                exp_date = order['order_date']
            else:
                exp_date = date.today()

        month_key = (data.get('month_key') or exp_date.strftime('%Y-%m')).strip()

        raw_amount = data.get('amount')
        if raw_amount is not None and str(raw_amount).strip() != '':
            total_price = max(0.0, float(raw_amount))
        else:
            total_price = float(order.get('total_amount') or 0.0)

        category = (data.get('category') or 'Purchases').strip()
        paid_by = (data.get('paid_by') or 'ABA Bank').strip()
        
        default_notes = f"Purchase Order: {order['order_number']} • Vendor: {vendor_name}"
        notes = (data.get('notes') or default_notes).strip()

        branch_id = order.get('branch_id')
        recorded_by = session.get('username') or 'Admin'

        # Check if an expense already exists for this PO
        existing_exp = query_one("""
            SELECT id, month_key, branch_id 
            FROM expenses 
            WHERE notes ILIKE %s OR item ILIKE %s
            ORDER BY id DESC LIMIT 1
        """, (f"%{order['order_number']}%", f"%{order['order_number']}%"))

        from routes.expenses import _get_or_create_monthly_summary

        if existing_exp:
            new_expense_id = existing_exp['id']
            execute("""
                UPDATE expenses 
                SET expense_date = %s, item = %s, category = %s, unit_price = %s, quantity = 1,
                    total_price = %s, paid_by = %s, payment_account = %s, notes = %s,
                    month_key = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (exp_date, item, category, total_price, total_price, paid_by, paid_by, notes, month_key, new_expense_id))
            try:
                if existing_exp.get('month_key') and existing_exp['month_key'] != month_key:
                    _get_or_create_monthly_summary(existing_exp['month_key'], branch_id=str(branch_id) if branch_id else 'main')
                _get_or_create_monthly_summary(month_key, branch_id=str(branch_id) if branch_id else 'main')
            except Exception:
                pass
            msg = f"Successfully updated {order['order_number']} (${total_price:,.2f}) in {month_key} Expenses Sheet!"
        else:
            new_expense_id = execute_returning_id("""
                INSERT INTO expenses (expense_date, item, category, unit_price, quantity, total_price, paid_by, payment_account, notes, month_key, branch_id, recorded_by)
                VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (exp_date, item, category, total_price, total_price, paid_by, paid_by, notes, month_key, branch_id, recorded_by))
            try:
                _get_or_create_monthly_summary(month_key, branch_id=str(branch_id) if branch_id else 'main')
            except Exception:
                pass
            msg = f"Successfully added {order['order_number']} (${total_price:,.2f}) to {month_key} Expenses Sheet!"

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
        if is_ajax:
            return jsonify({
                'success': True,
                'message': msg,
                'expense_id': new_expense_id,
                'month_key': month_key,
                'total_price': total_price
            })

        flash(msg, 'success')
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    except Exception as e:
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
        if is_ajax:
            return jsonify({'success': False, 'message': f"Error adding to expenses: {e}"}), 500
        flash(f"Error adding to expenses: {e}", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/print')
def print_po(id):
    doc_type = request.args.get('doc', 'order').lower() # 'order' (PO) or 'receive' (Goods Inward)
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            v.phone as vendor_phone,
            v.email as vendor_email,
            v.address1 as vendor_address,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE po.id = %s
    """, (id,))

    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    lines = query_all("""
        SELECT 
            pol.*,
            p.name as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            p.uom as product_uom
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    company = query_one("SELECT * FROM companies LIMIT 1")

    return render_template('purchases/po_print.html', order=order, lines=lines, company=company, doc_type=doc_type)

@purchase_orders_bp.route('/purchases/<int:id>/export/excel')
def export_po_excel(id):
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            COALESCE(po.contact, v.contact_name, '') as contact,
            COALESCE(po.phone, v.phone, '') as phone,
            COALESCE(po.vendor_address, v.address1, '') as vendor_address,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE po.id = %s
    """, (id,))
    if not order:
        flash("Purchase order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    lines = query_all("""
        SELECT 
            pol.*,
            COALESCE(pol.uom, p.purchasing_uom, p.uom, 'pcs.') as line_uom,
            p.name as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            COALESCE(p.uom, 'pcs.') as base_uom,
            COALESCE(p.purchasing_uom, p.uom, 'pcs.') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, p.master_pack_qty, p.inner_pack_qty, 1.0) as purchasing_ratio,
            COALESCE(p.sales_uom, p.uom, 'pcs.') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_ratio,
            COALESCE(p.packs_per_case, 0) as packs_per_case,
            COALESCE(p.pcs_per_pack, 0) as pcs_per_pack
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    company = query_one("SELECT * FROM companies LIMIT 1")
    buf = generate_po_excel(order, lines, company)
    order_num = order.get('order_number') or f"PO-{id}"
    filename = f"{order_num}_packing_list.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@purchase_orders_bp.route('/purchases/<int:id>/export/pdf')
def export_po_pdf(id):
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            COALESCE(po.contact, v.contact_name, '') as contact,
            COALESCE(po.phone, v.phone, '') as phone,
            COALESCE(po.vendor_address, v.address1, '') as vendor_address,
            l.name as location_name
        FROM purchase_orders po
        LEFT JOIN vendors v ON po.vendor_id = v.id
        LEFT JOIN locations l ON po.location_id = l.id
        WHERE po.id = %s
    """, (id,))
    if not order:
        flash("Purchase order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    raw_lines = query_all("""
        SELECT 
            pol.*,
            COALESCE(pol.uom, p.purchasing_uom, p.uom, 'pcs.') as line_uom,
            p.name as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            COALESCE(p.uom, 'pcs.') as base_uom,
            COALESCE(p.purchasing_uom, p.uom, 'pcs.') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, p.master_pack_qty, p.inner_pack_qty, 1.0) as purchasing_ratio,
            COALESCE(p.sales_uom, p.uom, 'pcs.') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_ratio,
            COALESCE(p.packs_per_case, 0) as packs_per_case,
            COALESCE(p.pcs_per_pack, 0) as pcs_per_pack
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    lines, has_case, total_cases, total_pcs = process_po_lines_for_export(raw_lines)
    company = query_one("SELECT * FROM companies LIMIT 1")

    return render_template(
        'purchases/po_export_pdf.html',
        order=order,
        lines=lines,
        company=company,
        has_case=has_case,
        total_cases=total_cases,
        total_pcs=total_pcs
    )

@purchase_orders_bp.route('/purchases/<int:id>/export')
def export_po(id):
    fmt = request.args.get('format', 'pdf').lower()
    if fmt in ('excel', 'xlsx'):
        return export_po_excel(id)
    return export_po_pdf(id)

@purchase_orders_bp.route('/purchases/<int:id>/cancel', methods=['POST'])
def cancel_purchase(id):
    order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        flash("Purchase order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    if order['status'] in ('RECEIVED', 'PAID'):
        flash("Cannot cancel a purchase order that has already been received or paid.", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    if order['status'] == 'CANCELLED':
        flash("Purchase order is already cancelled.", "info")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    with get_db_cursor(commit=True) as cur:
        # Revert open payable balance on vendor
        balance_due = float(order['balance_due'] or 0)
        if balance_due > 0 and order['vendor_id']:
            cur.execute("""
                UPDATE vendors 
                SET balance = GREATEST(0, balance - %s), updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (balance_due, order['vendor_id']))

        cur.execute("""
            UPDATE purchase_orders 
            SET status = 'CANCELLED', balance_due = 0, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s;
        """, (id,))

    flash(f"Purchase Order {order['order_number']} has been cancelled.", "success")
    return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/api/purchases/reorder-suggestions')
def api_reorder_suggestions():
    location_id = request.args.get('location_id')
    search = request.args.get('search', '').strip()
    loc_filter = ""
    inv_params = []
    if location_id and location_id.isdigit():
        loc_filter = "WHERE location_id = %s"
        inv_params.append(int(location_id))

    extra_clauses = []
    extra_params = []
    if search:
        extra_clauses.append("AND (p.sku ILIKE %s OR p.name ILIKE %s)")
        sp = f"%{search}%"
        extra_params.extend([sp, sp])

    extra_sql = " ".join(extra_clauses)

    sql = f"""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.barcode,
            COALESCE(p.reorder_point, 0) as reorder_point,
            COALESCE(p.reorder_quantity, 10) as reorder_quantity,
            COALESCE(p.last_purchase_cost, p.average_cost, p.standard_cost, 0) as unit_cost,
            COALESCE(inv.total_qty, 0) as on_hand,
            GREATEST(COALESCE(p.reorder_quantity, 10), COALESCE(p.reorder_point, 0) - COALESCE(inv.total_qty, 0)) as suggested_qty
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty 
            FROM inventory 
            {loc_filter}
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE p.is_active = TRUE 
          AND p.reorder_point > 0 
          AND COALESCE(inv.total_qty, 0) <= p.reorder_point
          {extra_sql}
        ORDER BY (COALESCE(inv.total_qty, 0) - p.reorder_point) ASC
        LIMIT 100;
    """
    items = query_all(sql, tuple(inv_params + extra_params))
    return jsonify([dict(r) for r in items])

@purchase_orders_bp.route('/api/vendors/quick-create', methods=['POST'])
def api_quick_create_vendor():
    try:
        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        contact_name = (data.get('contact_name') or data.get('contact') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip()
        address1 = (data.get('address1') or data.get('address') or '').strip()
        payment_terms = (data.get('payment_terms') or 'Net 30').strip()

        if not name:
            return jsonify({'success': False, 'message': 'Vendor name is required.'}), 400

        # Check existing
        existing = query_one("SELECT id, name, contact_name, phone, address1 FROM vendors WHERE LOWER(name) = LOWER(%s)", (name,))
        if existing:
            return jsonify({
                'success': True,
                'vendor': {
                    'id': existing['id'], 
                    'name': existing['name'], 
                    'contact_name': existing['contact_name'] or '',
                    'phone': existing['phone'] or phone, 
                    'address1': existing['address1'] or address1,
                    'balance': 0
                },
                'message': 'Vendor already exists and was selected.'
            })

        vendor_id = execute_returning_id("""
            INSERT INTO vendors (name, contact_name, phone, email, address1, payment_terms, balance, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 0, TRUE)
            RETURNING id;
        """, (name, contact_name, phone, email, address1, payment_terms))

        return jsonify({
            'success': True,
            'vendor': {
                'id': vendor_id,
                'name': name,
                'contact_name': contact_name,
                'phone': phone,
                'email': email,
                'address1': address1,
                'payment_terms': payment_terms,
                'balance': 0
            },
            'message': f"Vendor '{name}' created successfully!"
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
