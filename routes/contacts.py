from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from database import query_one, query_all, execute, execute_returning_id
import re

contacts_bp = Blueprint('contacts', __name__)

@contacts_bp.route('/customers')
def list_customers():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    offset = (page - 1) * per_page
    search = request.args.get('search', '').strip()

    where_clauses = ["c.is_active = TRUE"]
    params = []

    if search:
        where_clauses.append("(c.name ILIKE %s OR c.phone ILIKE %s OR c.contact_name ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp])

    where_sql = " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) as cnt FROM customers c WHERE {where_sql}"
    total_count = query_one(count_sql, tuple(params))['cnt']
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    list_sql = f"""
        SELECT 
            c.*,
            COUNT(so.id) as order_count,
            COALESCE(SUM(so.total_amount), 0) as total_spent,
            COALESCE(SUM(so.balance_due), 0) as open_balance
        FROM customers c
        LEFT JOIN sales_orders so ON c.id = so.customer_id AND so.status != 'CANCELLED'
        WHERE {where_sql}
        GROUP BY c.id
        ORDER BY c.name ASC
        LIMIT %s OFFSET %s
    """
    rows_params = params.copy()
    rows_params.extend([per_page, offset])
    customers = query_all(list_sql, tuple(rows_params))

    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")

    return render_template('contacts/customers.html',
                           customers=customers,
                           search=search,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           pricing_schemes=pricing_schemes)

@contacts_bp.route('/customers/new')
def new_customer():
    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")
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
        'payment_terms': 'Due on Receipt'
    }
    return render_template('contacts/customer_detail.html',
                           customer=customer,
                           orders=[],
                           pricing_schemes=pricing_schemes,
                           is_new=True)

@contacts_bp.route('/customers/<int:id>')
def detail_customer(id):
    customer = query_one("""
        SELECT *, 
               COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as display_address 
        FROM customers 
        WHERE id = %s
    """, (id,))
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for('contacts.list_customers'))

    orders = query_all("""
        SELECT so.*, l.name as location_name
        FROM sales_orders so
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE so.customer_id = %s
        ORDER BY so.order_date DESC, so.id DESC
        LIMIT 50
    """, (id,))

    pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")

    return render_template('contacts/customer_detail.html',
                           customer=customer,
                           orders=orders,
                           pricing_schemes=pricing_schemes,
                           is_new=False)

