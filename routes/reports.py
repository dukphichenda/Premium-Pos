from flask import Blueprint, render_template, request, Response, jsonify, redirect, url_for, session
from database import query_one, query_all
import csv
import io
import math
from datetime import datetime, date, timedelta
import calendar

reports_bp = Blueprint('reports', __name__)

# Complete inFlow Inventory Report Catalog matching Problem Steps Recording
REPORT_CATALOG = {
    'sales': {
        'name': 'Sales Reports',
        'key': 'sales',
        'items': [
            {
                'key': 'sales-by-product-summary',
                'title': 'Sales by Product Summary',
                'description': 'Summary of product sales quantities, revenues, costs, and profits.',
                'icon': '📦'
            },
            {
                'key': 'sales-by-product-details',
                'title': 'Sales by Product Details',
                'description': 'Itemized line transactions for product sales over a date period.',
                'icon': '📋'
            },
            {
                'key': 'sales-order-summary',
                'title': 'Sales Order Summary',
                'description': 'List of sales orders with customer, amounts, paid status, and balance due.',
                'icon': '📑'
            },
            {
                'key': 'sales-order-profit',
                'title': 'Sales Order Profit Report',
                'description': 'List of Sales Orders with the profit of each sales order.',
                'icon': '💰'
            },
            {
                'key': 'sales-order-operational',
                'title': 'Sales Order Operational Report',
                'description': 'Picking, packing, and shipping fulfillment status of sales orders.',
                'icon': '🚚'
            },
            {
                'key': 'sales-tax-report',
                'title': 'Sales Tax Report',
                'description': 'Summary of sales tax collected across taxable orders.',
                'icon': '🧾'
            },
            {
                'key': 'customer-payment-summary',
                'title': 'Customer Payment Summary',
                'description': 'Record of payments received from customers by payment method.',
                'icon': '💳'
            },
            {
                'key': 'customer-payment-details',
                'title': 'Customer Payment Details',
                'description': 'Detailed breakdown of customer invoices and receipts.',
                'icon': '💵'
            },
            {
                'key': 'customer-order-history',
                'title': 'Customer Order History',
                'description': 'Complete chronological order and invoice history per customer.',
                'icon': '👤'
            },
            {
                'key': 'customer-list',
                'title': 'Customer List',
                'description': 'A list of your customers and their contact information.',
                'icon': '👥'
            }
        ]
    },
    'purchasing': {
        'name': 'Purchasing Reports',
        'key': 'purchasing',
        'items': [
            {
                'key': 'purchase-order-summary',
                'title': 'Purchase Order Summary',
                'description': 'Summary of purchase orders with vendor, totals, and payment status.',
                'icon': '🛒'
            },
            {
                'key': 'purchase-order-details',
                'title': 'Purchase Order Details',
                'description': 'Itemized product lines ordered from vendors.',
                'icon': '📝'
            },
            {
                'key': 'purchase-order-status',
                'title': 'Purchase Order Status',
                'description': 'Receiving status and pending vendor shipments.',
                'icon': '📦'
            },
            {
                'key': 'purchasing-tax-report',
                'title': 'Purchasing Tax Report',
                'description': 'Summary of taxes paid to vendors on purchases.',
                'icon': '🧾'
            },
            {
                'key': 'product-cost-report',
                'title': 'Product Cost Report',
                'description': 'Average, standard, and last purchase cost breakdown per item.',
                'icon': '💲'
            },
            {
                'key': 'vendor-product-list',
                'title': 'Vendor Product List',
                'description': 'List of vendor item codes and supplier pricing.',
                'icon': '🏷️'
            },
            {
                'key': 'vendor-list',
                'title': 'Vendor List',
                'description': 'A list of your vendors and their contact information.',
                'icon': '🏭'
            }
        ]
    },
    'inventory': {
        'name': 'Inventory Reports',
        'key': 'inventory',
        'items': [
            {
                'key': 'inventory-summary',
                'title': 'Inventory Summary',
                'description': 'Current stock quantities on hand and reserved per location.',
                'icon': '📊'
            },
            {
                'key': 'inventory-valuation',
                'title': 'Inventory Valuation',
                'description': 'Total asset cost value and retail value of current stock.',
                'icon': '💎'
            },
            {
                'key': 'movement-log',
                'title': 'Stock Movement Log',
                'description': 'Audit trail of inventory transfers, adjustments, and receipts.',
                'icon': '🔄'
            },
            {
                'key': 'low-stock-reorder',
                'title': 'Low Stock Reorder Report',
                'description': 'Products below reorder threshold needing purchase replenishment.',
                'icon': '⚠️'
            }
        ]
    },
    'branch': {
        'name': 'Branch Reports',
        'key': 'branch',
        'items': [
            {
                'key': 'branch-sales-summary',
                'title': 'Branch Sales Summary',
                'description': 'Summary of branch sales by product, total money sold, and Branch Costing sheet calculation.',
                'icon': '🏬'
            }
        ]
    }
}

def get_report_meta(report_key):
    for cat in REPORT_CATALOG.values():
        for item in cat['items']:
            if item['key'] == report_key:
                return item, cat
    # Default fallback
    return {
        'key': report_key,
        'title': report_key.replace('-', ' ').title(),
        'description': 'inFlow Premium Report',
        'icon': '📊'
    }, {'name': 'General Reports', 'key': 'general'}

def calculate_date_range(preset, custom_from='', custom_to=''):
    now = datetime.now().date()
    if preset == 'Today':
        return now, now
    elif preset == 'This Week':
        start = now - timedelta(days=now.weekday())
        return start, start + timedelta(days=6)
    elif preset == 'This Month':
        start = now.replace(day=1)
        _, last_day = calendar.monthrange(now.year, now.month)
        return start, now.replace(day=last_day)
    elif preset == 'Last Month':
        first_this = now.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        start = last_prev.replace(day=1)
        return start, last_prev
    elif preset == 'This Year':
        return now.replace(month=1, day=1), now.replace(month=12, day=31)
    elif preset == 'Custom':
        try:
            d_from = datetime.strptime(custom_from, '%Y-%m-%d').date() if custom_from else now.replace(day=1)
            d_to = datetime.strptime(custom_to, '%Y-%m-%d').date() if custom_to else now
            return d_from, d_to
        except Exception:
            return now.replace(day=1), now
    else: # 'All'
        return date(2020, 1, 1), date(2035, 12, 31)

def _get_line_cogs_sql_expr(sol_alias='sol', p_alias='p'):
    """
    Computes accurate Cost of Goods Sold (COGS) for a sales order line:
    Focuses on UOM and costing compared to the pricing of the Sales Order:
    - If cost is already in the same UOM as the line unit price (e.g. packs, pcs, cases),
      uses quantity_display * cost.
    - If unit price is per case while cost is per piece, converts to case cost.
    - If unit price is per piece while cost is per case/pack, converts to piece cost.
    - Resolves inflated base quantity vs display quantity anomalies.
    """
    base_cost = f"COALESCE(NULLIF({sol_alias}.cost_price, 0), NULLIF({p_alias}.standard_cost, 0), NULLIF({p_alias}.average_cost, 0), 0)"
    return f"""
    CASE 
        WHEN {base_cost} = 0 THEN 0

        -- 1. Cost is already matching the SO pricing UOM:
        WHEN {sol_alias}.unit_price > 0 
             AND {base_cost} BETWEEN (0.05 * {sol_alias}.unit_price) AND (2.5 * {sol_alias}.unit_price)
             THEN COALESCE({sol_alias}.quantity_display, {sol_alias}.quantity, 1) * {base_cost}

        -- 2. Cost is per piece while SO pricing is per case (cost * ratio matches unit_price):
        WHEN {sol_alias}.unit_price > 0 
             AND {p_alias}.sales_uom_ratio_std > 1 
             AND ({base_cost} * {p_alias}.sales_uom_ratio_std) BETWEEN (0.05 * {sol_alias}.unit_price) AND (2.5 * {sol_alias}.unit_price)
             THEN COALESCE({sol_alias}.quantity_display, 1) * ({base_cost} * {p_alias}.sales_uom_ratio_std)

        -- 3. Cost is per case while SO pricing is per piece (cost / ratio matches unit_price):
        WHEN {sol_alias}.unit_price > 0 
             AND {p_alias}.sales_uom_ratio_std > 1 
             AND ({base_cost} / {p_alias}.sales_uom_ratio_std) BETWEEN (0.05 * {sol_alias}.unit_price) AND (2.5 * {sol_alias}.unit_price)
             THEN COALESCE({sol_alias}.quantity_display, {sol_alias}.quantity, 1) * ({base_cost} / {p_alias}.sales_uom_ratio_std)

        -- 4. Fallback when sol.quantity is in inflated base units (e.g. pieces) but quantity_display is in packs/cases:
        WHEN COALESCE({sol_alias}.quantity_display, 0) > 0 AND {sol_alias}.quantity > COALESCE({sol_alias}.quantity_display, 1) * 5
             THEN COALESCE({sol_alias}.quantity_display, 1) * {base_cost}

        ELSE COALESCE({sol_alias}.quantity_display, {sol_alias}.quantity, 1) * {base_cost}
    END
    """

# -------------------------------------------------------------------------
# Report List / Report Center (Matching screenshot0028.JPEG - screenshot0032.JPEG)
# -------------------------------------------------------------------------
@reports_bp.route('/reports')
@reports_bp.route('/reports/list')
def reports_center():
    selected_cat = request.args.get('cat', 'sales')
    selected_report = request.args.get('report', 'sales-order-profit')

    active_meta, active_cat = get_report_meta(selected_report)

    # Store Scope resolution: branch users strictly locked to their branch; HQ defaults to 'main'
    user_role = session.get('role')
    user_bid = session.get('branch_id')
    active_bid = session.get('active_branch_id')
    is_branch_user = (user_role in ('branch_admin', 'branch_cashier') and user_bid)

    req_branch = request.args.get('branch', '').strip().lower()
    if is_branch_user:
        branch_scope = str(user_bid)
    elif req_branch:
        branch_scope = req_branch
    elif active_bid:
        branch_scope = str(active_bid)
    else:
        branch_scope = 'main'

    if branch_scope == 'all':
        branch_scope_label = 'All Outlets (Consolidated)'
    elif branch_scope == 'main':
        branch_scope_label = 'Main Store (Headquarters)'
    else:
        try:
            b_row = query_one("SELECT code, name FROM branches WHERE id = %s", (int(branch_scope),))
            branch_scope_label = f"{b_row['code']} - {b_row['name']}" if b_row else f"Branch #{branch_scope}"
        except Exception:
            branch_scope_label = 'All Outlets'

    if is_branch_user:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE id = %s", (int(user_bid),))
    else:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")

    # Saved reports for "My Reports"
    my_reports = [
        {'key': 'sales-by-product-details', 'title': 'Sales by Product Details', 'date_saved': 'Saved: 08-Jul-26'},
        {'key': 'sales-order-profit', 'title': 'Sales Order Profit Report', 'date_saved': 'Saved: 06-Oct-26'},
        {'key': 'sales-order-profit', 'title': 'Sales Order Profit Report', 'date_saved': 'Saved: 23-Jul-26'},
        {'key': 'sales-order-profit', 'title': 'Sales Order Profit Report', 'date_saved': 'Saved: 01-Apr-25'},
        {'key': 'sales-order-profit', 'title': 'Sales Order Profit Report', 'date_saved': 'Saved: 26-Mar-25'},
        {'key': 'customer-order-history', 'title': 'Customer Order History', 'date_saved': 'Saved: 29-Sep-24'}
    ]

    today_str = datetime.now().strftime('%B %d, %Y')

    return render_template('reports/index.html',
                           catalog=REPORT_CATALOG,
                           selected_cat=selected_cat,
                           selected_report=selected_report,
                           active_meta=active_meta,
                           active_cat=active_cat,
                           branch_scope=branch_scope,
                           branch_scope_label=branch_scope_label,
                           all_branches=all_branches,
                           is_branch_user=is_branch_user,
                           my_reports=my_reports,
                           today_str=today_str)

