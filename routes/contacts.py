from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, Response
from database import query_one, query_all, execute, execute_returning_id
import re
import csv
import io
from services.csv_exchange import resolve_customer_phone_and_name

contacts_bp = Blueprint('contacts', __name__)

def _is_main_admin():
    return session.get('role') == 'main_admin'

def _get_user_branch_id():
    if _is_main_admin():
        return None
    bid = session.get('branch_id') or session.get('active_branch_id')
    if bid and str(bid).isdigit():
        return int(bid)
    return None

def _check_customer_branch_access(customer):
    """
    Main store HQ admin has unrestricted rights across all customers.
    Branch users are permitted to view and edit customers belonging to their own branch.
    """
    if _is_main_admin():
        return True
    user_bid = _get_user_branch_id()
    cust_bid = customer.get('branch_id')
    if user_bid is None:
        return cust_bid is None
    if cust_bid is None:
        return False
    return int(cust_bid) == user_bid

def _get_sidebar_customers(search_name='', search_contact='', search_phone='', search_address='', branch_param=None):
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()
    
    where = ["c.is_active = TRUE"]
    params = []
    
    if not is_main_admin:
        if user_bid is not None:
            where.append("c.branch_id = %s")
            params.append(user_bid)
        else:
            where.append("1=0")
    else:
        raw_b = branch_param or request.args.get('branch')
        if raw_b and str(raw_b).isdigit():
            where.append("c.branch_id = %s")
            params.append(int(raw_b))
        elif raw_b == 'main':
            where.append("c.branch_id IS NULL")

    if search_name:
        where.append("c.name ILIKE %s")
        params.append(f"%{search_name}%")
    if search_contact:
        where.append("c.contact_name ILIKE %s")
        params.append(f"%{search_contact}%")
    if search_phone:
        where.append("c.phone ILIKE %s")
        params.append(f"%{search_phone}%")
    if search_address:
        where.append("(c.address1 ILIKE %s OR c.billing_address ILIKE %s OR c.shipping_address ILIKE %s)")
        params.extend([f"%{search_address}%", f"%{search_address}%", f"%{search_address}%"])

    sql = f"""
        SELECT 
            c.id, c.name, c.contact_name, c.phone, c.email, c.address1, c.billing_address, c.shipping_address, c.branch_id,
            c.city, c.discount_percent, ps.name as pricing_scheme_name,
            b.name as branch_name, b.code as branch_code,
            COALESCE(SUM(so.balance_due), 0) as open_balance,
            COALESCE(SUM(so.total_amount), 0) as total_spent,
            COUNT(so.id) as order_count
        FROM customers c
        LEFT JOIN branches b ON c.branch_id = b.id
        LEFT JOIN pricing_schemes ps ON c.default_pricing_scheme_id = ps.id
        LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
        WHERE {' AND '.join(where)}
        GROUP BY c.id, ps.name, b.name, b.code
        ORDER BY c.name ASC
        LIMIT 10000
    """
    return query_all(sql, tuple(params))

def _get_customer_full_data(customer_id, user_bid=None, is_main_admin=False):
    customer = query_one("""
        SELECT c.*, 
               b.name as branch_name, b.code as branch_code,
               ps.name as pricing_scheme_name,
               COALESCE(NULLIF(c.shipping_address, ''), NULLIF(c.address1, ''), NULLIF(c.billing_address, ''), NULLIF(c.address2, ''), '') as display_address,
               COALESCE((SELECT SUM(balance_due) FROM sales_orders WHERE customer_id = c.id AND status != 'CANCELLED'), 0) as balance,
               COALESCE((SELECT SUM(total_amount) FROM sales_orders WHERE customer_id = c.id AND status != 'CANCELLED'), 0) as total_spent,
               COALESCE((SELECT COUNT(*) FROM sales_orders WHERE customer_id = c.id AND status != 'CANCELLED'), 0) as order_count
        FROM customers c
        LEFT JOIN branches b ON c.branch_id = b.id
        LEFT JOIN pricing_schemes ps ON c.default_pricing_scheme_id = ps.id
        WHERE c.id = %s
    """, (customer_id,))
    
    if not customer:
        return None
        
    if not is_main_admin:
        cust_bid = customer.get('branch_id')
        if user_bid is None and cust_bid is not None:
            return None
        if user_bid is not None and (cust_bid is None or int(cust_bid) != user_bid):
            return None

    branch_cond = ""
    order_params = [customer_id]
    if not is_main_admin and user_bid:
        branch_cond = " AND so.branch_id = %s"
        order_params.append(user_bid)

    orders = query_all(f"""
        SELECT so.id, so.order_number, so.order_date, so.status, so.payment_status,
               so.total_amount, so.paid_amount, so.balance_due, so.notes,
               l.name as location_name,
               (
                   SELECT STRING_AGG(COALESCE(sub.p_name, sub.description, 'Item') || ' (' || sub.quantity || ')', ', ')
                   FROM (
                       SELECT sol.description, sol.quantity, p.name as p_name
                       FROM sales_order_lines sol
                       LEFT JOIN products p ON sol.product_id = p.id
                       WHERE sol.sales_order_id = so.id
                       LIMIT 4
                   ) sub
               ) as items_summary,
               (SELECT SUM(quantity) FROM sales_order_lines WHERE sales_order_id = so.id) as total_qty
        FROM sales_orders so
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE so.customer_id = %s {branch_cond}
        ORDER BY so.order_date DESC, so.id DESC
        LIMIT 100
    """, tuple(order_params))

    stats_row = query_one(f"""
        SELECT 
            COUNT(*) as total_orders,
            COALESCE(SUM(total_amount), 0) as total_spent,
            COALESCE(SUM(balance_due), 0) as open_balance,
            COUNT(CASE WHEN balance_due <= 0.0001 AND status != 'CANCELLED' THEN 1 END) as paid_orders,
            COUNT(CASE WHEN balance_due > 0.0001 AND status != 'CANCELLED' THEN 1 END) as unpaid_orders
        FROM sales_orders so
        WHERE so.customer_id = %s AND so.status != 'CANCELLED' {branch_cond}
    """, tuple(order_params)) or {
        'total_orders': 0,
        'total_spent': 0,
        'open_balance': 0,
        'paid_orders': 0,
        'unpaid_orders': 0
    }

    return {
        'customer': customer,
        'orders': orders,
        'stats': stats_row
    }

