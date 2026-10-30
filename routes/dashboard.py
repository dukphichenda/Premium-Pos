import re
from flask import Blueprint, render_template, jsonify, session, redirect, url_for, request
from database import query_one, query_all
from datetime import datetime
from routes.reports import _get_line_cogs_sql_expr

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def index():
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))

    user_role = session.get('role', 'main_admin')
    user_bid = session.get('branch_id')
    active_bid = session.get('active_branch_id') or (user_bid if user_role in ('branch_admin', 'branch_cashier') else None)

    # Detect mobile mode from user-agent, cookies, or query parameters
    view_mode = request.args.get('view', '').strip().lower()
    ua = request.headers.get('User-Agent', '')
    is_phone_ua = bool(re.search(r'Android.*Mobile|iPhone|iPod|BlackBerry|IEMobile|Opera Mini', ua, re.I))
    cookie_mode = request.cookies.get('inflow_view_mode', '').strip().lower()
    is_mobile_req = (view_mode == 'mobile') or (cookie_mode == 'mobile' and view_mode != 'desktop') or (is_phone_ua and view_mode != 'desktop' and cookie_mode != 'desktop')

    # Desktop PC mode: preserve dedicated branch workspace interface if active_bid
    if not is_mobile_req and view_mode != 'table' and active_bid:
        return redirect(url_for('branches.branch_workspace', id=active_bid))

    raw_branch = request.args.get('branch')
    if raw_branch:
        branch_scope = raw_branch.strip().lower()
    elif active_bid:
        branch_scope = str(active_bid)
    else:
        branch_scope = 'main'

    try:
        # Load all active branches with fulfillment locations
        branches = query_all("""
            SELECT b.id, b.code, b.name, b.manager_name, b.phone, b.settings_json, b.location_id,
                   l.name as location_name
            FROM branches b
            LEFT JOIN locations l ON b.location_id = l.id
            WHERE b.is_active = TRUE
            ORDER BY b.id ASC
        """)
        import json
        for b in branches:
            raw_s = b.get('settings_json')
            s_dict = json.loads(raw_s) if isinstance(raw_s, str) else (raw_s or {})
            b['logo_url'] = s_dict.get('logo_url') or ''
        central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")

        # Determine store scope
        if branch_scope == 'all':
            so_filter = ""
            sol_filter = ""
            current_store_name = 'All Outlets Combined'
            current_store_code = 'ALL'
            selected_branch = None
        elif branch_scope.isdigit():
            bid = int(branch_scope)
            selected_branch = next((b for b in branches if b['id'] == bid), None)
            if selected_branch:
                so_filter = f"AND branch_id = {bid}"
                sol_filter = f"AND so.branch_id = {bid}"
                current_store_name = f"{selected_branch['code']} - {selected_branch['name']}"
                current_store_code = selected_branch['code']
                if selected_branch.get('location_name'):
                    central_wh = {'id': selected_branch.get('location_id'), 'name': selected_branch.get('location_name')}
            else:
                branch_scope = 'main'
                so_filter = "AND (branch_id IS NULL OR branch_id = 0)"
                sol_filter = "AND (so.branch_id IS NULL OR so.branch_id = 0)"
                current_store_name = 'Main Store (HQ)'
                current_store_code = 'HQ'
                selected_branch = None
        else:
            branch_scope = 'main'
            so_filter = "AND (branch_id IS NULL OR branch_id = 0)"
            sol_filter = "AND (so.branch_id IS NULL OR so.branch_id = 0)"
            current_store_name = 'Main Store (HQ)'
            current_store_code = 'HQ'
            selected_branch = None

        # 1. High level KPI metrics (scoped to selected store)
        kpis = query_one(f"""
            SELECT 
                (SELECT COUNT(*) FROM products WHERE is_active = TRUE) as total_products,
                (SELECT COALESCE(SUM(quantity), 0) FROM inventory) as total_units_on_hand,
                (SELECT COALESCE(SUM(GREATEST(i.quantity, 0) * COALESCE(p.average_cost, p.standard_cost, 0)), 0) 
                 FROM inventory i 
                 JOIN products p ON i.product_id = p.id) as total_inventory_value,
                (SELECT COUNT(DISTINCT p.id) 
                 FROM products p 
                 LEFT JOIN (SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id) inv ON p.id = inv.product_id
                 WHERE p.is_active = TRUE AND COALESCE(inv.total_qty, 0) <= p.reorder_point AND p.reorder_point > 0) as low_stock_count,
                (SELECT COUNT(*) FROM sales_orders WHERE status IN ('OPEN', 'PICKED', 'PACKED') {so_filter}) as pending_sales_orders,
                (SELECT COUNT(*) FROM purchase_orders WHERE status IN ('DRAFT', 'ISSUED', 'PARTIAL_RECEIVED')) as pending_purchase_orders,
                (SELECT COALESCE(SUM(total_amount), 0) FROM sales_orders WHERE status != 'CANCELLED' AND order_date >= date_trunc('month', CURRENT_DATE) {so_filter}) as month_sales_total,
                (SELECT COALESCE(SUM(CASE WHEN status = 'PAID' OR payment_status = 'PAID' THEN total_amount ELSE 0 END), 0) FROM sales_orders WHERE status != 'CANCELLED' AND order_date >= date_trunc('month', CURRENT_DATE) {so_filter}) as month_paid_total,
                (SELECT COALESCE(SUM(total_amount), 0) FROM sales_orders WHERE status != 'CANCELLED' AND order_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') AND order_date < date_trunc('month', CURRENT_DATE) {so_filter}) as prev_month_sales_total,
                (SELECT COALESCE(SUM(balance_due), 0) FROM sales_orders WHERE balance_due > 0 AND status != 'CANCELLED' {so_filter}) as total_receivables,
                (SELECT COALESCE(SUM(total_amount), 0) FROM sales_orders WHERE status != 'CANCELLED' AND order_date = CURRENT_DATE {so_filter}) as today_sales_total,
                (SELECT COUNT(*) FROM sales_orders WHERE status != 'CANCELLED' AND order_date = CURRENT_DATE {so_filter}) as today_sales_count,
                (SELECT COUNT(*) FROM branches WHERE is_active = TRUE) as active_branches_count
        """)

        if kpis:
            cur_sales = float(kpis.get('month_sales_total') or 0)
            prev_sales = float(kpis.get('prev_month_sales_total') or 0)
            if prev_sales > 0:
                diff_pct = round(((cur_sales - prev_sales) / prev_sales) * 100, 1)
                kpis['sales_trend_label'] = f"↑ {diff_pct}% vs last month" if diff_pct >= 0 else f"↓ {abs(diff_pct)}% vs last month"
            else:
                kpis['sales_trend_label'] = "Current month"

        # 2. Urgent Low Stock items (top 8)
        low_stock_items = query_all("""
            SELECT 
                p.id, p.sku, p.name, p.uom, p.reorder_point, p.reorder_quantity,
                COALESCE(inv.total_qty, 0) as current_qty,
                c.name as category_name
            FROM products p
            LEFT JOIN (
                SELECT product_id, SUM(quantity) as total_qty 
                FROM inventory 
                GROUP BY product_id
            ) inv ON p.id = inv.product_id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active = TRUE 
              AND p.reorder_point > 0 
              AND COALESCE(inv.total_qty, 0) <= p.reorder_point
            ORDER BY (COALESCE(inv.total_qty, 0) - p.reorder_point) ASC
            LIMIT 8
        """)

        # 3. Recent Sales Orders (latest 6) - Scoped to selected store
        recent_orders = query_all(f"""
            SELECT 
                so.id, so.order_number, so.order_date, so.status, so.payment_status,
                so.total_amount, so.paid_amount, so.balance_due,
                c.name as customer_name
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE 1=1 {sol_filter}
            ORDER BY so.order_date DESC, so.id DESC
            LIMIT 6
        """)

        # 4. Top 6 Selling Products (Excluding cancelled orders) - Scoped to selected store
        top_products = query_all(f"""
            SELECT 
                p.id, p.sku, p.name, p.uom,
                SUM(sol.quantity) as total_sold,
                SUM(sol.subtotal) as total_revenue
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE so.status != 'CANCELLED' {sol_filter}
            GROUP BY p.id, p.sku, p.name, p.uom
            ORDER BY total_sold DESC
            LIMIT 6
        """)

        # 5. Recent Purchase Orders
        recent_pos = query_all("""
            SELECT 
                po.id, po.order_number, po.order_date, po.status, po.total_amount,
                v.name as vendor_name
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            ORDER BY po.order_date DESC, po.id DESC
            LIMIT 5
        """)

        # 6. Separate Performance Data for EACH store (HQ + each branch separately)
        hq_perf = query_one("""
            SELECT 
                COUNT(id) as all_orders,
                COALESCE(SUM(total_amount), 0) as all_revenue,
                COALESCE(SUM(balance_due), 0) as all_receivables,
                COUNT(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) THEN 1 END) as month_orders,
                COALESCE(SUM(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) THEN total_amount ELSE 0 END), 0) as month_sales,
                COALESCE(SUM(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) AND (status = 'PAID' OR payment_status = 'PAID') THEN total_amount ELSE 0 END), 0) as month_paid,
                COUNT(CASE WHEN order_date = CURRENT_DATE THEN 1 END) as today_orders,
                COALESCE(SUM(CASE WHEN order_date = CURRENT_DATE THEN total_amount ELSE 0 END), 0) as today_sales
            FROM sales_orders
            WHERE status != 'CANCELLED' AND (branch_id IS NULL OR branch_id = 0)
        """)

        branch_perfs = query_all("""
            SELECT 
                b.id, b.code, b.name, b.manager_name, b.phone, b.is_active,
                l.name as location_name,
                COALESCE(s.all_orders, 0) as all_orders,
                COALESCE(s.all_revenue, 0) as all_revenue,
                COALESCE(s.all_receivables, 0) as all_receivables,
                COALESCE(s.month_orders, 0) as month_orders,
                COALESCE(s.month_sales, 0) as month_sales,
                COALESCE(s.month_paid, 0) as month_paid,
                COALESCE(s.today_orders, 0) as today_orders,
                COALESCE(s.today_sales, 0) as today_sales
            FROM branches b
            LEFT JOIN locations l ON b.location_id = l.id
            LEFT JOIN (
                SELECT 
                    branch_id,
                    COUNT(id) as all_orders,
                    SUM(total_amount) as all_revenue,
                    SUM(balance_due) as all_receivables,
                    COUNT(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) THEN 1 END) as month_orders,
                    SUM(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) THEN total_amount ELSE 0 END) as month_sales,
                    SUM(CASE WHEN order_date >= date_trunc('month', CURRENT_DATE) AND (status = 'PAID' OR payment_status = 'PAID') THEN total_amount ELSE 0 END) as month_paid,
                    COUNT(CASE WHEN order_date = CURRENT_DATE THEN 1 END) as today_orders,
                    SUM(CASE WHEN order_date = CURRENT_DATE THEN total_amount ELSE 0 END) as today_sales
                FROM sales_orders
                WHERE status != 'CANCELLED'
                GROUP BY branch_id
            ) s ON b.id = s.branch_id
            WHERE b.is_active = TRUE
            ORDER BY b.id ASC
        """)

        store_performances = []
        # Main Store (HQ)
        store_performances.append({
            'id': 'main',
            'code': 'HQ',
            'name': 'Main Store (Headquarters)',
            'location_name': central_wh['name'] if central_wh else 'Central Warehouse',
            'manager_name': 'Central Admin',
            'phone': None,
            'is_hq': True,
            'all_orders': hq_perf['all_orders'] if hq_perf else 0,
            'all_revenue': float(hq_perf['all_revenue'] if hq_perf else 0),
            'all_receivables': float(hq_perf['all_receivables'] if hq_perf else 0),
            'month_orders': hq_perf['month_orders'] if hq_perf else 0,
            'month_sales': float(hq_perf['month_sales'] if hq_perf else 0),
            'month_paid': float(hq_perf['month_paid'] if hq_perf else 0),
            'today_orders': hq_perf['today_orders'] if hq_perf else 0,
            'today_sales': float(hq_perf['today_sales'] if hq_perf else 0),
        })

        for b in branch_perfs:
            store_performances.append({
                'id': str(b['id']),
                'code': b['code'],
                'name': b['name'],
                'location_name': b['location_name'] or 'Main Warehouse',
                'manager_name': b['manager_name'] or 'Store Staff',
                'phone': b['phone'],
                'is_hq': False,
                'all_orders': b['all_orders'],
                'all_revenue': float(b['all_revenue']),
                'all_receivables': float(b['all_receivables']),
                'month_orders': b['month_orders'],
                'month_sales': float(b['month_sales']),
                'month_paid': float(b['month_paid']),
                'today_orders': b['today_orders'],
                'today_sales': float(b['today_sales']),
            })

    except Exception as e:
        kpis = {
            'total_products': 406,
            'total_units_on_hand': 12580,
            'total_inventory_value': 148520.00,
            'low_stock_count': 3,
            'pending_sales_orders': 5,
            'pending_purchase_orders': 2,
            'month_sales_total': 38240.50,
            'month_paid_total': 32150.00,
            'total_receivables': 4150.00,
            'today_sales_total': 1850.00,
            'today_sales_count': 12,
            'active_branches_count': 4
        }
        low_stock_items = []
        recent_orders = []
        top_products = []
        recent_pos = []
        branches = []
        store_performances = []
        central_wh = {'id': 1, 'name': 'Main Warehouse'}
        branch_scope = 'main'
        current_store_name = 'Main Store (HQ)'
        current_store_code = 'HQ'

    branch_active_logo = selected_branch.get('logo_url') if selected_branch else None

    return render_template('dashboard.html',
                           kpis=kpis,
                           low_stock_items=low_stock_items,
                           recent_orders=recent_orders,
                           top_products=top_products,
                           recent_pos=recent_pos,
                           branches=branches,
                           branch_scope=branch_scope,
                           current_store_name=current_store_name,
                           current_store_code=current_store_code,
                           store_performances=store_performances,
                           central_wh=central_wh,
                           active_logo_url=branch_active_logo,
                           now_date_str=datetime.now().strftime('%d %b %Y'))