# -------------------------------------------------------------------------
# Interactive Report Viewer & Generator (Matching screenshot0033 - 0070)
# -------------------------------------------------------------------------
@reports_bp.route('/reports/view/<report_key>')
def view_report(report_key):
    meta, cat = get_report_meta(report_key)

    # Filter parameters
    customer_id = request.args.get('customer_id', '').strip()
    customer_search = request.args.get('customer_search', '').strip()
    if customer_search == '<All>':
        customer_search = ''
    vendor_id = request.args.get('vendor_id', '')
    category_id = request.args.get('category_id', '')
    location_id = request.args.get('location_id', '')
    movement_type = request.args.get('movement_type', '')
    date_range = request.args.get('date_range', 'This Month')
    custom_from = request.args.get('date_from', '')
    custom_to = request.args.get('date_to', '')
    status = request.args.get('status', 'Paid' if report_key == 'sales-order-profit' else 'All')
    sort_by = request.args.get('sort_by', 'Total Sales' if report_key == 'branch-sales-summary' else 'Order Number')
    orientation = request.args.get('orientation', 'Landscape' if report_key in ['sales-order-operational', 'sales-by-product-details', 'inventory-valuation', 'branch-sales-summary'] else 'Portrait')
    group_by = request.args.get('group_by', 'None')
    page = max(1, int(request.args.get('page', 1)))
    per_page = 150 if (group_by == 'Category' or report_key == 'customer-order-history') else 36 # Rows per page matching printed sheet size
    
    # Store Scope: Branch users strictly locked to their branch; HQ can view main, branch, or all
    user_role = session.get('role')
    user_bid = session.get('branch_id')
    active_bid = session.get('active_branch_id')
    is_branch_user = (user_role in ('branch_admin', 'branch_cashier') and user_bid)
    is_main_admin = (user_role == 'main_admin') or (not user_role and not user_bid and not active_bid)

    req_branch = request.args.get('branch', '').strip().lower()

    if is_branch_user:
        # Branch users are strictly locked to their assigned branch
        branch_scope = str(user_bid)
    elif req_branch:
        branch_scope = req_branch
    elif active_bid:
        branch_scope = str(active_bid)
    elif report_key == 'branch-sales-summary':
        branch_scope = 'all'
    else:
        branch_scope = 'main'

    # Costing Tier / Price Sheet selection (Defaults to Branch Costing)
    all_pricing_schemes = query_all("SELECT id, name, currency FROM pricing_schemes WHERE is_active = TRUE ORDER BY CASE WHEN name ILIKE '%%Branch Costing%%' THEN 0 ELSE 1 END, name ASC")
    default_costing_scheme = query_one("SELECT id, name, currency FROM pricing_schemes WHERE name ILIKE '%%Branch Costing%%' LIMIT 1")
    default_costing_scheme_id = default_costing_scheme['id'] if default_costing_scheme else 107
    costing_scheme_id_param = request.args.get('costing_scheme_id', '').strip()
    try:
        costing_scheme_id = int(costing_scheme_id_param) if costing_scheme_id_param else default_costing_scheme_id
    except ValueError:
        costing_scheme_id = default_costing_scheme_id

    active_scheme = query_one("SELECT id, name, currency FROM pricing_schemes WHERE id = %s", (costing_scheme_id,))
    if not active_scheme:
        active_scheme = default_costing_scheme or {'id': default_costing_scheme_id, 'name': 'Branch Costing', 'currency': 'US Dollar ($)'}

    # Currency selection (USD or KHR)
    currency = request.args.get('currency', 'USD').strip().upper()
    if currency not in ['USD', 'KHR']:
        currency = 'USD'

    inv_set = query_one("SELECT khr_exchange_rate FROM invoice_settings LIMIT 1")
    khr_rate = float(inv_set.get('khr_exchange_rate') or 4100.0) if inv_set else 4100.0
    curr_multiplier = khr_rate if currency == 'KHR' else 1.0
    curr_symbol = '៛' if currency == 'KHR' else '$'

    if branch_scope == 'all':
        branch_scope_label = 'All Outlets (Consolidated)'
    elif branch_scope == 'main':
        branch_scope_label = 'Main Store (Headquarters)'
    else:
        try:
            b_row = query_one("SELECT code, name FROM branches WHERE id = %s", (int(branch_scope),))
            branch_scope_label = f"{b_row['code']} - {b_row['name']}" if b_row else f"Branch #{branch_scope}"
        except Exception:
            branch_scope_label = 'All Outlets'

    start_date, end_date = calculate_date_range(date_range, custom_from, custom_to)

    # Master Lookup Lists for Filter Dropdowns
    if branch_scope == 'main':
        all_customers = query_all("SELECT id, name FROM customers WHERE is_active = TRUE AND branch_id IS NULL ORDER BY name")
    elif branch_scope != 'all' and str(branch_scope).isdigit():
        all_customers = query_all("SELECT id, name FROM customers WHERE is_active = TRUE AND branch_id = %s ORDER BY name", (int(branch_scope),))
    else:
        all_customers = query_all("SELECT id, name FROM customers WHERE is_active = TRUE ORDER BY name")

    all_customers = [{'id': c['id'], 'name': c['name'] or ''} for c in all_customers]

    all_vendors = query_all("SELECT id, name FROM vendors WHERE is_active = TRUE ORDER BY name")
    all_categories = query_all("SELECT id, name FROM categories WHERE is_active = TRUE ORDER BY name")
    all_locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")

    if is_branch_user:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE id = %s", (int(user_bid),))
    else:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")

    selected_customer_name = ''
    if customer_id and customer_id.lower() != 'all':
        if str(customer_id).isdigit():
            for c in all_customers:
                if str(c['id']) == str(customer_id):
                    selected_customer_name = c['name']
                    break
        else:
            if not customer_search:
                customer_search = customer_id
            customer_id = ''

    if not selected_customer_name and customer_search:
        matched_c = [c for c in all_customers if customer_search.lower() in c['name'].lower()]
        if len(matched_c) == 1:
            customer_id = str(matched_c[0]['id'])
            selected_customer_name = matched_c[0]['name']
        elif matched_c and any(c['name'].lower() == customer_search.lower() for c in matched_c):
            exact = next(c for c in matched_c if c['name'].lower() == customer_search.lower())
            customer_id = str(exact['id'])
            selected_customer_name = exact['name']
        else:
            selected_customer_name = customer_search

    def apply_branch_scope(where_list, params_list):
        if branch_scope == 'main':
            where_list.append("so.branch_id IS NULL")
        elif branch_scope != 'all':
            try:
                bid = int(branch_scope)
                where_list.append("so.branch_id = %s")
                params_list.append(bid)
            except ValueError:
                where_list.append("so.branch_id IS NULL")

    rows = []
    total_count = 0
    total_pages = 1
    totals = {}
    category_groups = []
    customer_groups = []

    # 1. SALES ORDER PROFIT REPORT
    if report_key == 'sales-order-profit':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all' and str(customer_id).isdigit():
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        elif customer_search:
            base_where.append("c.name ILIKE %s")
            params.append(f"%{customer_search}%")

        if status == 'Paid':
            base_where.append("so.payment_status = 'PAID'")
        elif status == 'Open':
            base_where.append("so.status = 'OPEN'")
        elif status == 'Invoiced':
            base_where.append("so.status = 'INVOICED'")
        elif status != 'All':
            base_where.append("so.status = %s")
            params.append(status)

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM sales_orders so LEFT JOIN customers c ON so.customer_id = c.id WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
        totals_sql = f"""
            WITH order_costs AS (
                SELECT 
                    sol.sales_order_id,
                    COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
                FROM sales_order_lines sol
                LEFT JOIN products p ON sol.product_id = p.id
                GROUP BY sol.sales_order_id
            )
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(so.total_amount), 0) as total_sales,
                COALESCE(SUM(COALESCE(oc.total_cogs, 0)), 0) as total_cost,
                COALESCE(SUM(so.total_amount - COALESCE(oc.total_cogs, 0)), 0) as total_profit
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN order_costs oc ON so.id = oc.sales_order_id
            WHERE {where_sql}
        """
        totals_row = query_one(totals_sql, tuple(params))
        totals = {
            'sales_amount': float(totals_row['total_sales'] or 0),
            'costing': float(totals_row['total_cost'] or 0),
            'gross_profit': float(totals_row['total_profit'] or 0),
            'total_orders': totals_row['total_orders'] or 0
        }

        order_col = "so.order_number ASC"
        if sort_by == 'Order Date':
            order_col = "so.order_date ASC, so.order_number ASC"
        elif sort_by == 'Customer':
            order_col = "c.name ASC, so.order_number ASC"
        elif sort_by == 'Sales Amount':
            order_col = "so.total_amount DESC"
        elif sort_by in ('Total Cost', 'Costing', 'Branch Cost'):
            order_col = "costing DESC"
        elif sort_by == 'Gross Profit':
            order_col = "gross_profit DESC"

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            WITH order_costs AS (
                SELECT 
                    sol.sales_order_id,
                    COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
                FROM sales_order_lines sol
                LEFT JOIN products p ON sol.product_id = p.id
                GROUP BY sol.sales_order_id
            )
            SELECT 
                so.id,
                so.order_number,
                CASE WHEN so.payment_status = 'PAID' THEN 'Paid' ELSE initcap(so.status) END as status_display,
                c.name as customer_name,
                COALESCE(NULLIF(c.address1, ''), NULLIF(c.shipping_address, ''), c.city, '') as billing_address,
                so.order_date,
                so.total_amount as sales_amount,
                COALESCE(oc.total_cogs, 0) as costing,
                (so.total_amount - COALESCE(oc.total_cogs, 0)) as gross_profit
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN order_costs oc ON so.id = oc.sales_order_id
            WHERE {where_sql}
            ORDER BY {order_col}
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 2. SALES BY PRODUCT SUMMARY
    elif report_key == 'sales-by-product-summary':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        where_sql = " AND ".join(base_where)

        count_sql = f"""
            SELECT COUNT(DISTINCT sol.product_id) as cnt
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        total_count = query_one(count_sql, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
        totals_sql = f"""
            SELECT 
                COALESCE(SUM(sol.quantity), 0) as total_qty,
                COALESCE(SUM(sol.subtotal), 0) as total_sales,
                COALESCE(SUM(sol.subtotal - ({line_cogs_sql})), 0) as total_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'quantity': float(t['total_qty'] or 0),
            'sales_amount': float(t['total_sales'] or 0),
            'gross_profit': float(t['total_profit'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        if sort_by in ['Order Number', 'SKU', 'Order Number / SKU']:
            prod_sort = "p.sku ASC"
        elif sort_by in ['Item Name', 'Product Name', 'Name']:
            prod_sort = "p.name ASC"
        elif sort_by == 'Category':
            prod_sort = "category_name ASC, p.name ASC"
        elif sort_by in ['Quantity Sold', 'Quantity Sold (Pcs)', 'Quantity']:
            prod_sort = "quantity_sold DESC"
        elif sort_by in ['Gross Profit', 'Profit', 'Gross Profit / Asset Value']:
            prod_sort = "gross_profit DESC"
        else:
            prod_sort = "sales_amount DESC"

        if group_by == 'Category':
            prod_order_clause = f"c.name ASC, {prod_sort}"
        else:
            prod_order_clause = prod_sort

        data_sql = f"""
            SELECT 
                p.id, p.sku, p.name as item_name,
                c.name as category_name,
                SUM(sol.quantity) as quantity_sold,
                COALESCE(sol.uom, p.uom, 'pcs') as uom,
                SUM(sol.subtotal) as sales_amount,
                SUM(sol.subtotal - ({line_cogs_sql})) as gross_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE {where_sql}
            GROUP BY p.id, p.sku, p.name, c.name, COALESCE(sol.uom, p.uom, 'pcs')
            ORDER BY {prod_order_clause}
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

        if group_by == 'Category':
            cat_groups = {}
            for r in rows:
                cname = r.get('category_name') or 'General'
                if cname not in cat_groups:
                    cat_groups[cname] = {
                        'category_name': cname,
                        'lines': [],
                        'subtotal_qty': 0.0,
                        'subtotal_sales': 0.0,
                        'subtotal_profit': 0.0
                    }
                cat_groups[cname]['lines'].append(r)
                cat_groups[cname]['subtotal_qty'] += float(r.get('quantity_sold') or 0)
                cat_groups[cname]['subtotal_sales'] += float(r.get('sales_amount') or 0)
                cat_groups[cname]['subtotal_profit'] += float(r.get('gross_profit') or 0)
            category_groups = list(cat_groups.values())

    # 3. SALES BY PRODUCT DETAILS
    elif report_key == 'sales-by-product-details':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"""
            SELECT COUNT(*) as cnt
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
        totals_sql = f"""
            SELECT 
                COALESCE(SUM(sol.quantity), 0) as total_qty,
                COALESCE(SUM(sol.subtotal), 0) as total_sales,
                COALESCE(SUM(sol.subtotal - ({line_cogs_sql})), 0) as total_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'quantity': float(t['total_qty'] or 0),
            'sales_amount': float(t['total_sales'] or 0),
            'gross_profit': float(t['total_profit'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                so.id as sales_order_id,
                so.order_number,
                so.order_date,
                c.name as customer_name,
                p.sku,
                p.name as item_name,
                sol.quantity,
                COALESCE(sol.uom, p.uom, 'pcs') as uom,
                sol.unit_price,
                sol.subtotal as sales_amount,
                ({line_cogs_sql} / NULLIF(COALESCE(sol.quantity_display, sol.quantity, 1), 0)) as unit_cost,
                (sol.subtotal - ({line_cogs_sql})) as gross_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE {where_sql}
            ORDER BY so.order_date DESC, so.order_number DESC, sol.line_num ASC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 4. SALES ORDER SUMMARY
    elif report_key == 'sales-order-summary':
        base_where = ["so.order_date >= %s", "so.order_date <= %s"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        if status != 'All':
            if status == 'Paid':
                base_where.append("so.payment_status = 'PAID'")
            else:
                base_where.append("so.status = %s")
                params.append(status.upper())

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM sales_orders so WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(so.subtotal), 0) as tot_subtotal,
                COALESCE(SUM(so.total_amount), 0) as tot_amount,
                COALESCE(SUM(so.paid_amount), 0) as tot_paid,
                COALESCE(SUM(so.balance_due), 0) as tot_balance
            FROM sales_orders so
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'subtotal': float(t['tot_subtotal'] or 0),
            'sales_amount': float(t['tot_amount'] or 0),
            'paid_amount': float(t['tot_paid'] or 0),
            'balance_due': float(t['tot_balance'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                so.id,
                so.order_number,
                so.order_date,
                c.name as customer_name,
                initcap(so.status) as status_display,
                initcap(so.payment_status) as payment_status_display,
                so.subtotal,
                so.total_amount,
                so.paid_amount,
                so.balance_due
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE {where_sql}
            ORDER BY so.order_date DESC, so.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 5. SALES ORDER OPERATIONAL REPORT
    elif report_key == 'sales-order-operational':
        base_where = ["so.order_date >= %s", "so.order_date <= %s"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        if status != 'All':
            base_where.append("so.status = %s")
            params.append(status.upper())

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM sales_orders so WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals = {'total_orders': total_count}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                so.id,
                so.order_number,
                so.order_date,
                c.name as customer_name,
                initcap(so.status) as status_display,
                initcap(so.payment_status) as payment_status_display,
                so.picked_date,
                so.packed_date,
                so.shipped_date,
                COALESCE(so.carrier, 'Standard') as carrier,
                COALESCE(so.tracking_number, '-') as tracking_number,
                so.total_amount
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE {where_sql}
            ORDER BY so.order_date DESC, so.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 6. SALES TAX REPORT
    elif report_key == 'sales-tax-report':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM sales_orders so WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(so.subtotal), 0) as tot_subtotal,
                COALESCE(SUM(so.tax_amount), 0) as tot_tax,
                COALESCE(SUM(so.total_amount), 0) as tot_amount
            FROM sales_orders so
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'subtotal': float(t['tot_subtotal'] or 0),
            'tax_amount': float(t['tot_tax'] or 0),
            'sales_amount': float(t['tot_amount'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                so.id,
                so.order_number,
                so.order_date,
                c.name as customer_name,
                so.subtotal,
                so.tax_rate,
                so.tax_amount,
                so.total_amount
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE {where_sql}
            ORDER BY so.order_date DESC, so.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 7. CUSTOMER PAYMENT SUMMARY & DETAILS
    elif report_key in ['customer-payment-summary', 'customer-payment-details']:
        base_where = ["so.order_date >= %s", "so.order_date <= %s"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all':
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM sales_orders so WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(so.total_amount), 0) as tot_amount,
                COALESCE(SUM(so.paid_amount), 0) as tot_paid,
                COALESCE(SUM(so.balance_due), 0) as tot_balance
            FROM sales_orders so
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'sales_amount': float(t['tot_amount'] or 0),
            'paid_amount': float(t['tot_paid'] or 0),
            'balance_due': float(t['tot_balance'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                so.id,
                so.order_number,
                so.order_date,
                c.name as customer_name,
                initcap(so.payment_status) as payment_status,
                so.total_amount,
                so.paid_amount,
                so.balance_due
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE {where_sql}
            ORDER BY so.order_date DESC, so.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 8. CUSTOMER ORDER HISTORY (Matching inFlow screenshot0076.JPEG)
    elif report_key == 'customer-order-history':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        apply_branch_scope(base_where, params)

        if customer_id and customer_id != 'all' and str(customer_id).isdigit():
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        elif customer_search:
            base_where.append("c.name ILIKE %s")
            params.append(f"%{customer_search}%")

        if status and status != 'All':
            if status == 'Paid':
                base_where.append("so.payment_status = 'PAID'")
            elif status == 'Invoiced':
                base_where.append("so.status = 'INVOICED'")
            elif status == 'Open':
                base_where.append("so.status IN ('OPEN', 'PICKED', 'PACKED')")
            else:
                base_where.append("so.status = %s")
                params.append(status)

        if category_id and category_id != 'all' and str(category_id).isdigit():
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        where_sql = " AND ".join(base_where)

        count_sql = f"""
            SELECT COUNT(*) as cnt 
            FROM sales_orders so 
            JOIN customers c ON so.customer_id = c.id
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        total_count = query_one(count_sql, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(sol.quantity), 0) as tot_qty,
                COALESCE(SUM(sol.subtotal), 0) as tot_amount
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'quantity': float(t['tot_qty'] or 0),
            'amount': float(t['tot_amount'] or 0)
        }

        query_params = list(params) + [per_page, offset]

        # Chronological sort matching inFlow screenshot: customer name ASC, order date ASC, order number ASC
        if sort_by == 'Date Descending':
            order_clause = "c.name ASC, so.order_date DESC, so.order_number DESC, sol.id ASC"
        elif sort_by == 'Customer (Z-A)':
            order_clause = "c.name DESC, so.order_date ASC, so.order_number ASC, sol.id ASC"
        else:
            order_clause = "c.name ASC, so.order_date ASC, so.order_number ASC, sol.id ASC"

        data_sql = f"""
            SELECT 
                c.id as customer_id,
                c.name as customer_name,
                so.id as sales_order_id,
                so.order_number,
                so.order_date,
                initcap(so.status) as status_display,
                sol.id as line_id,
                sol.product_id,
                COALESCE(p.name, sol.description, 'Item') as item_name,
                p.sku,
                sol.quantity,
                sol.unit_price,
                sol.subtotal as amount,
                p.uom
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

        # Build customer groups with order subtotals and customer totals matching inFlow screenshot0076.JPEG
        customer_groups = []
        cur_cust_id = None
        cur_cust_name = None
        cur_orders = []
        cur_order_map = {}
        cur_all_lines = []

        for r in rows:
            cust_name = r['customer_name'] or 'Unassigned'
            cust_id = r['customer_id']
            so_id = r['sales_order_id']
            so_num = r['order_number']

            if cust_name != cur_cust_name:
                if cur_cust_name is not None:
                    c_qty = sum(o['subtotal_qty'] for o in cur_orders)
                    c_amt = sum(o['subtotal_amount'] for o in cur_orders)
                    customer_groups.append({
                        'customer_id': cur_cust_id,
                        'customer_name': cur_cust_name,
                        'orders': cur_orders,
                        'lines': cur_all_lines,
                        'subtotal_qty': c_qty,
                        'subtotal_amount': c_amt,
                        'total_qty': c_qty,
                        'total_amount': c_amt,
                    })
                cur_cust_name = cust_name
                cur_cust_id = cust_id
                cur_orders = []
                cur_order_map = {}
                cur_all_lines = []

            if so_id not in cur_order_map:
                order_entry = {
                    'sales_order_id': so_id,
                    'order_number': so_num,
                    'order_date': r['order_date'],
                    'status_display': r['status_display'],
                    'lines': [],
                    'subtotal_qty': 0.0,
                    'subtotal_amount': 0.0,
                }
                cur_order_map[so_id] = order_entry
                cur_orders.append(order_entry)

            qty = float(r['quantity'] or 0)
            amt = float(r['amount'] or 0)
            cur_order_map[so_id]['lines'].append(r)
            cur_order_map[so_id]['subtotal_qty'] += qty
            cur_order_map[so_id]['subtotal_amount'] += amt
            cur_all_lines.append(r)

        if cur_cust_name is not None:
            c_qty = sum(o['subtotal_qty'] for o in cur_orders)
            c_amt = sum(o['subtotal_amount'] for o in cur_orders)
            customer_groups.append({
                'customer_id': cur_cust_id,
                'customer_name': cur_cust_name,
                'orders': cur_orders,
                'lines': cur_all_lines,
                'subtotal_qty': c_qty,
                'subtotal_amount': c_amt,
                'total_qty': c_qty,
                'total_amount': c_amt,
            })

    # 9. CUSTOMER LIST
    elif report_key == 'customer-list':
        base_where = ["is_active = TRUE"]
        params = []
        if branch_scope == 'main':
            base_where.append("branch_id IS NULL")
        elif branch_scope != 'all':
            try:
                base_where.append("branch_id = %s")
                params.append(int(branch_scope))
            except ValueError:
                base_where.append("branch_id IS NULL")
        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM customers WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page

        t = query_one(f"SELECT COALESCE(SUM(balance), 0) as tot_bal FROM customers WHERE {where_sql}", tuple(params))
        totals = {'total_customers': total_count, 'balance_due': float(t['tot_bal'] or 0)}

        query_params = list(params) + [per_page, offset]
        rows = query_all(f"""
            SELECT id, name, contact_name, phone, email, address1, city, balance
            FROM customers
            WHERE {where_sql}
            ORDER BY name ASC
            LIMIT %s OFFSET %s
        """, tuple(query_params))

    # 10. PURCHASE ORDER SUMMARY
    elif report_key == 'purchase-order-summary':
        base_where = ["po.order_date >= %s", "po.order_date <= %s"]
        params = [start_date, end_date]

        if vendor_id and vendor_id != 'all':
            base_where.append("po.vendor_id = %s")
            params.append(int(vendor_id))
        if status != 'All':
            base_where.append("po.status = %s")
            params.append(status.upper())

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM purchase_orders po WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(po.total_amount), 0) as total_po,
                COALESCE(SUM(po.paid_amount), 0) as total_paid,
                COALESCE(SUM(po.balance_due), 0) as total_balance
            FROM purchase_orders po
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'total_amount': float(t['total_po'] or 0),
            'paid_amount': float(t['total_paid'] or 0),
            'balance_due': float(t['total_balance'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                po.id, po.order_number, po.order_date, initcap(po.status) as status_display,
                v.name as vendor_name,
                po.total_amount, po.paid_amount, po.balance_due
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE {where_sql}
            ORDER BY po.order_date DESC, po.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 11. PURCHASE ORDER DETAILS
    elif report_key == 'purchase-order-details':
        base_where = ["po.order_date >= %s", "po.order_date <= %s"]
        params = [start_date, end_date]

        if vendor_id and vendor_id != 'all':
            base_where.append("po.vendor_id = %s")
            params.append(int(vendor_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"""
            SELECT COUNT(*) as cnt
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            WHERE {where_sql}
        """, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(pol.quantity), 0) as total_qty,
                COALESCE(SUM(pol.subtotal), 0) as total_po
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'quantity': float(t['total_qty'] or 0),
            'total_amount': float(t['total_po'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                po.id as purchase_order_id,
                po.order_number,
                v.name as vendor_name,
                po.order_date,
                p.sku,
                p.name as item_name,
                pol.quantity,
                COALESCE(pol.received_qty, 0) as received_qty,
                p.uom,
                pol.unit_cost,
                pol.subtotal
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            JOIN products p ON pol.product_id = p.id
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE {where_sql}
            ORDER BY po.order_date DESC, po.order_number DESC, pol.line_num ASC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 12. PURCHASE ORDER STATUS
    elif report_key == 'purchase-order-status':
        base_where = ["po.order_date >= %s", "po.order_date <= %s"]
        params = [start_date, end_date]

        if vendor_id and vendor_id != 'all':
            base_where.append("po.vendor_id = %s")
            params.append(int(vendor_id))
        if status != 'All':
            base_where.append("po.status = %s")
            params.append(status.upper())

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM purchase_orders po WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"SELECT COALESCE(SUM(po.total_amount), 0) as tot_amt FROM purchase_orders po WHERE {where_sql}"
        t = query_one(totals_sql, tuple(params))
        totals = {'total_orders': total_count, 'total_amount': float(t['tot_amt'] or 0)}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                po.id,
                po.order_number,
                v.name as vendor_name,
                po.order_date,
                initcap(po.status) as status_display,
                initcap(po.payment_status) as payment_status_display,
                po.received_date,
                po.total_amount
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE {where_sql}
            ORDER BY po.order_date DESC, po.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 13. PURCHASING TAX REPORT
    elif report_key == 'purchasing-tax-report':
        base_where = ["po.order_date >= %s", "po.order_date <= %s"]
        params = [start_date, end_date]

        if vendor_id and vendor_id != 'all':
            base_where.append("po.vendor_id = %s")
            params.append(int(vendor_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM purchase_orders po WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(po.subtotal), 0) as tot_sub,
                COALESCE(SUM(po.tax_amount), 0) as tot_tax,
                COALESCE(SUM(po.total_amount), 0) as tot_amt
            FROM purchase_orders po
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'subtotal': float(t['tot_sub'] or 0),
            'tax_amount': float(t['tot_tax'] or 0),
            'total_amount': float(t['tot_amt'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                po.id,
                po.order_number,
                v.name as vendor_name,
                po.order_date,
                po.subtotal,
                po.tax_rate,
                po.tax_amount,
                po.total_amount
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE {where_sql}
            ORDER BY po.order_date DESC, po.order_number DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 14. PRODUCT COST REPORT
    elif report_key == 'product-cost-report':
        base_where = ["p.is_active = TRUE"]
        params = []
        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM products p WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals = {'total_products': total_count}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                p.id,
                p.sku,
                p.name as item_name,
                c.name as category_name,
                p.uom,
                p.average_cost,
                p.standard_cost,
                p.last_purchase_cost,
                p.default_price,
                CASE WHEN p.default_price > 0 
                     THEN ROUND(((p.default_price - COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0)) / p.default_price * 100), 2)
                     ELSE 0 END as margin_percent
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE {where_sql}
            ORDER BY p.sku ASC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 15. VENDOR PRODUCT LIST
    elif report_key == 'vendor-product-list':
        base_where = ["p.is_active = TRUE"]
        params = []
        if vendor_id and vendor_id != 'all':
            base_where.append("p.last_vendor_id = %s")
            params.append(int(vendor_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM products p WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals = {'total_products': total_count}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                COALESCE(v.name, 'Unassigned') as vendor_name,
                p.sku,
                p.name as item_name,
                c.name as category_name,
                p.standard_cost,
                p.uom
            FROM products p
            LEFT JOIN vendors v ON p.last_vendor_id = v.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE {where_sql}
            ORDER BY vendor_name ASC, p.sku ASC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 16. VENDOR LIST
    elif report_key == 'vendor-list':
        total_count = query_one("SELECT COUNT(*) as cnt FROM vendors WHERE is_active = TRUE")['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page

        t = query_one("SELECT COALESCE(SUM(balance), 0) as tot_bal FROM vendors WHERE is_active = TRUE")
        totals = {'total_vendors': total_count, 'balance_due': float(t['tot_bal'] or 0)}

        rows = query_all("""
            SELECT id, name, contact_name, phone, email, address1, city, country, balance
            FROM vendors
            WHERE is_active = TRUE
            ORDER BY name ASC
            LIMIT %s OFFSET %s
        """, (per_page, offset))

    # 17. INVENTORY SUMMARY (Matching inFlow screenshot0080.JPEG & screenshot0083.JPEG)
    elif report_key == 'inventory-summary':
        base_where = ["p.is_active = TRUE"]
        params = []
        loc_clause = ""
        inv_params = []
        if category_id and category_id != 'all' and str(category_id).isdigit():
            base_where.append("p.category_id = %s")
            params.append(int(category_id))
        if location_id and location_id != 'all' and str(location_id).isdigit():
            loc_clause = "AND i.location_id = %s"
            inv_params.append(int(location_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM products p WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(inv.qty), 0) as tot_qty,
                COALESCE(SUM(inv.res), 0) as tot_res,
                COALESCE(SUM(inv.qty - inv.res), 0) as tot_avail,
                COALESCE(SUM(inv.qty * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0)), 0) as tot_cost
            FROM products p
            LEFT JOIN (
                SELECT product_id, SUM(quantity) as qty, SUM(reserved_quantity) as res
                FROM inventory i
                WHERE 1=1 {loc_clause}
                GROUP BY product_id
            ) inv ON inv.product_id = p.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(inv_params + params))
        totals = {
            'on_hand': float(t['tot_qty'] or 0),
            'reserved_quantity': float(t['tot_res'] or 0),
            'available_quantity': float(t['tot_avail'] or 0),
            'total_cost_value': float(t['tot_cost'] or 0)
        }

        data_sql = f"""
            SELECT 
                p.id,
                p.sku,
                p.name as item_name,
                COALESCE(c.name, 'General') as category_name,
                COALESCE(SUM(i.quantity), 0) as on_hand,
                COALESCE(SUM(i.reserved_quantity), 0) as reserved_quantity,
                COALESCE(SUM(i.quantity - i.reserved_quantity), 0) as available_quantity,
                COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost,
                COALESCE(SUM(i.quantity), 0) * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as total_cost_value,
                p.uom
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN inventory i ON i.product_id = p.id {loc_clause}
            WHERE {where_sql}
            GROUP BY p.id, p.sku, p.name, c.name, p.average_cost, p.standard_cost, p.uom
            ORDER BY category_name ASC, p.name ASC
            LIMIT %s OFFSET %s
        """
        data_params = tuple(inv_params + params + [per_page, offset])
        rows = query_all(data_sql, data_params)

        # Build category groups with subtotals matching inFlow screenshot0080.JPEG
        category_groups = []
        cur_cat = None
        cur_items = []
        for r in rows:
            cat = r['category_name'] or 'General'
            if cat != cur_cat:
                if cur_items:
                    category_groups.append({
                        'category_name': cur_cat,
                        'lines': cur_items,
                        'subtotal_on_hand': sum(float(item['on_hand'] or 0) for item in cur_items),
                        'subtotal_reserved': sum(float(item['reserved_quantity'] or 0) for item in cur_items),
                        'subtotal_available': sum(float(item['available_quantity'] or 0) for item in cur_items),
                        'subtotal_cost': sum(float(item['total_cost_value'] or 0) for item in cur_items)
                    })
                cur_cat = cat
                cur_items = [r]
            else:
                cur_items.append(r)
        if cur_items:
            category_groups.append({
                'category_name': cur_cat,
                'lines': cur_items,
                'subtotal_on_hand': sum(float(item['on_hand'] or 0) for item in cur_items),
                'subtotal_reserved': sum(float(item['reserved_quantity'] or 0) for item in cur_items),
                'subtotal_available': sum(float(item['available_quantity'] or 0) for item in cur_items),
                'subtotal_cost': sum(float(item['total_cost_value'] or 0) for item in cur_items)
            })

    # 18. INVENTORY VALUATION
    elif report_key == 'inventory-valuation':
        base_where = ["p.is_active = TRUE", "i.quantity > 0"]
        params = []
        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))
        if location_id and location_id != 'all':
            base_where.append("i.location_id = %s")
            params.append(int(location_id))

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"""
            SELECT COUNT(*) as cnt 
            FROM inventory i 
            JOIN products p ON i.product_id = p.id 
            WHERE {where_sql}
        """, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(i.quantity), 0) as tot_units,
                COALESCE(SUM(i.quantity * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0)), 0) as asset_val,
                COALESCE(SUM(i.quantity * p.default_price), 0) as retail_val
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            WHERE {where_sql}
        """
        t = query_one(totals_sql, tuple(params))
        totals = {
            'quantity': float(t['tot_units'] or 0),
            'asset_value': float(t['asset_val'] or 0),
            'retail_value': float(t['retail_val'] or 0)
        }

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                p.id,
                p.sku,
                p.name as item_name,
                c.name as category_name,
                l.name as location_name,
                i.quantity,
                p.uom,
                COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost,
                (i.quantity * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0)) as asset_value,
                p.default_price as retail_price,
                (i.quantity * p.default_price) as retail_value
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN locations l ON i.location_id = l.id
            WHERE {where_sql}
            ORDER BY asset_value DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 19. STOCK MOVEMENT LOG
    elif report_key == 'movement-log':
        base_where = ["1=1"]
        params = []
        if movement_type and movement_type != 'all':
            base_where.append("il.movement_type = %s")
            params.append(movement_type)

        where_sql = " AND ".join(base_where)

        total_count = query_one(f"SELECT COUNT(*) as cnt FROM inventory_logs il WHERE {where_sql}", tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals = {'total_movements': total_count}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            SELECT 
                il.id,
                il.created_at,
                il.movement_type,
                p.sku,
                p.name as product_name,
                fl.name as from_location_name,
                tl.name as to_location_name,
                il.quantity,
                il.reason,
                il.notes
            FROM inventory_logs il
            JOIN products p ON il.product_id = p.id
            LEFT JOIN locations fl ON il.from_location_id = fl.id
            LEFT JOIN locations tl ON il.to_location_id = tl.id
            WHERE {where_sql}
            ORDER BY il.created_at DESC, il.id DESC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 20. LOW STOCK REORDER REPORT
    elif report_key == 'low-stock-reorder':
        base_where = [
            "p.is_active = TRUE",
            "COALESCE(ps.on_hand, 0) <= COALESCE(p.reorder_point, p.min_stock, 0)",
            "COALESCE(p.reorder_point, p.min_stock, 0) > 0"
        ]
        params = []
        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        where_sql = " AND ".join(base_where)

        count_sql = f"""
            WITH prod_stock AS (
                SELECT product_id, SUM(quantity) as on_hand
                FROM inventory
                GROUP BY product_id
            )
            SELECT COUNT(*) as cnt
            FROM products p
            LEFT JOIN prod_stock ps ON p.id = ps.product_id
            WHERE {where_sql}
        """
        total_count = query_one(count_sql, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        totals = {'low_stock_items': total_count}

        query_params = list(params) + [per_page, offset]
        data_sql = f"""
            WITH prod_stock AS (
                SELECT product_id, SUM(quantity) as on_hand
                FROM inventory
                GROUP BY product_id
            )
            SELECT 
                p.id,
                p.sku,
                p.name as item_name,
                c.name as category_name,
                COALESCE(ps.on_hand, 0) as on_hand,
                COALESCE(p.reorder_point, p.min_stock, 0) as reorder_point,
                COALESCE(p.reorder_quantity, 0) as reorder_qty,
                COALESCE(v.name, 'Unassigned') as vendor_name
            FROM products p
            LEFT JOIN prod_stock ps ON p.id = ps.product_id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN vendors v ON p.last_vendor_id = v.id
            WHERE {where_sql}
            ORDER BY on_hand ASC
            LIMIT %s OFFSET %s
        """
        rows = query_all(data_sql, tuple(query_params))

    # 17. BRANCH SALES SUMMARY REPORT
    elif report_key == 'branch-sales-summary':
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]

        if branch_scope == 'main':
            base_where.append("so.branch_id IS NULL")
        elif branch_scope != 'all':
            try:
                base_where.append("so.branch_id = %s")
                params.append(int(branch_scope))
            except ValueError:
                pass

        if category_id and category_id != 'all':
            base_where.append("p.category_id = %s")
            params.append(int(category_id))

        if status == 'Paid':
            base_where.append("so.payment_status = 'PAID'")
        elif status == 'Invoiced':
            base_where.append("so.status = 'INVOICED'")
        elif status == 'Open':
            base_where.append("so.status = 'OPEN'")
        elif status != 'All':
            base_where.append("so.status = %s")
            params.append(status)

        where_sql = " AND ".join(base_where)

        count_sql = f"""
            SELECT COUNT(DISTINCT sol.product_id) as cnt
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
        """
        total_count = query_one(count_sql, tuple(params))['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        cost_unit_expr = """
            CASE 
                WHEN pp.unit_price IS NOT NULL AND pp.unit_price > 0 AND p.sales_uom_ratio_std > 1 
                    THEN (pp.unit_price / p.sales_uom_ratio_std) 
                WHEN pp.unit_price IS NOT NULL AND pp.unit_price > 0 
                    THEN pp.unit_price 
                WHEN p.standard_cost IS NOT NULL AND p.standard_cost > 0 
                    THEN p.standard_cost 
                WHEN p.average_cost IS NOT NULL AND p.average_cost > 0 
                    THEN p.average_cost 
                ELSE 0 
            END
        """

        totals_sql = f"""
            SELECT 
                COALESCE(SUM(sol.quantity), 0) as total_qty,
                COALESCE(SUM(sol.subtotal), 0) as total_sales,
                COALESCE(SUM(sol.quantity * ({cost_unit_expr})), 0) as total_branch_cost,
                COALESCE(SUM(sol.subtotal - (sol.quantity * ({cost_unit_expr}))), 0) as total_branch_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id AND pp.pricing_scheme_id = %s
            WHERE {where_sql}
        """
        t_params = [costing_scheme_id] + params
        t = query_one(totals_sql, tuple(t_params))
        raw_qty = float(t['total_qty'] or 0)
        raw_sales = float(t['total_sales'] or 0)
        raw_cost = float(t['total_branch_cost'] or 0)
        raw_profit = float(t['total_branch_profit'] or 0)
        margin_pct = (raw_profit / raw_sales * 100.0) if raw_sales > 0 else 0.0

        totals = {
            'quantity': raw_qty,
            'quantity_sold': raw_qty,
            'quantity_sold_pcs': raw_qty,
            'sales_amount': raw_sales * curr_multiplier,
            'branch_cost': raw_cost * curr_multiplier,
            'total_branch_cost': raw_cost * curr_multiplier,
            'profit': raw_profit * curr_multiplier,
            'branch_profit': raw_profit * curr_multiplier,
            'margin_pct': margin_pct
        }

        if sort_by in ['Order Number', 'SKU', 'Order Number / SKU']:
            sort_order = "p.sku ASC"
        elif sort_by in ['Item Name', 'Product Name', 'Name']:
            sort_order = "p.name ASC"
        elif sort_by == 'Category':
            sort_order = "c.name ASC, p.name ASC"
        elif sort_by in ['Quantity Sold', 'Quantity Sold (Pcs)', 'Quantity']:
            sort_order = "quantity_sold DESC"
        elif sort_by in ['Price / PCS', 'Price']:
            sort_order = "(SUM(sol.subtotal) / NULLIF(SUM(sol.quantity), 0)) DESC"
        elif sort_by in ['Total Cost', 'Branch Cost', 'Total Branch Cost']:
            sort_order = "total_branch_cost DESC"
        elif sort_by in ['Gross Profit', 'Profit', 'Gross Profit / Asset Value']:
            sort_order = "branch_profit DESC"
        else:
            sort_order = "sales_amount DESC"

        if group_by == 'Category':
            order_clause = f"COALESCE(c.name, 'General') ASC, {sort_order}"
        else:
            order_clause = sort_order

        data_sql = f"""
            SELECT 
                p.id, p.sku, p.name as item_name,
                COALESCE(c.name, 'General') as category_name,
                COALESCE(p.uom, 'pcs') as base_uom,
                COALESCE(p.sales_uom, 'cases') as sales_uom,
                COALESCE(p.sales_uom_ratio_std, 1.0) as pcs_per_case,
                COALESCE(pp.unit_price, 0) as sheet_price,
                SUM(sol.quantity) as quantity_sold,
                SUM(sol.subtotal) as sales_amount,
                {cost_unit_expr} as raw_branch_cost_pc,
                SUM(sol.quantity * ({cost_unit_expr})) as total_branch_cost,
                SUM(sol.subtotal) - SUM(sol.quantity * ({cost_unit_expr})) as branch_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id AND pp.pricing_scheme_id = %s
            WHERE {where_sql}
            GROUP BY p.id, p.sku, p.name, c.name, p.uom, p.sales_uom, p.sales_uom_ratio_std, pp.unit_price, p.standard_cost, p.average_cost
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """
        d_params = [costing_scheme_id] + params + [per_page, offset]
        raw_rows = query_all(data_sql, tuple(d_params))

        rows = []
        for r in raw_rows:
            qty_pcs = float(r['quantity_sold'] or 0)
            sales = float(r['sales_amount'] or 0)
            cost_pc = float(r['raw_branch_cost_pc'] or 0)
            total_cost = float(r['total_branch_cost'] or 0)
            profit = float(r['branch_profit'] or 0)
            price_pc = (sales / qty_pcs) if qty_pcs > 0 else 0.0
            m_pct = (profit / sales * 100.0) if sales > 0 else 0.0

            pcs_ratio = float(r['pcs_per_case'] or 1.0)
            case_sheet_price = float(r['sheet_price'] or 0.0)
            cases_equivalent = (qty_pcs / pcs_ratio) if pcs_ratio > 1 else None
            price_case = (price_pc * pcs_ratio) if pcs_ratio > 1 else None
            cost_case = (cost_pc * pcs_ratio) if pcs_ratio > 1 else None

            rows.append({
                'id': r['id'],
                'product_id': r['id'],
                'sku': r['sku'],
                'item_name': r['item_name'],
                'product_name': r['item_name'],
                'category_name': r['category_name'],
                'uom': 'pcs',
                'quantity_sold': qty_pcs,
                'quantity_sold_pcs': qty_pcs,
                'pcs_per_case': pcs_ratio,
                'cases_equivalent': cases_equivalent,
                'avg_sale_price': price_pc * curr_multiplier,
                'sale_price_pc': price_pc * curr_multiplier,
                'sale_price_case': price_case * curr_multiplier if price_case else None,
                'sales_amount': sales * curr_multiplier,
                'branch_unit_cost': cost_pc * curr_multiplier,
                'branch_cost_pc': cost_pc * curr_multiplier,
                'branch_cost_case': cost_case * curr_multiplier if cost_case else None,
                'total_branch_cost': total_cost * curr_multiplier,
                'branch_profit': profit * curr_multiplier,
                'margin_pct': m_pct
            })

        if group_by == 'Category':
            cat_groups = {}
            for r in rows:
                cname = r.get('category_name') or 'General'
                if cname not in cat_groups:
                    cat_groups[cname] = {
                        'category_name': cname,
                        'lines': [],
                        'subtotal_qty': 0.0,
                        'subtotal_sales': 0.0,
                        'subtotal_cost': 0.0,
                        'subtotal_profit': 0.0,
                        'subtotal_margin': 0.0,
                        'avg_price_pc': 0.0,
                        'avg_cost_pc': 0.0
                    }
                cat_groups[cname]['lines'].append(r)
                cat_groups[cname]['subtotal_qty'] += float(r.get('quantity_sold') or 0)
                cat_groups[cname]['subtotal_sales'] += float(r.get('sales_amount') or 0)
                cat_groups[cname]['subtotal_cost'] += float(r.get('total_branch_cost') or 0)
                cat_groups[cname]['subtotal_profit'] += float(r.get('branch_profit') or 0)

            for cg in cat_groups.values():
                sqty = cg['subtotal_qty']
                ssales = cg['subtotal_sales']
                scost = cg['subtotal_cost']
                sprofit = cg['subtotal_profit']
                cg['subtotal_margin'] = (sprofit / ssales * 100.0) if ssales > 0 else 0.0
                cg['avg_price_pc'] = (ssales / sqty) if sqty > 0 else 0.0
                cg['avg_cost_pc'] = (scost / sqty) if sqty > 0 else 0.0

            category_groups = list(cat_groups.values())

    else:
        # Fallback generic sales orders list
        total_count = query_one("SELECT COUNT(*) as cnt FROM sales_orders")['cnt']
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page
        rows = query_all("""
            SELECT so.id, so.order_number, so.order_date, so.status, c.name as customer_name,
                   so.subtotal, so.total_amount, so.paid_amount, so.balance_due
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            ORDER BY so.order_date DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))

    today_str = datetime.now().strftime('%B %d, %Y')

    selected_category_name = ''
    if category_id and category_id.lower() != 'all':
        for c_item in all_categories:
            if str(c_item['id']) == str(category_id):
                selected_category_name = c_item['name']
                break

    return render_template('reports/viewer.html',
                           report_key=report_key,
                           meta=meta,
                           cat=cat,
                           rows=rows,
                           totals=totals,
                           total_count=total_count,
                           page=page,
                           total_pages=total_pages,
                           per_page=per_page,
                           customer_id=customer_id,
                           customer_search=customer_search,
                           selected_customer_name=selected_customer_name,
                           selected_category_name=selected_category_name,
                           vendor_id=vendor_id,
                           category_id=category_id,
                           location_id=location_id,
                           movement_type=movement_type,
                           all_customers=all_customers,
                           all_vendors=all_vendors,
                           all_categories=all_categories,
                           all_locations=all_locations,
                           date_range=date_range,
                           date_from=str(start_date),
                           date_to=str(end_date),
                           status=status,
                           sort_by=sort_by,
                           orientation=orientation,
                           group_by=group_by,
                           branch_scope=branch_scope,
                           branch_scope_label=branch_scope_label,
                           all_branches=all_branches,
                           is_branch_user=is_branch_user,
                           all_pricing_schemes=all_pricing_schemes,
                           costing_scheme_id=costing_scheme_id,
                           active_scheme=active_scheme,
                           currency=currency,
                           curr_symbol=curr_symbol,
                           khr_rate=khr_rate,
                           category_groups=locals().get('category_groups', []),
                           customer_groups=locals().get('customer_groups', []),
                           today_str=today_str)