@contacts_bp.route('/customers')
def list_customers(selected_id_override=None):
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    page = int(request.args.get('page', 1))
    per_page_raw = request.args.get('per_page', 'all').strip().lower()
    
    search = request.args.get('search', '').strip()
    search_name = request.args.get('search_name', '').strip()
    op_name = request.args.get('op_name', '-').strip()
    search_contact = request.args.get('search_contact', '').strip()
    op_contact = request.args.get('op_contact', '-').strip()
    search_phone = request.args.get('search_phone', '').strip()
    op_phone = request.args.get('op_phone', '-').strip()
    search_address = request.args.get('search_address', '').strip()
    op_address = request.args.get('op_address', '-').strip()
    with_balance = request.args.get('with_balance', '').strip()
    scheme_filter = request.args.get('scheme_id', '').strip()

    sort_by = request.args.get('sort_by', 'name').strip().lower()
    sort_dir = request.args.get('sort_dir', 'asc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'asc'

    where_clauses = ["c.is_active = TRUE"]
    params = []

    # Branch Isolation: Branch users can ONLY view their own branch!
    # HQ (main_admin) can see all, or filter by Main Store (main) or specific branch ID.
    if not is_main_admin:
        if user_bid is not None:
            where_clauses.append("c.branch_id = %s")
            params.append(user_bid)
        else:
            where_clauses.append("1=0")
        current_branch_param = str(user_bid or 'main')
        branches = []
    else:
        branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")
        raw_branch = request.args.get('branch')
        if raw_branch is None and session.get('active_branch_id'):
            raw_branch = str(session.get('active_branch_id'))
        raw_branch = (raw_branch or '').strip().lower()
        if not raw_branch or raw_branch == 'all':
            current_branch_param = 'all'  # HQ sees all customers across all branches by default
        elif raw_branch == 'main':
            where_clauses.append("c.branch_id IS NULL")
            current_branch_param = 'main'
        elif raw_branch.isdigit():
            where_clauses.append("c.branch_id = %s")
            params.append(int(raw_branch))
            current_branch_param = raw_branch
        else:
            current_branch_param = 'all'

    def _apply_op(field, val, op):
        if op in ('=', 'exact'):
            return f"LOWER({field}) = LOWER(%s)", val
        elif op in ('^', 'starts'):
            return f"{field} ILIKE %s", f"{val}%"
        else:  # default contains '-'
            return f"{field} ILIKE %s", f"%{val}%"

    if search:
        where_clauses.append("(c.name ILIKE %s OR c.phone ILIKE %s OR c.contact_name ILIKE %s OR c.email ILIKE %s OR c.city ILIKE %s OR c.billing_address ILIKE %s OR c.address1 ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp, sp, sp, sp, sp])

    if search_name:
        clause, p = _apply_op("c.name", search_name, op_name)
        where_clauses.append(clause)
        params.append(p)

    if search_contact:
        clause, p = _apply_op("c.contact_name", search_contact, op_contact)
        where_clauses.append(clause)
        params.append(p)

    if search_phone:
        clause, p = _apply_op("c.phone", search_phone, op_phone)
        where_clauses.append(clause)
        params.append(p)

    if search_address:
        clause, p = _apply_op("COALESCE(NULLIF(c.address1, ''), c.billing_address, '')", search_address, op_address)
        where_clauses.append(clause)
        params.append(p)

    if scheme_filter and scheme_filter.isdigit():
        where_clauses.append("c.default_pricing_scheme_id = %s")
        params.append(int(scheme_filter))

    having_clauses = []
    having_params = []
    if with_balance == '1':
        having_clauses.append("COALESCE(SUM(so.balance_due), 0) > 0")

    where_sql = " AND ".join(where_clauses)
    having_sql = f"HAVING {' AND '.join(having_clauses)}" if having_clauses else ""

    # Sort map
    sort_cols = {
        'name': 'c.name',
        'contact': 'c.contact_name',
        'phone': 'c.phone',
        'email': 'c.email',
        'website': 'c.website',
        'address1': 'c.address1',
        'address2': 'c.address2',
        'city': 'c.city',
        'state': 'c.state',
        'postal_code': 'c.postal_code',
        'country': 'c.country',
        'pricing': 'pricing_scheme_name',
        'discount': 'c.discount_percent',
        'branch': 'branch_name',
        'balance': 'open_balance',
        'orders': 'order_count',
        'spent': 'total_spent'
    }
    order_col = sort_cols.get(sort_by, 'c.name')
    order_clause = f"ORDER BY {order_col} {sort_dir.upper()} NULLS LAST"

    # Count query
    if having_clauses:
        count_sql = f"""
            SELECT COUNT(*) as cnt FROM (
                SELECT c.id
                FROM customers c
                LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
                WHERE {where_sql}
                GROUP BY c.id
                {having_sql}
            ) sub
        """
        count_params = params + having_params
    else:
        count_sql = f"SELECT COUNT(*) as cnt FROM customers c WHERE {where_sql}"
        count_params = params

    total_count = query_one(count_sql, tuple(count_params))['cnt']
    
    if per_page_raw in ('all', ''):
        per_page = max(1, total_count)
        page = 1
        offset = 0
        total_pages = 1
    else:
        try:
            per_page = max(10, min(10000, int(per_page_raw)))
        except ValueError:
            per_page = max(1, total_count)
        offset = (page - 1) * per_page
        total_pages = max(1, (total_count + per_page - 1) // per_page)

    list_sql = f"""
        SELECT 
            c.*,
            b.name as branch_name,
            b.code as branch_code,
            ps.name as pricing_scheme_name,
            COUNT(so.id) as order_count,
            COALESCE(SUM(so.total_amount), 0) as total_spent,
            COALESCE(SUM(so.balance_due), 0) as open_balance
        FROM customers c
        LEFT JOIN branches b ON c.branch_id = b.id
        LEFT JOIN pricing_schemes ps ON c.default_pricing_scheme_id = ps.id
        LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
        WHERE {where_sql}
        GROUP BY c.id, b.name, b.code, ps.name
        {having_sql}
        {order_clause}
        LIMIT %s OFFSET %s
    """
    rows_params = params + having_params + [per_page, offset]
    customers = query_all(list_sql, tuple(rows_params))

    # Calculate summary aggregate stats
    summary_stats = query_one(f"""
        SELECT 
            COUNT(DISTINCT c.id) as total_customers,
            COALESCE(SUM(so.balance_due), 0) as total_receivables,
            COALESCE(SUM(so.total_amount), 0) as total_revenue
        FROM customers c
        LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
        WHERE {where_sql}
    """, tuple(params)) or {'total_customers': total_count, 'total_receivables': 0, 'total_revenue': 0}

    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")

    # JSON response support for live AJAX search / drawer refresh
    if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.args.get('ajax') == '1':
        return jsonify({
            'success': True,
            'total_count': total_count,
            'page': page,
            'total_pages': total_pages,
            'customers': [{
                'id': c['id'],
                'name': c['name'],
                'contact_name': c['contact_name'] or '',
                'phone': c['phone'] or '',
                'email': c['email'] or '',
                'website': c['website'] or '',
                'address1': c['address1'] or '',
                'address2': c['address2'] or '',
                'city': c['city'] or '',
                'state': c['state'] or '',
                'postal_code': c['postal_code'] or '',
                'country': c['country'] or '',
                'pricing_scheme_name': c['pricing_scheme_name'] or 'Retail 1',
                'discount_percent': float(c['discount_percent'] or 0),
                'open_balance': float(c['open_balance'] or 0),
                'order_count': c['order_count'],
                'branch_name': c['branch_name'] or '',
                'branch_code': c['branch_code'] or ''
            } for c in customers]
        })

    # Determine which customer is selected for the modern split-view panel
    selected_id_param = selected_id_override or request.args.get('selected_id') or request.args.get('id')
    selected_id = None
    if selected_id_param and str(selected_id_param).isdigit():
        selected_id = int(selected_id_param)
    elif customers:
        selected_id = customers[0]['id']

    selected_customer = None
    selected_orders = []
    selected_stats = {'total_orders': 0, 'total_spent': 0, 'open_balance': 0, 'paid_orders': 0, 'unpaid_orders': 0}

    if selected_id:
        cust_full = _get_customer_full_data(selected_id, user_bid, is_main_admin)
        if cust_full:
            selected_customer = cust_full['customer']
            selected_orders = cust_full['orders']
            selected_stats = cust_full['stats']
            # If the selected customer is not in the currently paged/filtered list, prepend it so the card is present
            if not any(c['id'] == selected_id for c in customers):
                customers.insert(0, {
                    'id': selected_customer['id'],
                    'name': selected_customer['name'],
                    'contact_name': selected_customer['contact_name'] or '',
                    'phone': selected_customer['phone'] or '',
                    'email': selected_customer['email'] or '',
                    'city': selected_customer['city'] or '',
                    'address1': selected_customer['address1'] or '',
                    'billing_address': selected_customer['billing_address'] or '',
                    'shipping_address': selected_customer['shipping_address'] or '',
                    'open_balance': float(selected_customer['balance'] or 0),
                    'total_spent': float(selected_customer['total_spent'] or 0),
                    'order_count': int(selected_customer['order_count'] or 0),
                    'branch_id': selected_customer.get('branch_id'),
                    'branch_name': selected_customer.get('branch_name') or '',
                    'branch_code': selected_customer.get('branch_code') or ''
                })
        elif customers:
            fallback_full = _get_customer_full_data(customers[0]['id'], user_bid, is_main_admin)
            if fallback_full:
                selected_id = customers[0]['id']
                selected_customer = fallback_full['customer']
                selected_orders = fallback_full['orders']
                selected_stats = fallback_full['stats']

    return render_template('contacts/customers.html',
                           customers=customers,
                           selected_id=selected_id,
                           selected_customer=selected_customer,
                           selected_orders=selected_orders,
                           selected_stats=selected_stats,
                           search=search,
                           search_name=search_name,
                           op_name=op_name,
                           search_contact=search_contact,
                           op_contact=op_contact,
                           search_phone=search_phone,
                           op_phone=op_phone,
                           search_address=search_address,
                           op_address=op_address,
                           with_balance=with_balance,
                           scheme_filter=scheme_filter,
                           sort_by=sort_by,
                           sort_dir=sort_dir,
                           page=page,
                           per_page=per_page,
                           per_page_raw=per_page_raw,
                           total_count=total_count,
                           total_pages=total_pages,
                           summary_stats=summary_stats,
                           pricing_schemes=pricing_schemes,
                           branches=branches,
                           current_branch_param=current_branch_param,
                           is_main_admin=is_main_admin)

@contacts_bp.route('/customers/new')
def new_customer():
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")
    branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC") if is_main_admin else []
    search_name = request.args.get('search_name', '').strip()
    search_contact = request.args.get('search_contact', '').strip()
    search_phone = request.args.get('search_phone', '').strip()
    search_address = request.args.get('search_address', '').strip()
    sidebar_customers = _get_sidebar_customers(search_name, search_contact, search_phone, search_address)
    
    customer = {
        'id': 0,
        'name': '',
        'balance': 0.0,
        'contact_name': '',
        'phone': '',
        'fax': '',
        'email': '',
        'website': '',
        'address1': '',
        'shipping_address': '',
        'billing_address': '',
        'default_pricing_scheme_id': 100,
        'discount_percent': 0.0,
        'payment_terms': 'Due on Receipt',
        'branch_id': user_bid if not is_main_admin else None
    }
    return render_template('contacts/customer_detail.html',
                           customer=customer,
                           orders=[],
                           pricing_schemes=pricing_schemes,
                           branches=branches,
                           is_main_admin=is_main_admin,
                           sidebar_customers=sidebar_customers,
                           is_new=True)

def _format_customer_api_payload(cust_data):
    if not cust_data:
        return {'success': False, 'message': 'Customer not found.'}
    c = cust_data.get('customer') or {}
    orders = cust_data.get('orders') or []
    stats = cust_data.get('stats') or {}
    return {
        'success': True,
        'customer': {
            'id': c.get('id'),
            'name': c.get('name') or '',
            'contact_name': c.get('contact_name') or '',
            'phone': c.get('phone') or '',
            'fax': c.get('fax') or '',
            'email': c.get('email') or '',
            'website': c.get('website') or '',
            'address1': c.get('address1') or '',
            'address2': c.get('address2') or '',
            'city': c.get('city') or '',
            'state': c.get('state') or '',
            'country': c.get('country') or 'Cambodia',
            'postal_code': c.get('postal_code') or '',
            'shipping_address': c.get('shipping_address') or c.get('address1') or '',
            'billing_address': c.get('billing_address') or c.get('address1') or '',
            'display_address': c.get('display_address') or '',
            'default_pricing_scheme_id': c.get('default_pricing_scheme_id') or 100,
            'pricing_scheme_name': c.get('pricing_scheme_name') or 'Retail 1',
            'discount_percent': float(c.get('discount_percent') or 0),
            'payment_terms': c.get('payment_terms') or 'Due on Receipt',
            'remarks': c.get('remarks') or '',
            'tax_number': c.get('tax_number') or '',
            'branch_id': c.get('branch_id'),
            'branch_name': c.get('branch_name') or '',
            'branch_code': c.get('branch_code') or '',
            'balance': float(c.get('balance') or 0),
            'total_spent': float(c.get('total_spent') or 0),
            'order_count': int(c.get('order_count') or 0),
            'created_at': str(c.get('created_at') or '')[:10],
            'updated_at': str(c.get('updated_at') or '')[:10]
        },
        'orders': [{
            'id': o.get('id'),
            'order_number': o.get('order_number') or '',
            'order_date': str(o.get('order_date') or '')[:10],
            'status': o.get('status') or '',
            'payment_status': o.get('payment_status') or '',
            'location_name': o.get('location_name') or 'Main Warehouse',
            'total_amount': float(o.get('total_amount') or 0),
            'paid_amount': float(o.get('paid_amount') or 0),
            'balance_due': float(o.get('balance_due') or 0),
            'items_summary': o.get('items_summary') or 'Products',
            'total_qty': float(o.get('total_qty') or 0),
            'notes': o.get('notes') or ''
        } for o in orders],
        'stats': {
            'total_orders': int(stats.get('total_orders') or 0),
            'total_spent': float(stats.get('total_spent') or 0),
            'open_balance': float(stats.get('open_balance') or 0),
            'paid_orders': int(stats.get('paid_orders') or 0),
            'unpaid_orders': int(stats.get('unpaid_orders') or 0)
        }
    }

@contacts_bp.route('/customers/<int:id>')
def detail_customer(id):
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    customer = query_one("SELECT * FROM customers WHERE id = %s", (id,))
    if not customer:
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == '1':
            return jsonify({'success': False, 'message': 'Customer not found.'}), 404
        flash("Customer not found.", "error")
        return redirect(url_for('contacts.list_customers'))

    if not _check_customer_branch_access(customer):
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == '1':
            return jsonify({'success': False, 'message': 'Access Denied: You do not have permission to view customers outside your branch'}), 403
        flash("🔒 Access Denied: You do not have permission to view customers outside your branch", "error")
        return redirect(url_for('contacts.list_customers'))

    # JSON response support for live AJAX selection without page reloads
    if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == '1':
        cust_data = _get_customer_full_data(id, user_bid, is_main_admin)
        if not cust_data:
            return jsonify({'success': False, 'message': 'Customer not found or access denied.'}), 404
        return jsonify(_format_customer_api_payload(cust_data))

    # Direct browser GET navigation: render list_customers with selected_id=id
    # so user gets full split-view interface with customer selected!
    return list_customers(selected_id_override=id)

@contacts_bp.route('/api/customers/<int:id>/details')
def api_customer_details(id):
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()
        cust_data = _get_customer_full_data(id, user_bid, is_main_admin)
        if not cust_data:
            return jsonify({'success': False, 'message': 'Customer not found or access denied.'}), 404
        return jsonify(_format_customer_api_payload(cust_data))
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error loading customer: {str(e)}"}), 500

@contacts_bp.route('/api/sales-orders/<int:id>/lines')
def api_sales_order_lines(id):
    lines = query_all("""
        SELECT sol.id, sol.line_num, sol.quantity, sol.unit_price, sol.discount_percent, sol.subtotal,
               COALESCE(p.name, sol.description, 'Item') as product_name,
               COALESCE(p.sku, '') as product_sku,
               COALESCE(p.image_url, '') as image_url
        FROM sales_order_lines sol
        LEFT JOIN products p ON sol.product_id = p.id
        WHERE sol.sales_order_id = %s
        ORDER BY sol.id ASC
    """, (id,))
    return jsonify({
        'success': True,
        'lines': [{
            'id': l['id'],
            'product_name': l['product_name'],
            'product_sku': l['product_sku'],
            'quantity': float(l['quantity'] or 0),
            'unit_price': float(l['unit_price'] or 0),
            'discount_percent': float(l['discount_percent'] or 0),
            'subtotal': float(l['subtotal'] or 0),
            'image_url': l['image_url'] or ''
        } for l in lines]
    })

@contacts_bp.route('/customers/<int:id>/save', methods=['POST'])
def save_customer(id):
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.is_json or
        request.args.get('format') == 'json'
    )
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()

        existing = query_one("SELECT id, branch_id FROM customers WHERE id = %s", (id,))
        if not existing:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Customer not found.'}), 404
            flash("Customer not found.", "error")
            return redirect(url_for('contacts.list_customers'))

        # Security check: Branch user can edit their own branch customer
        if not _check_customer_branch_access(existing):
            if is_ajax:
                return jsonify({'success': False, 'message': 'Permission denied: Cannot edit customers of other branches or HQ.'}), 403
            flash("🔒 Permission denied: Cannot edit customers of other branches or HQ.", "error")
            return redirect(url_for('contacts.list_customers'))

        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        contact_name = (data.get('contact_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        fax = (data.get('fax') or '').strip()
        email = (data.get('email') or '').strip()
        website = (data.get('website') or '').strip()
        address1 = (data.get('address1') or data.get('address') or '').strip()
        address2 = (data.get('address2') or '').strip()
        city = (data.get('city') or '').strip()
        state = (data.get('state') or '').strip()
        country = (data.get('country') or '').strip()
        postal_code = (data.get('postal_code') or '').strip()
        shipping_address = (data.get('shipping_address') or '').strip() or address1
        billing_address = (data.get('billing_address') or '').strip() or address1
        discount_percent = float(data.get('discount_percent') or 0)
        pricing_scheme_id = int(data.get('default_pricing_scheme_id') or data.get('pricing_scheme_id') or 0) or None
        payment_terms = (data.get('payment_terms') or 'Due on Receipt').strip()
        remarks = (data.get('remarks') or '').strip()

        if is_main_admin:
            raw_b = data.get('branch_id')
            target_branch_id = int(raw_b) if raw_b and str(raw_b).strip().isdigit() else None
        else:
            target_branch_id = existing.get('branch_id') if existing.get('branch_id') is not None else user_bid

        if not name:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Customer Name is required.'}), 400
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.detail_customer', id=id))

        tax_number = (data.get('tax_number') or '').strip()

        execute("""
            UPDATE customers
            SET name = %s,
                contact_name = %s,
                phone = %s,
                fax = %s,
                email = %s,
                website = %s,
                address1 = %s,
                address2 = %s,
                city = %s,
                state = %s,
                country = %s,
                postal_code = %s,
                shipping_address = %s,
                billing_address = %s,
                default_pricing_scheme_id = %s,
                discount_percent = %s,
                payment_terms = %s,
                remarks = %s,
                tax_number = %s,
                branch_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, contact_name, phone, fax, email, website, address1, address2, city, state, country, postal_code, shipping_address, billing_address, pricing_scheme_id, discount_percent, payment_terms, remarks, tax_number, target_branch_id, id))

        if is_ajax:
            cust_full = _get_customer_full_data(id, user_bid, is_main_admin)
            return jsonify({
                'success': True,
                'message': f"Customer '{name}' saved successfully!",
                'customer': {
                    'id': id,
                    'name': name,
                    'contact_name': contact_name,
                    'phone': phone,
                    'email': email,
                    'website': website,
                    'address1': address1,
                    'address2': address2,
                    'city': city,
                    'state': state,
                    'country': country,
                    'postal_code': postal_code,
                    'shipping_address': shipping_address,
                    'billing_address': billing_address,
                    'address': shipping_address or address1 or billing_address or address2 or '',
                    'display_address': shipping_address or address1 or billing_address or address2 or '',
                    'pricing_scheme_id': pricing_scheme_id,
                    'discount_percent': discount_percent,
                    'payment_terms': payment_terms,
                    'remarks': remarks,
                    'tax_number': tax_number,
                    'branch_id': target_branch_id,
                    'balance': float(((cust_full or {}).get('customer') or {}).get('balance') or 0),
                    'open_balance': float(((cust_full or {}).get('customer') or {}).get('balance') or 0)
                }
            })

        flash(f"Customer '{name}' saved successfully!", "success")
        return redirect(url_for('contacts.list_customers', selected_id=id))

    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error saving customer: {e}", "error")
        return redirect(url_for('contacts.detail_customer', id=id))

@contacts_bp.route('/customers/create', methods=['POST'])
def create_customer():
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.is_json or
        request.args.get('format') == 'json'
    )
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()

        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        contact_name = (data.get('contact_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        fax = (data.get('fax') or '').strip()
        email = (data.get('email') or '').strip()
        website = (data.get('website') or '').strip()
        address1 = (data.get('address1') or data.get('address') or '').strip()
        address2 = (data.get('address2') or '').strip()
        city = (data.get('city') or '').strip()
        state = (data.get('state') or '').strip()
        country = (data.get('country') or '').strip()
        postal_code = (data.get('postal_code') or '').strip()
        shipping_address = (data.get('shipping_address') or '').strip() or address1
        billing_address = (data.get('billing_address') or '').strip() or address1
        discount_percent = float(data.get('discount_percent') or 0)
        pricing_scheme_id = int(data.get('default_pricing_scheme_id') or data.get('pricing_scheme_id') or 0) or None
        payment_terms = (data.get('payment_terms') or 'Due on Receipt').strip()
        remarks = (data.get('remarks') or '').strip()

        if not name:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Customer Name is required.'}), 400
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.list_customers'))

        if is_main_admin:
            raw_b = data.get('branch_id')
            branch_id = int(raw_b) if raw_b and str(raw_b).strip().isdigit() else None
        else:
            branch_id = user_bid

        new_id = execute_returning_id("""
            INSERT INTO customers (
                name, contact_name, phone, fax, email, website,
                address1, address2, city, state, country, postal_code,
                shipping_address, billing_address,
                discount_percent, default_pricing_scheme_id, payment_terms,
                remarks, branch_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (name, contact_name, phone, fax, email, website, address1, address2, city, state, country, postal_code, shipping_address, billing_address, discount_percent, pricing_scheme_id, payment_terms, remarks, branch_id))

        if is_ajax:
            return jsonify({
                'success': True,
                'message': f"Customer '{name}' created successfully!",
                'customer': {
                    'id': new_id,
                    'name': name,
                    'contact_name': contact_name,
                    'phone': phone,
                    'email': email,
                    'website': website,
                    'address1': address1,
                    'city': city,
                    'shipping_address': shipping_address,
                    'billing_address': billing_address,
                    'address': shipping_address or address1 or billing_address or address2 or '',
                    'display_address': shipping_address or address1 or billing_address or address2 or '',
                    'pricing_scheme_id': pricing_scheme_id,
                    'discount_percent': discount_percent,
                    'payment_terms': payment_terms,
                    'remarks': remarks,
                    'branch_id': branch_id,
                    'balance': 0.0,
                    'open_balance': 0.0,
                    'order_count': 0
                }
            })

        flash(f"Customer '{name}' created successfully!", "success")
        return redirect(url_for('contacts.list_customers', selected_id=new_id))

    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error creating customer: {e}", "error")
        return redirect(url_for('contacts.list_customers'))

@contacts_bp.route('/customers/<int:id>/delete', methods=['POST', 'DELETE'])
def delete_customer(id):
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.is_json or
        request.args.get('format') == 'json' or
        request.method == 'DELETE'
    )
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()

        customer = query_one("SELECT name, branch_id FROM customers WHERE id = %s", (id,))
        if not customer:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Customer not found.'}), 404
            flash("Customer not found.", "error")
            return redirect(url_for('contacts.list_customers'))

        if not _check_customer_branch_access(customer):
            if is_ajax:
                return jsonify({'success': False, 'message': 'Permission denied: Cannot delete customer belonging to another branch.'}), 403
            flash("🔒 Permission denied: Cannot delete customer belonging to another branch.", "error")
            return redirect(url_for('contacts.list_customers'))

        cust_name = customer['name'] or f"#{id}"

        # Check if customer has any sales orders
        order_count = query_one("SELECT COUNT(*) as count FROM sales_orders WHERE customer_id = %s", (id,))
        if order_count and order_count['count'] > 0:
            execute("UPDATE customers SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
            msg = f"Customer '{cust_name}' has been archived ({order_count['count']} sales order(s) preserved)."
            action = 'archived'
        else:
            execute("DELETE FROM customers WHERE id = %s", (id,))
            msg = f"Customer '{cust_name}' removed permanently."
            action = 'deleted'

        if is_ajax:
            return jsonify({'success': True, 'action': action, 'message': msg, 'id': id, 'name': cust_name})

        flash(msg, "info" if action == 'archived' else "success")
        return redirect(url_for('contacts.list_customers'))
    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error removing customer: {e}", "error")
        return redirect(url_for('contacts.detail_customer', id=id))

@contacts_bp.route('/customers/bulk-delete', methods=['POST'])
def bulk_delete_customers():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    try:
        data = request.get_json(silent=True) or request.form
        raw_ids = data.get('ids')
        if isinstance(raw_ids, str):
            import json
            try:
                ids = json.loads(raw_ids)
            except Exception:
                ids = [int(x.strip()) for x in raw_ids.split(',') if x.strip().isdigit()]
        elif isinstance(raw_ids, (list, tuple)):
            ids = [int(x) for x in raw_ids if str(x).isdigit()]
        else:
            ids = []

        if not ids:
            if is_ajax:
                return jsonify({'success': False, 'message': 'No customer IDs provided.'}), 400
            flash("No customers selected for deletion.", "warning")
            return redirect(url_for('contacts.list_customers'))

        deleted_count = 0
        archived_count = 0
        skipped_count = 0

        for cid in ids:
            cust = query_one("SELECT id, name, branch_id FROM customers WHERE id = %s", (cid,))
            if not cust or not _check_customer_branch_access(cust):
                skipped_count += 1
                continue

            order_count = query_one("SELECT COUNT(*) as count FROM sales_orders WHERE customer_id = %s", (cid,))
            if order_count and order_count['count'] > 0:
                execute("UPDATE customers SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (cid,))
                archived_count += 1
            else:
                execute("DELETE FROM customers WHERE id = %s", (cid,))
                deleted_count += 1

        total_affected = deleted_count + archived_count
        msg = f"Successfully processed {total_affected} customer(s): {deleted_count} deleted permanently, {archived_count} archived with order history."
        if skipped_count > 0:
            msg += f" ({skipped_count} skipped due to branch permissions)"

        if is_ajax:
            return jsonify({
                'success': True,
                'deleted_count': deleted_count,
                'archived_count': archived_count,
                'skipped_count': skipped_count,
                'total_affected': total_affected,
                'message': msg
            })

        flash(msg, "success")
        return redirect(url_for('contacts.list_customers'))
    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error during bulk deletion: {e}", "error")
        return redirect(url_for('contacts.list_customers'))

@contacts_bp.route('/customers/export')
def export_customers():
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    search = request.args.get('search', '').strip()
    search_name = request.args.get('search_name', '').strip()
    op_name = request.args.get('op_name', '-').strip()
    search_contact = request.args.get('search_contact', '').strip()
    op_contact = request.args.get('op_contact', '-').strip()
    search_phone = request.args.get('search_phone', '').strip()
    op_phone = request.args.get('op_phone', '-').strip()
    search_address = request.args.get('search_address', '').strip()
    op_address = request.args.get('op_address', '-').strip()
    with_balance = request.args.get('with_balance', '').strip()
    scheme_filter = request.args.get('scheme_id', '').strip()

    sort_by = request.args.get('sort_by', 'name').strip().lower()
    sort_dir = request.args.get('sort_dir', 'asc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'asc'

    where_clauses = ["c.is_active = TRUE"]
    params = []

    if not is_main_admin:
        if user_bid is not None:
            where_clauses.append("c.branch_id = %s")
            params.append(user_bid)
        else:
            where_clauses.append("1=0")
    else:
        raw_branch = request.args.get('branch', 'main').strip().lower()
        if raw_branch == 'main':
            where_clauses.append("c.branch_id IS NULL")
        elif raw_branch == 'all':
            pass
        elif raw_branch.isdigit():
            where_clauses.append("c.branch_id = %s")
            params.append(int(raw_branch))
        else:
            where_clauses.append("c.branch_id IS NULL")

    def _apply_op(field, val, op):
        if op in ('=', 'exact'):
            return f"LOWER({field}) = LOWER(%s)", val
        elif op in ('^', 'starts'):
            return f"{field} ILIKE %s", f"{val}%"
        else:
            return f"{field} ILIKE %s", f"%{val}%"

    if search:
        where_clauses.append("(c.name ILIKE %s OR c.phone ILIKE %s OR c.contact_name ILIKE %s OR c.billing_address ILIKE %s OR c.address1 ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp, sp, sp])

    if search_name:
        clause, p = _apply_op("c.name", search_name, op_name)
        where_clauses.append(clause)
        params.append(p)

    if search_contact:
        clause, p = _apply_op("c.contact_name", search_contact, op_contact)
        where_clauses.append(clause)
        params.append(p)

    if search_phone:
        clause, p = _apply_op("c.phone", search_phone, op_phone)
        where_clauses.append(clause)
        params.append(p)

    if search_address:
        clause, p = _apply_op("COALESCE(NULLIF(c.address1, ''), c.billing_address, '')", search_address, op_address)
        where_clauses.append(clause)
        params.append(p)

    if scheme_filter and scheme_filter.isdigit():
        where_clauses.append("c.default_pricing_scheme_id = %s")
        params.append(int(scheme_filter))

    having_clauses = []
    if with_balance == '1':
        having_clauses.append("COALESCE(SUM(so.balance_due), 0) > 0")

    where_sql = " AND ".join(where_clauses)
    having_sql = f"HAVING {' AND '.join(having_clauses)}" if having_clauses else ""

    sort_cols = {
        'name': 'c.name',
        'contact': 'c.contact_name',
        'phone': 'c.phone',
        'email': 'c.email',
        'website': 'c.website',
        'address1': 'c.address1',
        'address2': 'c.address2',
        'city': 'c.city',
        'state': 'c.state',
        'postal_code': 'c.postal_code',
        'country': 'c.country',
        'pricing': 'pricing_scheme_name',
        'discount': 'c.discount_percent',
        'branch': 'branch_name',
        'balance': 'open_balance',
        'orders': 'order_count',
        'spent': 'total_spent'
    }
    order_col = sort_cols.get(sort_by, 'c.name')
    order_clause = f"ORDER BY {order_col} {sort_dir.upper()} NULLS LAST"

    sql = f"""
        SELECT 
            c.*,
            b.name as branch_name,
            b.code as branch_code,
            ps.name as pricing_scheme_name,
            COUNT(so.id) as order_count,
            COALESCE(SUM(so.total_amount), 0) as total_spent,
            COALESCE(SUM(so.balance_due), 0) as open_balance
        FROM customers c
        LEFT JOIN branches b ON c.branch_id = b.id
        LEFT JOIN pricing_schemes ps ON c.default_pricing_scheme_id = ps.id
        LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
        WHERE {where_sql}
        GROUP BY c.id, b.name, b.code, ps.name
        {having_sql}
        {order_clause}
    """
    rows = query_all(sql, tuple(params))

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel Khmer support
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Name', 'Contact Name', 'Phone', 'Email', 'Website',
        'Address 1', 'Address 2', 'City', 'State/Province', 'Zip/Postal Code', 'Country',
        'Pricing Scheme', 'Discount (%)', 'Branch', 'Open Balance ($)', 'Total Spent ($)', 'Orders Count'
    ])

    for r in rows:
        c_name, c_contact, c_phone = resolve_customer_phone_and_name(
            r['name'], r['contact_name'], r['phone'], r['address1'] or r['billing_address'] or ''
        )
        writer.writerow([
            r['id'],
            c_name or '',
            c_contact or '',
            c_phone or '',
            r['email'] or '',
            r['website'] or '',
            r['address1'] or r['billing_address'] or '',
            r['address2'] or '',
            r['city'] or '',
            r['state'] or '',
            r['postal_code'] or '',
            r['country'] or '',
            r['pricing_scheme_name'] or 'Retail 1',
            f"{float(r['discount_percent'] or 0):.2f}",
            r['branch_code'] or r['branch_name'] or 'HQ',
            f"{float(r['open_balance'] or 0):.2f}",
            f"{float(r['total_spent'] or 0):.2f}",
            r['order_count'] or 0
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=inflow_customers.csv"}
    )


@contacts_bp.route('/customers/<int:id>/export-orders')
def export_customer_orders(id):
    customer = query_one("SELECT * FROM customers WHERE id = %s", (id,))
    if not customer:
        flash("Customer not found", "error")
        return redirect(url_for('contacts.customers_view'))

    if not _check_customer_branch_access(customer):
        flash("Access denied.", "error")
        return redirect(url_for('contacts.customers_view'))

    c_name, c_contact, c_phone = resolve_customer_phone_and_name(
        customer.get('name'), customer.get('contact_name'), customer.get('phone'),
        customer.get('address1') or customer.get('shipping_address') or ''
    )

    rows = query_all("""
        SELECT so.order_number, to_char(so.order_date, 'YYYY-MM-DD') as order_date,
               so.status, so.payment_status,
               COALESCE(NULLIF(TRIM(so.customer_phone), ''), %s) as phone,
               COALESCE(NULLIF(TRIM(so.customer_address), ''), %s) as address,
               p.sku, COALESCE(NULLIF(sol.description, ''), p.name, '') as item_description,
               sol.quantity, sol.unit_price, sol.subtotal,
               so.total_amount, so.paid_amount, so.balance_due
        FROM sales_orders so
        LEFT JOIN sales_order_lines sol ON sol.sales_order_id = so.id
        LEFT JOIN products p ON sol.product_id = p.id
        WHERE so.customer_id = %s
        ORDER BY so.id DESC, sol.line_num ASC;
    """, (c_phone, customer.get('address1') or '', id))

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM
    writer = csv.writer(output)
    writer.writerow([
        'Order Number', 'Order Date', 'Status', 'Payment Status',
        'Customer Name', 'Customer Phone', 'Delivery Address',
        'Item Code', 'Description', 'Quantity', 'Unit Price', 'Line Subtotal',
        'Order Total', 'Paid Amount', 'Balance Due'
    ])

    for r in rows:
        writer.writerow([
            r['order_number'] or '',
            r['order_date'] or '',
            r['status'] or '',
            r['payment_status'] or '',
            c_name or '',
            r['phone'] or c_phone or '',
            r['address'] or '',
            r['sku'] or '',
            r['item_description'] or '',
            f"{float(r['quantity'] or 0):g}",
            f"{float(r['unit_price'] or 0):.2f}",
            f"{float(r['subtotal'] or 0):.2f}",
            f"{float(r['total_amount'] or 0):.2f}",
            f"{float(r['paid_amount'] or 0):.2f}",
            f"{float(r['balance_due'] or 0):.2f}"
        ])

    clean_filename = re.sub(r'[^a-zA-Z0-9_\-]', '_', c_name or f"Customer_{id}")
    filename = f"Orders_{clean_filename}.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


@contacts_bp.route('/vendors')
def list_vendors():
    vendors = query_all("""
        SELECT 
            v.*,
            COUNT(po.id) as po_count,
            COALESCE(SUM(po.total_amount), 0) as total_purchased,
            COALESCE(SUM(po.balance_due), 0) as open_payable
        FROM vendors v
        LEFT JOIN purchase_orders po ON v.id = po.vendor_id AND po.status != 'CANCELLED'
        WHERE v.is_active = TRUE
        GROUP BY v.id
        ORDER BY v.name ASC
    """)
    return render_template('contacts/vendors.html', vendors=vendors)

@contacts_bp.route('/vendors/create', methods=['POST'])
def create_vendor():
    try:
        name = request.form.get('name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        address1 = request.form.get('address1', '').strip()
        city = request.form.get('city', '').strip()
        country = request.form.get('country', 'Cambodia').strip()

        if not name:
            flash("Vendor name is required.", "error")
            return redirect(url_for('contacts.list_vendors'))

        execute("""
            INSERT INTO vendors (name, contact_name, phone, email, address1, city, country)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, (name, contact_name, phone, email, address1, city, country))

        flash(f"Vendor '{name}' added successfully!", "success")
        return redirect(url_for('contacts.list_vendors'))

    except Exception as e:
        flash(f"Error adding vendor: {e}", "error")
        return redirect(url_for('contacts.list_vendors'))

@contacts_bp.route('/api/customers/search')
def search_customers_json():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    user_role = session.get('role', 'branch_admin')
    user_bid = session.get('branch_id')
    is_main_admin = (user_role == 'main_admin')

    where_clauses = ["is_active = TRUE", "(name ILIKE %s OR phone ILIKE %s)"]
    param = f"%{query}%"
    params = [param, param]

    if not is_main_admin:
        if user_bid:
            where_clauses.append("branch_id = %s")
            params.append(int(user_bid))
        else:
            where_clauses.append("branch_id IS NULL")
    else:
        req_b = request.args.get('branch_id') or request.args.get('branch') or 'main'
        if req_b and str(req_b).strip().lower() == 'main':
            where_clauses.append("branch_id IS NULL")
        elif req_b and str(req_b).strip().isdigit():
            where_clauses.append("branch_id = %s")
            params.append(int(req_b))
        elif req_b and str(req_b).strip().lower() == 'all':
            pass

    where_sql = " AND ".join(where_clauses)
    results = query_all(f"""
        SELECT id, name, phone, email, address1, city, discount_percent, branch_id
        FROM customers
        WHERE {where_sql}
        ORDER BY name ASC
        LIMIT 20
    """, tuple(params))

    return jsonify([dict(r) for r in results])


@contacts_bp.route('/api/customers/quick-add', methods=['POST'])
def quick_add_customer_ajax():
    try:
        user_role = session.get('role', 'branch_admin')
        user_bid = session.get('branch_id')
        is_main_admin = (user_role == 'main_admin')

        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        contact_name = (data.get('contact_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip()
        website = (data.get('website') or '').strip()
        address1 = (data.get('address') or data.get('address1') or '').strip()
        address2 = (data.get('address2') or '').strip()
        city = (data.get('city') or '').strip()
        state = (data.get('state') or '').strip()
        postal_code = (data.get('postal_code') or '').strip()
        country = (data.get('country') or 'Cambodia').strip()
        pricing_scheme_id = int(data.get('pricing_scheme_id') or data.get('default_pricing_scheme_id') or 0) or 100
        discount_percent = float(data.get('discount_percent') or 0)

        if not name:
            return jsonify({'success': False, 'message': 'Customer name is required'}), 400

        if not is_main_admin:
            branch_id = user_bid
        else:
            raw_b = data.get('branch_id')
            if raw_b and str(raw_b).lower() not in ('main', 'none', '', 'all', '0', 'null') and str(raw_b).isdigit():
                branch_id = int(raw_b)
            else:
                branch_id = None

        new_id = execute_returning_id("""
            INSERT INTO customers (
                name, contact_name, phone, email, website,
                address1, address2, city, state, postal_code, country,
                shipping_address, billing_address,
                default_pricing_scheme_id, discount_percent, branch_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id;
        """, (name, contact_name, phone, email, website,
              address1, address2, city, state, postal_code, country,
              address1, address1, pricing_scheme_id, discount_percent, branch_id))

        scheme = query_one("SELECT name FROM pricing_schemes WHERE id = %s", (pricing_scheme_id,))
        scheme_name = scheme['name'] if scheme else 'Retail 1'

        branch_row = query_one("SELECT name, code FROM branches WHERE id = %s", (branch_id,)) if branch_id else None

        customer = {
            'id': new_id,
            'name': name,
            'contact_name': contact_name,
            'phone': phone,
            'email': email,
            'website': website,
            'address': address1,
            'address1': address1,
            'address2': address2,
            'shipping_address': address1,
            'billing_address': address1,
            'display_address': address1,
            'city': city,
            'state': state,
            'postal_code': postal_code,
            'country': country,
            'pricing_scheme_id': pricing_scheme_id,
            'pricing_scheme_name': scheme_name,
            'discount_percent': discount_percent,
            'branch_id': branch_id,
            'branch_name': branch_row['name'] if branch_row else '',
            'branch_code': branch_row['code'] if branch_row else ''
        }

        return jsonify({'success': True, 'customer': customer})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@contacts_bp.route('/api/customers/ai-extract', methods=['POST'])
def ai_extract_customer():
    try:
        from services.ai_customer_extractor import extract_customer_info
        import base64

        image_bytes = None
        image_b64 = None
        mime_type = "image/jpeg"
        text_fallback = ""
        api_key = None

        if request.content_type and 'multipart/form-data' in request.content_type:
            if 'image' in request.files and request.files['image'].filename:
                file = request.files['image']
                image_bytes = file.read()
                mime_type = file.mimetype or "image/jpeg"
            elif 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                image_bytes = file.read()
                mime_type = file.mimetype or "image/jpeg"
            text_fallback = request.form.get('text', '')
            api_key = request.form.get('api_key')
        else:
            json_data = request.get_json(silent=True) or {}
            raw_b64 = json_data.get('image_data') or json_data.get('image_base64')
            if raw_b64:
                if ',' in raw_b64:
                    header, raw_b64 = raw_b64.split(',', 1)
                    if 'image/png' in header:
                        mime_type = 'image/png'
                    elif 'image/webp' in header:
                        mime_type = 'image/webp'
                    elif 'image/jpeg' in header or 'image/jpg' in header:
                        mime_type = 'image/jpeg'
                image_b64 = raw_b64
            text_fallback = json_data.get('text', '')
            api_key = json_data.get('api_key')

        result = extract_customer_info(
            image_bytes=image_bytes,
            image_b64=image_b64,
            mime_type=mime_type,
            text_fallback=text_fallback,
            api_key=api_key
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f"Extraction error: {str(e)}"}), 500


@contacts_bp.route('/api/customers/ai-key-status', methods=['GET'])
def ai_key_status():
    from services.ai_customer_extractor import get_configured_gemini_api_key
    key = get_configured_gemini_api_key()
    has_key = bool(key)
    masked = (key[:4] + '...' + key[-4:]) if has_key and len(key) >= 8 else ('****' if has_key else '')
    return jsonify({'success': True, 'has_key': has_key, 'masked_key': masked})


@contacts_bp.route('/api/customers/save-ai-key', methods=['POST'])
def save_ai_key():
    try:
        from services.ai_customer_extractor import save_gemini_api_key
        data = request.get_json(silent=True) or request.form or {}
        key = (data.get('api_key') or '').strip()
        ok = save_gemini_api_key(key)
        return jsonify({'success': ok, 'has_key': bool(key)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@contacts_bp.route('/customers/<int:id>/print-label')
def print_customer_label(id):
    from datetime import date
    from routes.settings import get_invoice_settings
    
    user_role = session.get('role', 'branch_admin')
    user_bid = session.get('branch_id')
    is_main_admin = (user_role == 'main_admin')

    customer = query_one("""
        SELECT *, 
               COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), '') as display_address 
        FROM customers 
        WHERE id = %s
    """, (id,))
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for('contacts.list_customers'))

    if not is_main_admin and customer.get('branch_id') != user_bid:
        flash("🔒 Access Denied: You cannot print label for customers outside your branch.", "error")
        return redirect(url_for('contacts.list_customers'))
    
    company = query_one("SELECT * FROM companies LIMIT 1") or {}
    inv_settings = get_invoice_settings()
    
    delivery_services = query_all("SELECT * FROM delivery_services WHERE is_active = TRUE ORDER BY id ASC")
    if not delivery_services:
        defaults = [
            ('Virak Buntham', 'VET', '023 999 999'),
            ('Capitol', 'CAPITOL', '023 217 627'),
            ('J&T Express', 'JT', '023 999 555'),
            ('Taxi (ឡានឈ្នួល)', 'TAXI', ''),
            ('KEX Express', 'KEX', ''),
            ('Cambodia Post', 'POST', '023 428 555')
        ]
        for name, code, phone in defaults:
            execute("INSERT INTO delivery_services (name, code, phone) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING;", (name, code, phone))
        delivery_services = query_all("SELECT * FROM delivery_services WHERE is_active = TRUE ORDER BY id ASC")

    selected_carrier = request.args.get('carrier') or (delivery_services[0]['name'] if delivery_services else 'Virak Buntham')
    package_count = max(1, int(request.args.get('packages') or 1))
    delivery_notes = request.args.get('notes') or ''
    
    raw_cost = request.args.get('cost')
    if raw_cost is not None:
        try:
            product_cost = max(0.0, float(raw_cost))
        except (ValueError, TypeError):
            product_cost = float(customer.get('balance') or 0.0)
    else:
        product_cost = float(customer.get('balance') or 0.0)
        
    address = request.args.get('address') or customer.get('display_address') or customer.get('shipping_address') or customer.get('address1') or 'រាជធានីភ្នំពេញ / Phnom Penh'
    
    recent_order = query_one("SELECT order_number FROM sales_orders WHERE customer_id = %s ORDER BY id DESC LIMIT 1", (id,))
    order_num = recent_order['order_number'] if recent_order else f"CUST-{id:04d}"

    order = {
        'id': id,
        'order_number': order_num,
        'order_date': date.today(),
        'customer_name': customer.get('name') or '',
        'customer_contact': customer.get('contact_name') or '',
        'customer_phone': customer.get('phone') or '',
        'customer_address': address,
        'total_amount': product_cost
    }

    raw_sender = (inv_settings.get('phone') if inv_settings else None) or (company.get('phone') if company else None) or ''
    sender_phone = ''
    if raw_sender:
        sender_phone = re.split(r'[/\\;,|]', str(raw_sender))[0].strip()
    if not sender_phone:
        sender_phone = '010 264 731'

    return render_template('sales/delivery_label_print.html',
                           order=order,
                           company=company,
                           inv_settings=inv_settings,
                           sender_phone=sender_phone,
                           delivery_services=delivery_services,
                           selected_carrier=selected_carrier,
                           package_count=package_count,
                           delivery_notes=delivery_notes,
                           product_cost=product_cost)

