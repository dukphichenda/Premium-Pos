from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, Response
from database import query_one, query_all, execute, execute_returning_id
import re
import csv
import io

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
            c.id, c.name, c.contact_name, c.phone, c.address1, c.billing_address, c.shipping_address, c.branch_id,
            c.city, c.discount_percent, ps.name as pricing_scheme_name
        FROM customers c
        LEFT JOIN pricing_schemes ps ON c.default_pricing_scheme_id = ps.id
        WHERE {' AND '.join(where)}
        ORDER BY c.name ASC
        LIMIT 500
    """
    return query_all(sql, tuple(params))

@contacts_bp.route('/customers')
def list_customers():
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    page = int(request.args.get('page', 1))
    per_page_raw = request.args.get('per_page', '50').strip().lower()
    
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
        raw_branch = request.args.get('branch', 'main').strip().lower()
        if raw_branch == 'main':
            where_clauses.append("c.branch_id IS NULL")
            current_branch_param = 'main'
        elif raw_branch == 'all':
            current_branch_param = 'all'  # HQ sees all combined
        elif raw_branch.isdigit():
            where_clauses.append("c.branch_id = %s")
            params.append(int(raw_branch))
            current_branch_param = raw_branch
        else:
            where_clauses.append("c.branch_id IS NULL")
            current_branch_param = 'main'

    def _apply_op(field, val, op):
        if op in ('=', 'exact'):
            return f"LOWER({field}) = LOWER(%s)", val
        elif op in ('^', 'starts'):
            return f"{field} ILIKE %s", f"{val}%"
        else:  # default contains '-'
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
    
    if per_page_raw == 'all':
        per_page = max(1, total_count)
        page = 1
        offset = 0
        total_pages = 1
    else:
        try:
            per_page = max(10, min(500, int(per_page_raw)))
        except ValueError:
            per_page = 50
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

    return render_template('contacts/customers.html',
                           customers=customers,
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

@contacts_bp.route('/customers/<int:id>')
def detail_customer(id):
    is_main_admin = _is_main_admin()
    user_bid = _get_user_branch_id()

    customer = query_one("""
        SELECT c.*, 
               b.name as branch_name, b.code as branch_code,
               COALESCE(NULLIF(c.address1, ''), NULLIF(c.shipping_address, ''), '') as display_address 
        FROM customers c
        LEFT JOIN branches b ON c.branch_id = b.id
        WHERE c.id = %s
    """, (id,))
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for('contacts.list_customers'))

    # Security rule: Branch user can ONLY view their own branch's customers
    if not _check_customer_branch_access(customer):
        flash("🔒 Access Denied: You do not have permission to view customers outside your branch. / សិទ្ធិត្រូវបានកំណត់៖ អ្នកអាចមើលបានតែអតិថិជនក្នុងសាខារបស់អ្នកប៉ុណ្ណោះ", "error")
        return redirect(url_for('contacts.list_customers'))

    if not is_main_admin and user_bid:
        orders = query_all("""
            SELECT so.*, l.name as location_name
            FROM sales_orders so
            LEFT JOIN locations l ON so.location_id = l.id
            WHERE so.customer_id = %s AND so.branch_id = %s
            ORDER BY so.order_date DESC, so.id DESC
            LIMIT 50
        """, (id, user_bid))
    else:
        orders = query_all("""
            SELECT so.*, l.name as location_name
            FROM sales_orders so
            LEFT JOIN locations l ON so.location_id = l.id
            WHERE so.customer_id = %s
            ORDER BY so.order_date DESC, so.id DESC
            LIMIT 50
        """, (id,))

    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")
    branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC") if is_main_admin else []
    
    search_name = request.args.get('search_name', '').strip()
    search_contact = request.args.get('search_contact', '').strip()
    search_phone = request.args.get('search_phone', '').strip()
    search_address = request.args.get('search_address', '').strip()
    sidebar_customers = _get_sidebar_customers(search_name, search_contact, search_phone, search_address)

    return render_template('contacts/customer_detail.html',
                           customer=customer,
                           orders=orders,
                           pricing_schemes=pricing_schemes,
                           branches=branches,
                           is_main_admin=is_main_admin,
                           sidebar_customers=sidebar_customers,
                           is_new=False)

@contacts_bp.route('/customers/<int:id>/save', methods=['POST'])
def save_customer(id):
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()

        existing = query_one("SELECT id, branch_id FROM customers WHERE id = %s", (id,))
        if not existing:
            flash("Customer not found.", "error")
            return redirect(url_for('contacts.list_customers'))

        # Security check: Branch user can edit their own branch customer
        if not _check_customer_branch_access(existing):
            flash("🔒 Permission denied: Cannot edit customers of other branches or HQ.", "error")
            return redirect(url_for('contacts.list_customers'))

        name = request.form.get('name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        phone = request.form.get('phone', '').strip()
        fax = request.form.get('fax', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        address1 = request.form.get('address1', '').strip()
        address2 = request.form.get('address2', '').strip()
        city = request.form.get('city', '').strip()
        state = request.form.get('state', '').strip()
        country = request.form.get('country', '').strip()
        postal_code = request.form.get('postal_code', '').strip()
        shipping_address = request.form.get('shipping_address', '').strip() or address1
        billing_address = request.form.get('billing_address', '').strip() or address1
        discount_percent = float(request.form.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(request.form.get('default_pricing_scheme_id') or 0) or None
        payment_terms = request.form.get('payment_terms', 'Due on Receipt').strip()
        remarks = request.form.get('remarks', '').strip()

        if is_main_admin:
            raw_b = request.form.get('branch_id')
            target_branch_id = int(raw_b) if raw_b and str(raw_b).strip().isdigit() else None
        else:
            target_branch_id = existing.get('branch_id') if existing.get('branch_id') is not None else user_bid

        if not name:
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.detail_customer', id=id))

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
                branch_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, contact_name, phone, fax, email, website, address1, address2, city, state, country, postal_code, shipping_address, billing_address, pricing_scheme_id, discount_percent, payment_terms, remarks, target_branch_id, id))

        flash(f"Customer '{name}' saved successfully!", "success")
        return redirect(url_for('contacts.detail_customer', id=id))

    except Exception as e:
        flash(f"Error saving customer: {e}", "error")
        return redirect(url_for('contacts.detail_customer', id=id))

@contacts_bp.route('/customers/create', methods=['POST'])
def create_customer():
    try:
        is_main_admin = _is_main_admin()
        user_bid = _get_user_branch_id()

        name = request.form.get('name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        phone = request.form.get('phone', '').strip()
        fax = request.form.get('fax', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        address1 = request.form.get('address1', '').strip()
        address2 = request.form.get('address2', '').strip()
        city = request.form.get('city', '').strip()
        state = request.form.get('state', '').strip()
        country = request.form.get('country', '').strip()
        postal_code = request.form.get('postal_code', '').strip()
        shipping_address = request.form.get('shipping_address', '').strip() or address1
        billing_address = request.form.get('billing_address', '').strip() or address1
        discount_percent = float(request.form.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(request.form.get('default_pricing_scheme_id') or 0) or None
        payment_terms = request.form.get('payment_terms', 'Due on Receipt').strip()
        remarks = request.form.get('remarks', '').strip()

        if not name:
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.list_customers'))

        if is_main_admin:
            raw_b = request.form.get('branch_id')
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

        flash(f"Customer '{name}' created successfully!", "success")
        return redirect(url_for('contacts.detail_customer', id=new_id))

    except Exception as e:
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
        writer.writerow([
            r['id'],
            r['name'] or '',
            r['contact_name'] or '',
            r['phone'] or '',
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
            'address1': address1,
            'address2': address2,
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