# -------------------------------------------------------------------------
# Report Export (CSV matching screenshot0070.JPEG)
# -------------------------------------------------------------------------
@reports_bp.route('/reports/export/<report_key>')
def export_report(report_key):
    date_range = request.args.get('date_range', 'This Month')
    custom_from = request.args.get('date_from', '')
    custom_to = request.args.get('date_to', '')
    status = request.args.get('status', 'Paid')
    customer_id = request.args.get('customer_id', '').strip()
    customer_search = request.args.get('customer_search', '').strip()
    if customer_search == '<All>':
        customer_search = ''
    if customer_id and not str(customer_id).isdigit() and not customer_search:
        customer_search = customer_id
        customer_id = ''
    vendor_id = request.args.get('vendor_id', '')
    category_id = request.args.get('category_id', '')
    location_id = request.args.get('location_id', '')
    sort_by = request.args.get('sort_by', 'Sales Amount').strip()
    group_by = request.args.get('group_by', '').strip()

    # Store Scope resolution: branch users strictly locked to their branch; HQ can view main, branch, or all
    user_role = session.get('role')
    user_bid = session.get('branch_id')
    active_bid = session.get('active_branch_id')
    is_branch_user = (user_role in ('branch_admin', 'branch_cashier') and user_bid)

    req_branch = request.args.get('branch', '').strip().lower()
    if is_branch_user:
        branch_scope = str(user_bid)
    elif req_branch:
        branch_scope = req_branch
    elif active_bid:
        branch_scope = str(active_bid)
    elif report_key == 'branch-sales-summary':
        branch_scope = 'all'
    else:
        branch_scope = 'main'

    start_date, end_date = calculate_date_range(date_range, custom_from, custom_to)

    output = io.StringIO()
    writer = csv.writer(output)

    if report_key == 'sales-order-profit':
        writer.writerow(['Order Number', 'Status', 'Customer', 'Billing Address', 'Order Date', 'Sales Amount ($)', 'Costing ($)', 'Gross Profit ($)'])
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        if branch_scope == 'main':
            base_where.append("so.branch_id IS NULL")
        elif branch_scope != 'all' and str(branch_scope).isdigit():
            base_where.append("so.branch_id = %s")
            params.append(int(branch_scope))

        if customer_id and customer_id != 'all' and str(customer_id).isdigit():
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        elif customer_search:
            base_where.append("c.name ILIKE %s")
            params.append(f"%{customer_search}%")

        if status == 'Paid':
            base_where.append("so.payment_status = 'PAID'")
        elif status == 'Open':
            base_where.append("so.status = 'OPEN'")
        elif status == 'Invoiced':
            base_where.append("so.status = 'INVOICED'")
        elif status != 'All':
            base_where.append("so.status = %s")
            params.append(status)

        where_sql = " AND ".join(base_where)
        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
        rows = query_all(f"""
            WITH order_costs AS (
                SELECT 
                    sol.sales_order_id,
                    COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
                FROM sales_order_lines sol
                LEFT JOIN products p ON sol.product_id = p.id
                GROUP BY sol.sales_order_id
            )
            SELECT 
                so.order_number,
                CASE WHEN so.payment_status = 'PAID' THEN 'Paid' ELSE initcap(so.status) END as status_display,
                c.name as customer_name,
                COALESCE(NULLIF(c.address1, ''), NULLIF(c.shipping_address, ''), c.city, '') as billing_address,
                so.order_date,
                so.total_amount as sales_amount,
                COALESCE(oc.total_cogs, 0) as costing,
                (so.total_amount - COALESCE(oc.total_cogs, 0)) as gross_profit
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN order_costs oc ON so.id = oc.sales_order_id
            WHERE {where_sql}
            ORDER BY so.order_date ASC, so.order_number ASC
        """, tuple(params))

        for r in rows:
            writer.writerow([
                r['order_number'],
                r['status_display'],
                r['customer_name'] or '',
                r['billing_address'] or '',
                str(r['order_date']),
                f"{float(r['sales_amount'] or 0):.2f}",
                f"{float(r['costing'] or 0):.2f}",
                f"{float(r['gross_profit'] or 0):.2f}"
            ])
        filename = f"Sales_Order_Profit_Report_{start_date}_{end_date}.csv"

    elif report_key == 'sales-by-product-summary':
        writer.writerow(['Category', 'Item SKU', 'Item Name', 'Quantity Sold', 'UOM', 'Total Sales ($)', 'Gross Profit ($)'])
        where_branch = "so.branch_id IS NULL" if branch_scope == 'main' else (f"so.branch_id = {int(branch_scope)}" if branch_scope.isdigit() else "1=1")

        if sort_by in ['Order Number', 'SKU', 'Order Number / SKU']:
            prod_sort = "p.sku ASC"
        elif sort_by in ['Item Name', 'Product Name', 'Name']:
            prod_sort = "p.name ASC"
        elif sort_by == 'Category':
            prod_sort = "category_name ASC, p.name ASC"
        elif sort_by in ['Quantity Sold', 'Quantity Sold (Pcs)', 'Quantity']:
            prod_sort = "quantity_sold DESC"
        elif sort_by in ['Gross Profit', 'Profit', 'Gross Profit / Asset Value']:
            prod_sort = "gross_profit DESC"
        else:
            prod_sort = "sales_amount DESC"

        if group_by == 'Category':
            prod_order_clause = f"COALESCE(c.name, 'General') ASC, {prod_sort}"
        else:
            prod_order_clause = prod_sort

        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
        rows = query_all(f"""
            SELECT 
                COALESCE(c.name, 'General') as category_name, p.sku, p.name as item_name,
                SUM(sol.quantity) as quantity_sold,
                COALESCE(sol.uom, p.uom, 'pcs') as uom,
                SUM(sol.subtotal) as sales_amount,
                SUM(sol.subtotal - ({line_cogs_sql})) as gross_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE so.order_date >= %s AND so.order_date <= %s AND so.status != 'CANCELLED' AND {where_branch}
            GROUP BY c.name, p.sku, p.name, COALESCE(sol.uom, p.uom, 'pcs')
            ORDER BY {prod_order_clause}
        """, (start_date, end_date))
        for r in rows:
            writer.writerow([r['category_name'] or '', r['sku'], r['item_name'], f"{float(r['quantity_sold'] or 0):.0f}", r['uom'], f"{float(r['sales_amount'] or 0):.2f}", f"{float(r['gross_profit'] or 0):.2f}"])
        filename = f"Sales_by_Product_Summary_{start_date}_{end_date}.csv"

    elif report_key == 'customer-order-history':
        writer.writerow(['Customer', 'Order Number', 'Order Date', 'Status', 'Item Name', 'SKU', 'Quantity', 'UOM', 'Unit Price ($)', 'Amount ($)'])
        base_where = ["so.order_date >= %s", "so.order_date <= %s", "so.status != 'CANCELLED'"]
        params = [start_date, end_date]
        if branch_scope == 'main':
            base_where.append("so.branch_id IS NULL")
        elif branch_scope != 'all' and branch_scope.isdigit():
            base_where.append("so.branch_id = %s")
            params.append(int(branch_scope))
        if customer_id and customer_id != 'all' and str(customer_id).isdigit():
            base_where.append("so.customer_id = %s")
            params.append(int(customer_id))
        if status and status != 'All':
            if status == 'Paid':
                base_where.append("so.payment_status = 'PAID'")
            elif status == 'Invoiced':
                base_where.append("so.status = 'INVOICED'")
            elif status == 'Open':
                base_where.append("so.status IN ('OPEN', 'PICKED', 'PACKED')")
        where_sql = " AND ".join(base_where)
        rows = query_all(f"""
            SELECT 
                c.name as customer_name, so.order_number, so.order_date,
                initcap(so.status) as status_display,
                COALESCE(p.name, sol.description, 'Item') as item_name, p.sku,
                sol.quantity, p.uom, sol.unit_price, sol.subtotal as amount
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE {where_sql}
            ORDER BY c.name ASC, so.order_date DESC, so.order_number DESC
        """, tuple(params))
        for r in rows:
            writer.writerow([
                r['customer_name'] or '', r['order_number'], str(r['order_date']),
                r['status_display'], r['item_name'], r['sku'] or '',
                f"{float(r['quantity'] or 0):.2f}", r['uom'] or 'pcs',
                f"{float(r['unit_price'] or 0):.2f}", f"{float(r['amount'] or 0):.2f}"
            ])
        filename = f"Customer_Order_History_{start_date}_{end_date}.csv"

    elif report_key == 'inventory-summary':
        writer.writerow(['Category', 'SKU', 'Item Name', 'Qty On Hand', 'Qty Reserved', 'Qty Available', 'UOM', 'Unit Cost ($)', 'Total Cost Value ($)'])
        loc_clause = ""
        inv_params = []
        base_where = ["p.is_active = TRUE"]
        if category_id and category_id != 'all' and str(category_id).isdigit():
            base_where.append("p.category_id = %s")
            inv_params.append(int(category_id))
        if location_id and location_id != 'all' and str(location_id).isdigit():
            loc_clause = "AND i.location_id = %s"
            inv_params.append(int(location_id))
        where_sql = " AND ".join(base_where)
        rows = query_all(f"""
            SELECT 
                p.sku, p.name as item_name,
                COALESCE(c.name, 'General') as category_name,
                COALESCE(SUM(i.quantity), 0) as on_hand,
                COALESCE(SUM(i.reserved_quantity), 0) as reserved_quantity,
                COALESCE(SUM(i.quantity - i.reserved_quantity), 0) as available_quantity,
                COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost,
                COALESCE(SUM(i.quantity), 0) * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as total_cost_value,
                p.uom
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN inventory i ON i.product_id = p.id {loc_clause}
            WHERE {where_sql}
            GROUP BY p.id, p.sku, p.name, c.name, p.average_cost, p.standard_cost, p.uom
            ORDER BY category_name ASC, p.name ASC
        """, tuple(inv_params))
        for r in rows:
            writer.writerow([
                r['category_name'], r['sku'], r['item_name'],
                f"{float(r['on_hand'] or 0):.2f}", f"{float(r['reserved_quantity'] or 0):.2f}",
                f"{float(r['available_quantity'] or 0):.2f}", r['uom'] or 'pcs',
                f"{float(r['unit_cost'] or 0):.2f}", f"{float(r['total_cost_value'] or 0):.2f}"
            ])
        filename = "Inventory_Summary.csv"

    elif report_key == 'inventory-valuation':
        writer.writerow(['SKU', 'Item Name', 'Category', 'Warehouse', 'On Hand', 'UOM', 'Unit Cost ($)', 'Asset Value ($)', 'Retail Price ($)', 'Retail Value ($)'])
        rows = query_all("""
            SELECT 
                p.sku, p.name as item_name, c.name as category_name, l.name as location_name,
                i.quantity, p.uom,
                COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost,
                (i.quantity * COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0)) as asset_value,
                p.default_price as retail_price,
                (i.quantity * p.default_price) as retail_value
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN locations l ON i.location_id = l.id
            WHERE p.is_active = TRUE AND i.quantity > 0
            ORDER BY asset_value DESC
        """)
        for r in rows:
            writer.writerow([r['sku'], r['item_name'], r['category_name'] or '', r['location_name'] or '', f"{float(r['quantity'] or 0):.2f}", r['uom'] or '', f"{float(r['unit_cost'] or 0):.2f}", f"{float(r['asset_value'] or 0):.2f}", f"{float(r['retail_price'] or 0):.2f}", f"{float(r['retail_value'] or 0):.2f}"])
        filename = "Inventory_Valuation.csv"

    elif report_key == 'purchase-order-summary':
        writer.writerow(['PO Number', 'Vendor', 'Order Date', 'Status', 'Total ($)', 'Paid ($)', 'Balance Due ($)'])
        rows = query_all("""
            SELECT po.order_number, v.name as vendor_name, po.order_date, po.status, po.total_amount, po.paid_amount, po.balance_due
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE po.order_date >= %s AND po.order_date <= %s
            ORDER BY po.order_date DESC
        """, (start_date, end_date))
        for r in rows:
            writer.writerow([r['order_number'], r['vendor_name'] or '', str(r['order_date']), r['status'], f"{float(r['total_amount'] or 0):.2f}", f"{float(r['paid_amount'] or 0):.2f}", f"{float(r['balance_due'] or 0):.2f}"])
        filename = f"Purchase_Order_Summary_{start_date}_{end_date}.csv"

    elif report_key == 'vendor-list':
        writer.writerow(['Vendor Name', 'Contact Name', 'Phone', 'Email', 'Address', 'City', 'Country'])
        rows = query_all("SELECT name, contact_name, phone, email, address1, city, country FROM vendors WHERE is_active = TRUE ORDER BY name")
        for r in rows:
            writer.writerow([r['name'], r['contact_name'], r['phone'], r['email'], r['address1'], r['city'], r['country']])
        filename = "Vendor_List.csv"

    elif report_key == 'customer-list':
        writer.writerow(['Customer Name', 'Contact Person', 'Phone', 'Email', 'Address', 'City', 'Balance ($)'])
        where_branch = "branch_id IS NULL" if branch_scope == 'main' else (f"branch_id = {int(branch_scope)}" if branch_scope.isdigit() else "1=1")
        rows = query_all(f"SELECT name, contact_name, phone, email, address1, city, balance FROM customers WHERE is_active = TRUE AND {where_branch} ORDER BY name")
        for r in rows:
            writer.writerow([r['name'], r['contact_name'], r['phone'], r['email'], r['address1'], r['city'], f"{float(r['balance'] or 0):.2f}"])
        filename = "Customer_List.csv"

    elif report_key == 'sales-order-summary':
        writer.writerow(['Order Number', 'Date', 'Customer', 'Status', 'Payment Status', 'Subtotal ($)', 'Total Amount ($)', 'Paid Amount ($)', 'Balance Due ($)'])
        where_branch = "so.branch_id IS NULL" if branch_scope == 'main' else (f"so.branch_id = {int(branch_scope)}" if branch_scope.isdigit() else "1=1")
        where_status = "1=1"
        if status == 'Paid':
            where_status = "so.payment_status = 'PAID'"
        elif status != 'All':
            where_status = f"so.status = '{status.upper()}'"
        rows = query_all(f"""
            SELECT so.order_number, so.order_date, c.name as customer_name, initcap(so.status) as status_display, initcap(so.payment_status) as payment_status_display,
                   so.subtotal, so.total_amount, so.paid_amount, so.balance_due
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.order_date >= %s AND so.order_date <= %s AND {where_status} AND {where_branch}
            ORDER BY so.order_date DESC, so.order_number DESC
        """, (start_date, end_date))
        for r in rows:
            writer.writerow([
                r['order_number'], str(r['order_date']), r['customer_name'] or '',
                r['status_display'], r['payment_status_display'],
                f"{float(r['subtotal'] or 0):.2f}", f"{float(r['total_amount'] or 0):.2f}",
                f"{float(r['paid_amount'] or 0):.2f}", f"{float(r['balance_due'] or 0):.2f}"
            ])
        filename = f"Sales_Order_Summary_{start_date}_{end_date}.csv"

    elif report_key == 'branch-sales-summary':
        costing_scheme_id_param = request.args.get('costing_scheme_id', '').strip()
        default_costing_scheme = query_one("SELECT id, name FROM pricing_schemes WHERE name ILIKE '%%Branch Costing%%' LIMIT 1")
        default_costing_scheme_id = default_costing_scheme['id'] if default_costing_scheme else 107
        try:
            costing_scheme_id = int(costing_scheme_id_param) if costing_scheme_id_param else default_costing_scheme_id
        except ValueError:
            costing_scheme_id = default_costing_scheme_id

        currency = request.args.get('currency', 'USD').strip().upper()
        if currency not in ['USD', 'KHR']:
            currency = 'USD'
        inv_set = query_one("SELECT khr_exchange_rate FROM invoice_settings LIMIT 1")
        khr_rate = float(inv_set.get('khr_exchange_rate') or 4100.0) if inv_set else 4100.0
        curr_mult = khr_rate if currency == 'KHR' else 1.0
        curr_sym = '៛' if currency == 'KHR' else '$'

        writer.writerow(['Category', 'Item SKU', 'Item Name', 'Quantity Sold', 'Packaging', f'Sale Price / Pcs ({curr_sym})', f'Branch Unit Cost ({curr_sym})', f'Total Sales ({curr_sym})', f'Total Branch Cost ({curr_sym})', f'Branch Profit ({curr_sym})', 'Margin %'])

        where_branch = "1=1"
        if branch_scope == 'main':
            where_branch = "so.branch_id IS NULL"
        elif branch_scope != 'all' and branch_scope.isdigit():
            where_branch = f"so.branch_id = {int(branch_scope)}"

        where_cat = f"p.category_id = {int(category_id)}" if (category_id and category_id.isdigit()) else "1=1"
        where_stat = "1=1"
        if status == 'Paid':
            where_stat = "so.payment_status = 'PAID'"
        elif status == 'Invoiced':
            where_stat = "so.status = 'INVOICED'"
        elif status == 'Open':
            where_stat = "so.status = 'OPEN'"

        cost_unit_expr = """
            CASE 
                WHEN pp.unit_price IS NOT NULL AND pp.unit_price > 0 AND p.sales_uom_ratio_std > 1 
                    THEN (pp.unit_price / p.sales_uom_ratio_std) 
                WHEN pp.unit_price IS NOT NULL AND pp.unit_price > 0 
                    THEN pp.unit_price 
                WHEN p.standard_cost IS NOT NULL AND p.standard_cost > 0 
                    THEN p.standard_cost 
                WHEN p.average_cost IS NOT NULL AND p.average_cost > 0 
                    THEN p.average_cost 
                ELSE 0 
            END
        """

        if sort_by in ['Order Number', 'SKU', 'Order Number / SKU']:
            sort_order = "p.sku ASC"
        elif sort_by in ['Item Name', 'Product Name', 'Name']:
            sort_order = "p.name ASC"
        elif sort_by == 'Category':
            sort_order = "c.name ASC, p.name ASC"
        elif sort_by in ['Quantity Sold', 'Quantity Sold (Pcs)', 'Quantity']:
            sort_order = "quantity_sold DESC"
        elif sort_by in ['Price / PCS', 'Price']:
            sort_order = "(SUM(sol.subtotal) / NULLIF(SUM(sol.quantity), 0)) DESC"
        elif sort_by in ['Total Cost', 'Branch Cost', 'Total Branch Cost']:
            sort_order = "total_branch_cost DESC"
        elif sort_by in ['Gross Profit', 'Profit', 'Gross Profit / Asset Value']:
            sort_order = "branch_profit DESC"
        else:
            sort_order = "sales_amount DESC"

        if group_by == 'Category':
            order_clause = f"COALESCE(c.name, 'General') ASC, {sort_order}"
        else:
            order_clause = sort_order

        rows = query_all(f"""
            SELECT 
                p.id, p.sku, p.name as item_name,
                COALESCE(c.name, 'General') as category_name,
                COALESCE(p.uom, 'pcs') as base_uom,
                COALESCE(p.sales_uom_ratio_std, 1.0) as pcs_per_case,
                SUM(sol.quantity) as quantity_sold,
                SUM(sol.subtotal) as sales_amount,
                {cost_unit_expr} as raw_branch_cost_pc,
                SUM(sol.quantity * ({cost_unit_expr})) as total_branch_cost,
                SUM(sol.subtotal) - SUM(sol.quantity * ({cost_unit_expr})) as branch_profit
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id AND pp.pricing_scheme_id = %s
            WHERE so.order_date >= %s AND so.order_date <= %s AND so.status != 'CANCELLED'
              AND {where_branch} AND {where_cat} AND {where_stat}
            GROUP BY p.id, p.sku, p.name, c.name, p.uom, p.sales_uom_ratio_std, pp.unit_price, p.standard_cost, p.average_cost
            ORDER BY {order_clause}
        """, (costing_scheme_id, start_date, end_date))

        for r in rows:
            qty_pcs = float(r['quantity_sold'] or 0)
            sales = float(r['sales_amount'] or 0) * curr_mult
            b_cost = float(r['raw_branch_cost_pc'] or 0) * curr_mult
            tot_cost = float(r['total_branch_cost'] or 0) * curr_mult
            profit = float(r['branch_profit'] or 0) * curr_mult
            price_pc = (sales / qty_pcs) if qty_pcs > 0 else 0.0
            m_pct = (profit / sales * 100.0) if sales > 0 else 0.0
            pcs_ratio = float(r['pcs_per_case'] or 1.0)
            pack_str = f"{pcs_ratio:.0f} pcs/cs" if pcs_ratio > 1 else "1 pc"

            price_pc_str = f"{price_pc:,.3f}" if currency == 'USD' else f"{price_pc:,.0f}"
            cost_pc_str = f"{b_cost:,.3f}" if currency == 'USD' else f"{b_cost:,.0f}"

            writer.writerow([
                r['category_name'],
                r['sku'],
                r['item_name'],
                f"{qty_pcs:.0f}",
                pack_str,
                price_pc_str,
                cost_pc_str,
                f"{sales:,.2f}" if currency == 'USD' else f"{sales:,.0f}",
                f"{tot_cost:,.2f}" if currency == 'USD' else f"{tot_cost:,.0f}",
                f"{profit:,.2f}" if currency == 'USD' else f"{profit:,.0f}",
                f"{m_pct:.1f}%"
            ])
        filename = f"Branch_Sales_Summary_{start_date}_{end_date}.csv"

    else:
        writer.writerow(['Order Number', 'Date', 'Customer', 'Status', 'Total Amount ($)'])
        rows = query_all("""
            SELECT so.order_number, so.order_date, c.name as customer_name, so.status, so.total_amount
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            ORDER BY so.order_date DESC
        """)
        for r in rows:
            writer.writerow([r['order_number'], str(r['order_date']), r['customer_name'] or '', r['status'], f"{float(r['total_amount'] or 0):.2f}"])
        filename = f"{report_key}.csv"

    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