@contacts_bp.route('/customers/<int:id>/save', methods=['POST'])
def save_customer(id):
    try:
        name = request.form.get('name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        phone = request.form.get('phone', '').strip()
        fax = request.form.get('fax', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        address1 = request.form.get('address1', '').strip()
        shipping_address = request.form.get('shipping_address', '').strip()
        billing_address = request.form.get('billing_address', '').strip()
        discount_percent = float(request.form.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(request.form.get('default_pricing_scheme_id') or 0) or None
        payment_terms = request.form.get('payment_terms', 'Due on Receipt').strip()

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
                shipping_address = %s,
                billing_address = %s,
                default_pricing_scheme_id = %s,
                discount_percent = %s,
                payment_terms = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, contact_name, phone, fax, email, website, address1, shipping_address, billing_address, pricing_scheme_id, discount_percent, payment_terms, id))

        flash(f"Customer '{name}' saved successfully!", "success")
        return redirect(url_for('contacts.detail_customer', id=id))

    except Exception as e:
        flash(f"Error saving customer: {e}", "error")
        return redirect(url_for('contacts.detail_customer', id=id))

@contacts_bp.route('/customers/create', methods=['POST'])
def create_customer():
    try:
        name = request.form.get('name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        phone = request.form.get('phone', '').strip()
        fax = request.form.get('fax', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        address1 = request.form.get('address1', '').strip()
        shipping_address = request.form.get('shipping_address', '').strip() or address1
        billing_address = request.form.get('billing_address', '').strip() or address1
        discount_percent = float(request.form.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(request.form.get('default_pricing_scheme_id') or 0) or None
        payment_terms = request.form.get('payment_terms', 'Due on Receipt').strip()

        if not name:
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.list_customers'))

        branch_id = request.form.get('branch_id') or session.get('active_branch_id')
        branch_id = int(branch_id) if branch_id else None

        new_id = execute_returning_id("""
            INSERT INTO customers (
                name, contact_name, phone, fax, email, website,
                address1, shipping_address, billing_address,
                discount_percent, default_pricing_scheme_id, payment_terms,
                branch_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (name, contact_name, phone, fax, email, website, address1, shipping_address, billing_address, discount_percent, pricing_scheme_id, payment_terms, branch_id))

        flash(f"Customer '{name}' created successfully!", "success")
        return redirect(url_for('contacts.detail_customer', id=new_id))

    except Exception as e:
        flash(f"Error creating customer: {e}", "error")
        return redirect(url_for('contacts.list_customers'))

@contacts_bp.route('/customers/<int:id>/delete', methods=['POST'])
def delete_customer(id):
    try:
        customer = query_one("SELECT name FROM customers WHERE id = %s", (id,))
        cust_name = customer['name'] if customer else f"#{id}"

        # Check if customer has any sales orders
        order_count = query_one("SELECT COUNT(*) as count FROM sales_orders WHERE customer_id = %s", (id,))
        if order_count and order_count['count'] > 0:
            execute("UPDATE customers SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
            flash(f"Customer '{cust_name}' has been removed/archived ({order_count['count']} sales order(s) preserved).", "info")
        else:
            execute("DELETE FROM customers WHERE id = %s", (id,))
            flash(f"Customer '{cust_name}' removed permanently.", "success")

        return redirect(url_for('contacts.list_customers'))
    except Exception as e:
        flash(f"Error removing customer: {e}", "error")
        return redirect(url_for('contacts.detail_customer', id=id))

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

    param = f"%{query}%"
    results = query_all("""
        SELECT id, name, phone, email, address1, city, discount_percent
        FROM customers
        WHERE is_active = TRUE AND (name ILIKE %s OR phone ILIKE %s)
        ORDER BY name ASC
        LIMIT 20
    """, (param, param))

    return jsonify([dict(r) for r in results])


@contacts_bp.route('/api/customers/quick-add', methods=['POST'])
def quick_add_customer_ajax():
    try:
        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        contact_name = (data.get('contact_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        address = (data.get('address') or data.get('address1') or '').strip()
        pricing_scheme_id = int(data.get('pricing_scheme_id') or 0) or 100

        if not name:
            return jsonify({'success': False, 'message': 'Customer name is required'}), 400

        branch_id = data.get('branch_id') or session.get('active_branch_id')
        if branch_id and str(branch_id).lower() not in ('main', 'none', ''):
            try:
                branch_id = int(branch_id)
            except (ValueError, TypeError):
                branch_id = None
        else:
            branch_id = None

        new_id = execute_returning_id("""
            INSERT INTO customers (
                name, contact_name, phone, address1, shipping_address, billing_address,
                default_pricing_scheme_id, branch_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id;
        """, (name, contact_name, phone, address, address, address, pricing_scheme_id, branch_id))

        customer = {
            'id': new_id,
            'name': name,
            'contact_name': contact_name,
            'phone': phone,
            'address': address,
            'address1': address,
            'pricing_scheme_id': pricing_scheme_id
        }

        return jsonify({'success': True, 'customer': customer})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@contacts_bp.route('/customers/<int:id>/print-label')
def print_customer_label(id):
    from datetime import date
    from routes.settings import get_invoice_settings
    
    customer = query_one("""
        SELECT *, 
               COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), '') as display_address 
        FROM customers 
        WHERE id = %s
    """, (id,))
    if not customer:
        flash("Customer not found.", "error")
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

