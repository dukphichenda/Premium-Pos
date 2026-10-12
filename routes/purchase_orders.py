from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val
from datetime import datetime

purchase_orders_bp = Blueprint('purchase_orders', __name__)

@purchase_orders_bp.route('/purchases')
def list_purchases():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    offset = (page - 1) * per_page

    status = request.args.get('status', '').strip()
    payment_status = request.args.get('payment_status', '').strip()
    search = request.args.get('search', '').strip()

    where_clauses = ["1=1"]
    params = []

    if status:
        where_clauses.append("po.status = %s")
        params.append(status)

    if payment_status:
        where_clauses.append("po.payment_status = %s")
        params.append(payment_status)

    if search:
        where_clauses.append("(po.order_number ILIKE %s OR v.name ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp])

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
            COUNT(pol.id) as line_count
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

    status_counts = query_all("SELECT status, COUNT(*) as cnt FROM purchase_orders GROUP BY status")
    stats_dict = {r['status']: r['cnt'] for r in status_counts}

    return render_template('purchases/list.html',
                           orders=orders,
                           status=status,
                           payment_status=payment_status,
                           search=search,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           stats_dict=stats_dict)

@purchase_orders_bp.route('/purchases/create', methods=['GET', 'POST'])
def create_purchase():
    if request.method == 'GET':
        vendors = query_all("SELECT id, name, phone FROM vendors WHERE is_active = TRUE ORDER BY name")
        locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
        prefill_prod_id = request.args.get('product_id')
        prefill_prod = None
        if prefill_prod_id:
            prefill_prod = query_one("SELECT * FROM products WHERE id = %s", (prefill_prod_id,))
        return render_template('purchases/create.html', vendors=vendors, locations=locations, prefill_prod=prefill_prod)

    try:
        vendor_id = int(request.form.get('vendor_id'))
        location_id = int(request.form.get('location_id'))
        raw_order_date = request.form.get('order_date')
        order_date = datetime.now().date()
        if raw_order_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    order_date = datetime.strptime(str(raw_order_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        raw_expected_date = request.form.get('expected_date')
        expected_date = None
        if raw_expected_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    expected_date = datetime.strptime(str(raw_expected_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass
        notes = request.form.get('notes', '').strip()
        shipping_fee = max(0.0, float(request.form.get('shipping_fee', 0) or 0))

        prod_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        unit_costs = request.form.getlist('unit_cost[]')
        descriptions = request.form.getlist('description[]')

        if not prod_ids:
            flash("Please add at least one line item.", "error")
            return redirect(url_for('purchase_orders.create_purchase'))

        seq_val = get_next_sequence_val('po_number_seq')
        order_number = f"PO-{seq_val:06d}"

        subtotal = 0.0
        lines_data = []

        for idx in range(len(prod_ids)):
            pid = int(prod_ids[idx])
            qty = max(0.0001, float(quantities[idx] or 1))
            cost = max(0.0, float(unit_costs[idx] or 0))
            desc = descriptions[idx] if idx < len(descriptions) else ''
            line_sub = qty * cost
            subtotal += line_sub
            lines_data.append((idx + 1, pid, desc, qty, cost, line_sub))

        total_amount = subtotal + shipping_fee
        balance_due = total_amount

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO purchase_orders (
                    order_number, vendor_id, location_id, order_date, expected_date,
                    status, payment_status, subtotal, shipping_fee, total_amount, paid_amount, balance_due, notes
                ) VALUES (%s, %s, %s, %s, %s, 'ISSUED', 'UNPAID', %s, %s, %s, 0, %s, %s)
                RETURNING id;
            """, (order_number, vendor_id, location_id, order_date, expected_date, subtotal, shipping_fee, total_amount, balance_due, notes))
            po_id = cur.fetchone()['id']

            for line in lines_data:
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (po_id, line[0], line[1], line[2], line[3], line[4], line[5]))

            # Update vendor open balance
            cur.execute("""
                UPDATE vendors 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (balance_due, vendor_id))

        flash(f"Purchase Order {order_number} created successfully!", "success")
        return redirect(url_for('purchase_orders.detail_purchase', id=po_id))

    except Exception as e:
        flash(f"Error creating PO: {e}", "error")
        return redirect(url_for('purchase_orders.create_purchase'))

@purchase_orders_bp.route('/purchases/<int:id>')
def detail_purchase(id):
    order = query_one("""
        SELECT 
            po.*,
            v.name as vendor_name,
            v.phone as vendor_phone,
            v.email as vendor_email,
            v.address1 as vendor_address,
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

    lines = query_all("""
        SELECT 
            pol.*,
            p.name as product_name,
            p.sku as product_sku,
            p.uom as product_uom
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    payments = query_all("""
        SELECT * FROM order_payments 
        WHERE order_type = 'PO' AND order_id = %s 
        ORDER BY payment_date DESC, id DESC
    """, (id,))

    company = query_one("SELECT * FROM companies LIMIT 1")

    return render_template('purchases/detail.html', order=order, lines=lines, company=company, payments=payments)

@purchase_orders_bp.route('/purchases/<int:id>/receive', methods=['POST'])
def receive_goods(id):
    order = query_one("SELECT * FROM purchase_orders WHERE id = %s", (id,))
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    if order['status'] in ('RECEIVED', 'PAID'):
        flash("Purchase order has already been received. Duplicate inventory increment was prevented.", "warning")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    if order['status'] == 'CANCELLED':
        flash("Cannot receive goods for a cancelled purchase order.", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    with get_db_cursor(commit=True) as cur:
        # Fetch lines using the transaction cursor
        cur.execute("SELECT product_id, quantity, unit_cost FROM purchase_order_lines WHERE purchase_order_id = %s", (id,))
        lines = cur.fetchall()

        for l in lines:
            pid = l['product_id']
            qty = float(l['quantity'])
            cost = float(l['unit_cost'])

            # Lock product and inventory using SAME cursor
            cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s FOR UPDATE", (pid,))
            cur_p = cur.fetchone()

            cur.execute("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (pid, order['location_id']))
            cur_inv = cur.fetchone()
            old_qty = float(cur_inv['qty']) if cur_inv else 0.0

            # Increment stock in warehouse
            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES (%s, %s, '', %s)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
            """, (pid, order['location_id'], qty))

            # Recalculate moving average cost
            cur_avg = float(cur_p['average_cost'] or cost) if cur_p else cost
            new_total_qty = old_qty + qty
            if new_total_qty > 0:
                new_avg = ((old_qty * cur_avg) + (qty * cost)) / new_total_qty
            else:
                new_avg = cost

            cur.execute("""
                UPDATE products 
                SET last_purchase_cost = %s,
                    average_cost = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (cost, new_avg, pid))

            # Audit ledger
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                ) VALUES (%s, 'PO_RECEIVE', 'PO', %s, %s, %s, %s, %s, %s, 'Purchase Order Receiving');
            """, (pid, order['order_number'], order['location_id'], qty, old_qty, old_qty + qty, cost))

        # Update PO status to RECEIVED
        cur.execute("""
            UPDATE purchase_orders 
            SET status = 'RECEIVED', received_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (id,))

    flash(f"Purchase Order {order['order_number']} goods received into warehouse! Inventory updated.", "success")
    return redirect(url_for('purchase_orders.detail_purchase', id=id))

@purchase_orders_bp.route('/purchases/<int:id>/pay', methods=['POST'])
def record_payment(id):
    try:
        amount = float(request.form.get('amount', 0) or 0)
        if amount <= 0:
            flash("Payment amount must be greater than zero.", "error")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        method = request.form.get('method', 'Bank Transfer').strip()
        reference = request.form.get('reference', '').strip()
        notes = request.form.get('notes', '').strip()

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
                    order_type, order_id, amount, payment_method, reference, notes
                ) VALUES ('PO', %s, %s, %s, %s, %s);
            """, (id, amount, method, reference, notes))

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

@purchase_orders_bp.route('/purchases/<int:id>/print')
def print_po(id):
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

    lines = query_all("""
        SELECT 
            pol.*,
            p.name as product_name,
            p.sku as product_sku,
            p.uom as product_uom
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (id,))

    company = query_one("SELECT * FROM companies LIMIT 1")

    return render_template('purchases/po_print.html', order=order, lines=lines, company=company)

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