# -------------------------------------------------------------------------
# Legacy / Existing Endpoints (Preserved for tests)
# -------------------------------------------------------------------------
@reports_bp.route('/reports/valuation')
def valuation_report():
    category_id = request.args.get('category_id')
    location_id = request.args.get('location_id')

    where_clauses = ["p.is_active = TRUE", "i.quantity > 0"]
    params = []

    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(int(category_id))

    if location_id:
        where_clauses.append("i.location_id = %s")
        params.append(int(location_id))

    where_sql = " AND ".join(where_clauses)

    rows = query_all(f"""
        SELECT 
            p.id, p.sku, p.name, p.uom,
            c.name as category_name,
            l.name as location_name,
            (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END) as unit_cost,
            p.default_price as selling_price,
            i.quantity,
            (i.quantity * (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END)) as total_cost_value,
            (i.quantity * p.default_price) as total_retail_value
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN locations l ON i.location_id = l.id
        WHERE {where_sql}
        ORDER BY total_cost_value DESC
    """, tuple(params))

    summary = query_one(f"""
        SELECT 
            COUNT(DISTINCT p.id) as total_items,
            COALESCE(SUM(i.quantity), 0) as total_units,
            COALESCE(SUM(i.quantity * (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END)), 0) as total_asset_value,
            COALESCE(SUM(i.quantity * p.default_price), 0) as total_retail_value
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        WHERE {where_sql}
    """, tuple(params))

    categories = query_all("SELECT id, name FROM categories WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")

    return render_template('reports/valuation.html',
                           rows=rows,
                           summary=summary,
                           categories=categories,
                           locations=locations,
                           category_id=category_id,
                           location_id=location_id)