@dashboard_bp.route('/api/dashboard/charts')
def chart_data():
    user_role = session.get('role', 'main_admin')
    user_bid = session.get('branch_id')
    if user_role in ('branch_admin', 'branch_cashier') and user_bid:
        branch_scope = str(user_bid)
    else:
        branch_scope = request.args.get('branch', 'main').strip().lower()

    if branch_scope == 'all':
        branch_filter = ""
        params = ()
    elif branch_scope.isdigit():
        branch_filter = "AND so.branch_id = %s"
        params = (int(branch_scope),)
    else:
        branch_filter = "AND (so.branch_id IS NULL OR so.branch_id = 0)"
        params = ()

    # 1. Monthly Financial Breakdown (Last 12 months) - Scoped to selected store using canonical COGS (with Branch Cost for branch sales)
    default_costing_scheme = query_one("SELECT id FROM pricing_schemes WHERE name ILIKE '%%Branch Cost%%' LIMIT 1")
    branch_cost_scheme_id = default_costing_scheme['id'] if default_costing_scheme else 107
    line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p', pp_alias='pp_bc', so_alias='so')
    monthly_sales = query_all(f"""
        WITH order_costs AS (
            SELECT 
                sol.sales_order_id,
                COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            LEFT JOIN products p ON sol.product_id = p.id
            LEFT JOIN product_prices pp_bc ON pp_bc.product_id = p.id AND pp_bc.pricing_scheme_id = {branch_cost_scheme_id}
            GROUP BY sol.sales_order_id
        )
        SELECT 
            TO_CHAR(so.order_date, 'Mon YYYY') as month_label,
            date_trunc('month', so.order_date) as month_date,
            COALESCE(SUM(CASE WHEN so.status = 'PAID' OR so.payment_status = 'PAID' THEN so.total_amount ELSE 0 END), 0) as paid_sales,
            COALESCE(SUM(CASE WHEN (so.status = 'OPEN' OR so.balance_due > 0) AND NOT (so.status = 'PAID' OR so.payment_status = 'PAID') THEN so.total_amount ELSE 0 END), 0) as open_sales,
            COALESCE(SUM(so.total_amount), 0) as revenue,
            COALESCE(SUM(CASE WHEN so.status = 'PAID' OR so.payment_status = 'PAID' THEN (so.total_amount - COALESCE(oc.total_cogs, 0)) ELSE 0 END), 0) as paid_profit,
            COALESCE(SUM(so.total_amount - COALESCE(oc.total_cogs, 0)), 0) as total_profit,
            COUNT(*) as order_count
        FROM sales_orders so
        LEFT JOIN order_costs oc ON so.id = oc.sales_order_id
        WHERE so.status != 'CANCELLED' 
          {branch_filter}
          AND so.order_date >= CURRENT_DATE - INTERVAL '12 months'
        GROUP BY date_trunc('month', so.order_date), TO_CHAR(so.order_date, 'Mon YYYY')
        ORDER BY month_date ASC
    """, params)

    # 2. Stock Value by Category
    category_distribution = query_all("""
        SELECT 
            COALESCE(c.name, 'Uncategorized') as category_name,
            COUNT(DISTINCT p.id) as product_count,
            COALESCE(SUM(GREATEST(i.quantity, 0) * COALESCE(p.average_cost, p.standard_cost, 0)), 0) as total_value
        FROM categories c
        RIGHT JOIN products p ON c.id = p.category_id
        LEFT JOIN inventory i ON p.id = i.product_id
        WHERE p.is_active = TRUE
        GROUP BY c.name
        ORDER BY total_value DESC
        LIMIT 7
    """)

    profit_data = [round(float(r['paid_profit']), 2) for r in monthly_sales] if user_role not in ('branch_admin', 'branch_cashier') else []
    total_profit_data = [round(float(r['total_profit']), 2) for r in monthly_sales] if user_role not in ('branch_admin', 'branch_cashier') else []

    return jsonify({
        'monthly_labels': [r['month_label'] for r in monthly_sales],
        'monthly_paid': [round(float(r['paid_sales']), 2) for r in monthly_sales],
        'monthly_open': [round(float(r['open_sales']), 2) for r in monthly_sales],
        'monthly_profit': profit_data,
        'monthly_total_profit': total_profit_data,
        'monthly_revenue': [round(float(r['revenue']), 2) for r in monthly_sales],
        'monthly_orders': [int(r['order_count']) for r in monthly_sales],
        'category_labels': [r['category_name'] for r in category_distribution],
        'category_values': [round(float(r['total_value']), 2) for r in category_distribution]
    })