@reports_bp.route('/reports/sales')
def sales_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    where_clauses = ["so.status != 'CANCELLED'"]
    params = []

    if date_from:
        where_clauses.append("so.order_date >= %s")
        params.append(date_from)
    if date_to:
        where_clauses.append("so.order_date <= %s")
        params.append(date_to)

    where_sql = " AND ".join(where_clauses)

    line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
    summary = query_one(f"""
        WITH filtered_so AS (
            SELECT id, total_amount FROM sales_orders so WHERE {where_sql}
        ),
        lines_cogs AS (
            SELECT COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
            FROM sales_order_lines sol
            JOIN products p ON sol.product_id = p.id
            JOIN filtered_so ON sol.sales_order_id = filtered_so.id
        )
        SELECT 
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            (SELECT total_cogs FROM lines_cogs) as total_cogs,
            (COALESCE(SUM(total_amount), 0) - (SELECT total_cogs FROM lines_cogs)) as gross_profit
        FROM filtered_so;
    """, tuple(params))

    product_breakdown = query_all(f"""
        SELECT 
            p.id, p.sku, p.name,
            SUM(sol.quantity) as units_sold,
            SUM(sol.subtotal) as revenue,
            SUM({line_cogs_sql}) as cogs,
            SUM(sol.subtotal - ({line_cogs_sql})) as gross_profit,
            CASE WHEN SUM(sol.subtotal) > 0 
                 THEN ROUND(((SUM(sol.subtotal - ({line_cogs_sql})) / SUM(sol.subtotal)) * 100), 2)
                 ELSE 0 END as margin_percent
        FROM sales_order_lines sol
        JOIN sales_orders so ON sol.sales_order_id = so.id
        JOIN products p ON sol.product_id = p.id
        WHERE {where_sql}
        GROUP BY p.id, p.sku, p.name
        ORDER BY revenue DESC
        LIMIT 50
    """, tuple(params))

    return render_template('reports/sales_analytics.html',
                           summary=summary,
                           product_breakdown=product_breakdown,
                           date_from=date_from,
                           date_to=date_to)

@reports_bp.route('/reports/movement-log')
def movement_log():
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page
    movement_type = request.args.get('type', '')

    where_clauses = ["1=1"]
    params = []
    if movement_type:
        where_clauses.append("il.movement_type = %s")
        params.append(movement_type)

    where_sql = " AND ".join(where_clauses)

    count = query_one(f"SELECT COUNT(*) as cnt FROM inventory_logs il WHERE {where_sql}", tuple(params))['cnt']
    total_pages = max(1, (count + per_page - 1) // per_page)

    query_params = params.copy()
    query_params.extend([per_page, offset])

    logs = query_all(f"""
        SELECT 
            il.*,
            p.name as product_name,
            p.sku as product_sku,
            fl.name as from_location_name,
            tl.name as to_location_name
        FROM inventory_logs il
        JOIN products p ON il.product_id = p.id
        LEFT JOIN locations fl ON il.from_location_id = fl.id
        LEFT JOIN locations tl ON il.to_location_id = tl.id
        WHERE {where_sql}
        ORDER BY il.created_at DESC, il.id DESC
        LIMIT %s OFFSET %s
    """, tuple(query_params))

    return render_template('reports/movement_log.html',
                           logs=logs,
                           movement_type=movement_type,
                           page=page,
                           total_pages=total_pages,
                           total_count=count)

@reports_bp.route('/reports/export/valuation')
def export_valuation_csv():
    rows = query_all("""
        SELECT 
            p.sku, p.name, c.name as category, l.name as warehouse,
            i.quantity,
            (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END) as unit_cost,
            (i.quantity * (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END)) as asset_value,
            p.default_price, (i.quantity * p.default_price) as retail_value
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN locations l ON i.location_id = l.id
        WHERE p.is_active = TRUE AND i.quantity > 0 AND l.name NOT LIKE '<%%>'
        ORDER BY asset_value DESC
    """)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['SKU', 'Product Name', 'Category', 'Warehouse', 'Quantity', 'Unit Cost ($)', 'Asset Value ($)', 'Retail Price ($)', 'Retail Value ($)'])
    for r in rows:
        writer.writerow([r['sku'], r['name'], r['category'], r['warehouse'], r['quantity'], r['unit_cost'], r['asset_value'], r['default_price'], r['retail_value']])

    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=inflow_inventory_valuation.csv"}
    )
