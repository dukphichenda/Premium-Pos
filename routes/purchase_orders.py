from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val
from datetime import datetime, date

purchase_orders_bp = Blueprint('purchase_orders', __name__)

@purchase_orders_bp.route('/purchases')
def list_purchases():
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

@purchase_orders_bp.route('/purchases/create', methods=['GET', 'POST'])
def create_purchase():
    if request.method == 'GET':
        vendors = query_all("SELECT id, name, phone, email, address1, balance, payment_terms FROM vendors WHERE is_active = TRUE ORDER BY name")
        locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
        
        # Calculate preview PO number
        try:
            seq_res = query_one("SELECT last_value, is_called FROM po_number_seq;")
            if seq_res:
                next_num = seq_res['last_value'] + (1 if seq_res['is_called'] else 0)
            else:
                next_num = 1
        except Exception:
            next_num = 1
        preview_po_number = f"PO-{next_num:06d}"

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
        
        prefill_vendor_id = request.args.get('vendor_id')

        return render_template('purchases/create.html', 
                               vendors=vendors, 
                               locations=locations, 
                               prefill_prod=prefill_prod,
                               prefill_vendor_id=prefill_vendor_id,
                               preview_po_number=preview_po_number)

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
        shipping_fee = max(0.0, float(data.get('shipping_fee') or 0))
        discount_amount = max(0.0, float(data.get('discount_amount') or 0))

        if isinstance(data, dict) and 'lines' in data:
            raw_lines = data.get('lines', [])
            prod_ids = [l.get('product_id') for l in raw_lines]
            quantities = [l.get('quantity') for l in raw_lines]
            unit_costs = [l.get('unit_cost') if l.get('unit_cost') is not None else (l.get('unit_price') if l.get('unit_price') is not None else l.get('cost', 0)) for l in raw_lines]
            discounts = [l.get('discount_percent', 0) for l in raw_lines]
            descriptions = [l.get('description', '') for l in raw_lines]
        else:
            prod_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            unit_costs = request.form.getlist('unit_cost[]') or request.form.getlist('unit_price[]') or request.form.getlist('cost[]')
            discounts = request.form.getlist('discount_percent[]')
            descriptions = request.form.getlist('description[]')

        if not prod_ids:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Please add at least one line item.'}), 400
            flash("Please add at least one line item.", "error")
            return redirect(url_for('purchase_orders.create_purchase'))

        seq_val = get_next_sequence_val('po_number_seq')
        order_number = f"PO-{seq_val:06d}"

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
            
            line_sub = qty * cost * (1.0 - (disc_pct / 100.0))
            subtotal += line_sub
            lines_data.append((idx + 1, pid, desc, qty, cost, disc_pct, line_sub))

        total_amount = max(0.0, subtotal + shipping_fee - discount_amount)
        balance_due = total_amount

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO purchase_orders (
                    order_number, vendor_id, location_id, order_date, expected_date,
                    carrier, vendor_invoice_no, status, payment_status, 
                    subtotal, shipping_fee, discount_amount, total_amount, paid_amount, balance_due, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ISSUED', 'UNPAID', %s, %s, %s, %s, 0, %s, %s)
                RETURNING id;
            """, (order_number, vendor_id, location_id, order_date, expected_date, 
                  carrier, vendor_invoice_no, subtotal, shipping_fee, discount_amount, total_amount, balance_due, notes))
            po_id = cur.fetchone()['id']

            for line in lines_data:
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, quantity, unit_cost, discount_percent, subtotal, received_qty
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0);
                """, (po_id, line[0], line[1], line[2], line[3], line[4], line[5], line[6]))

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
            p.barcode as product_barcode,
            p.uom as product_uom,
            p.average_cost as product_avg_cost,
            p.last_purchase_cost as product_last_cost,
            COALESCE(inv.qty, 0) as on_hand_stock
        FROM purchase_order_lines pol
        JOIN products p ON pol.product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as qty 
            FROM inventory 
            WHERE location_id = %s
            GROUP BY product_id
        ) inv ON pol.product_id = inv.product_id
        WHERE pol.purchase_order_id = %s
        ORDER BY pol.line_num ASC
    """, (order['location_id'], id))

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

    vendors = query_all("SELECT id, name, phone, email, address1, balance, payment_terms FROM vendors WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    company = query_one("SELECT * FROM companies LIMIT 1")

    # Receiving summary
    total_qty_ordered = sum(float(l['quantity'] or 0) for l in lines)
    total_qty_received = sum(float(l['received_qty'] or 0) for l in lines)
    receiving_percent = int((total_qty_received / total_qty_ordered * 100) if total_qty_ordered > 0 else 0)

    return render_template('purchases/detail.html', 
                           order=order, 
                           lines=lines, 
                           payments=payments,
                           inventory_logs=inventory_logs,
                           vendors=vendors,
                           locations=locations,
                           company=company,
                           total_qty_ordered=total_qty_ordered,
                           total_qty_received=total_qty_received,
                           receiving_percent=receiving_percent)

@purchase_orders_bp.route('/purchases/<int:id>/update', methods=['POST'])
def update_purchase(id):
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
                SET expected_date = %s, carrier = %s, vendor_invoice_no = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (expected_date, carrier, vendor_invoice_no, notes, id))
            if is_ajax:
                return jsonify({'success': True, 'message': 'Purchase order updated successfully!'})
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

        if isinstance(data, dict) and 'lines' in data:
            raw_lines = data.get('lines', [])
            prod_ids = [l.get('product_id') for l in raw_lines]
            quantities = [l.get('quantity') for l in raw_lines]
            unit_costs = [l.get('unit_cost') for l in raw_lines]
            discounts = [l.get('discount_percent', 0) for l in raw_lines]
            descriptions = [l.get('description', '') for l in raw_lines]
        else:
            prod_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            unit_costs = request.form.getlist('unit_cost[]')
            discounts = request.form.getlist('discount_percent[]')
            descriptions = request.form.getlist('description[]')

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
            
            line_sub = qty * cost * (1.0 - (disc_pct / 100.0))
            subtotal += line_sub
            lines_data.append((idx + 1, pid, desc, qty, cost, disc_pct, line_sub))

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
                    carrier = %s, vendor_invoice_no = %s, subtotal = %s, shipping_fee = %s,
                    discount_amount = %s, total_amount = %s, balance_due = %s, payment_status = %s,
                    notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (vendor_id, location_id, order_date, expected_date, carrier, vendor_invoice_no,
                  subtotal, shipping_fee, discount_amount, total_amount, new_balance_due, new_pay_status, notes, id))

            # Preserve received_qty if lines already partially received
            cur.execute("SELECT product_id, received_qty FROM purchase_order_lines WHERE purchase_order_id = %s", (id,))
            old_lines_rcv = {r['product_id']: float(r['received_qty'] or 0) for r in cur.fetchall()}

            cur.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (id,))
            for line in lines_data:
                rcv_qty = old_lines_rcv.get(line[1], 0.0)
                cur.execute("""
                    INSERT INTO purchase_order_lines (
                        purchase_order_id, line_num, product_id, description, quantity, unit_cost, discount_percent, subtotal, received_qty
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (id, line[0], line[1], line[2], line[3], line[4], line[5], line[6], rcv_qty))

        if is_ajax:
            return jsonify({'success': True, 'message': 'Purchase order saved successfully!'})
        flash("Purchase order updated successfully!", "success")
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
        
        seq_val = get_next_sequence_val('po_number_seq')
        new_order_number = f"PO-{seq_val:06d}"
        
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
                        purchase_order_id, line_num, product_id, description, quantity, unit_cost, discount_percent, subtotal, received_qty
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0);
                """, (new_po_id, line.get('line_num') or (idx + 1), line['product_id'], line.get('description') or '', line['quantity'], line['unit_cost'], line.get('discount_percent') or 0, line['subtotal']))

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
        flash("Order not found.", "error")
        return redirect(url_for('purchase_orders.list_purchases'))

    if order['status'] in ('RECEIVED', 'PAID'):
        flash("Purchase order has already been received. Duplicate inventory increment was prevented.", "warning")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    if order['status'] == 'CANCELLED':
        flash("Cannot receive goods for a cancelled purchase order.", "error")
        return redirect(url_for('purchase_orders.detail_purchase', id=id))

    # Check if partial receiving quantities were provided
    data = request.get_json(silent=True) or request.form
    line_receives = {}
    
    if request.is_json and 'items' in data:
        for it in data['items']:
            lid = int(it.get('line_id'))
            rq = float(it.get('received_qty') or 0)
            if rq > 0:
                line_receives[lid] = rq
    else:
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
        cur.execute("SELECT id, product_id, quantity, unit_cost, received_qty FROM purchase_order_lines WHERE purchase_order_id = %s FOR UPDATE", (id,))
        lines = cur.fetchall()

        any_received = False
        all_lines_complete = True

        for l in lines:
            lid = l['id']
            pid = l['product_id']
            ordered_qty = float(l['quantity'])
            already_rcv = float(l['received_qty'] or 0)
            cost = float(l['unit_cost'])
            remaining = max(0.0, ordered_qty - already_rcv)

            if line_receives:
                qty_to_receive = min(remaining, line_receives.get(lid, 0.0))
            else:
                qty_to_receive = remaining

            if qty_to_receive > 0:
                any_received = True
                new_rcv_total = already_rcv + qty_to_receive

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
                """, (pid, order['location_id'], qty_to_receive))

                # Recalculate moving average cost
                cur_avg = float(cur_p['average_cost'] or cost) if cur_p else cost
                new_total_qty = old_qty + qty_to_receive
                if new_total_qty > 0:
                    new_avg = ((old_qty * cur_avg) + (qty_to_receive * cost)) / new_total_qty
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
                """, (pid, order['order_number'], order['location_id'], qty_to_receive, old_qty, old_qty + qty_to_receive, cost))

                # Update line received_qty
                cur.execute("UPDATE purchase_order_lines SET received_qty = %s WHERE id = %s", (new_rcv_total, lid))

                if new_rcv_total < ordered_qty:
                    all_lines_complete = False
            else:
                if already_rcv < ordered_qty:
                    all_lines_complete = False

        if not any_received:
            flash("No quantities were specified to receive.", "warning")
            return redirect(url_for('purchase_orders.detail_purchase', id=id))

        new_status = 'RECEIVED' if all_lines_complete else 'PARTIAL_RECEIVED'
        cur.execute("""
            UPDATE purchase_orders 
            SET status = %s, received_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (new_status, id))

    if all_lines_complete:
        flash(f"Purchase Order {order['order_number']} goods fully received into warehouse! Inventory updated.", "success")
    else:
        flash(f"Partial shipment for Purchase Order {order['order_number']} received! Inventory updated.", "success")

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
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip()
        address1 = (data.get('address1') or '').strip()
        payment_terms = (data.get('payment_terms') or 'Net 30').strip()

        if not name:
            return jsonify({'success': False, 'message': 'Vendor name is required.'}), 400

        # Check existing
        existing = query_one("SELECT id, name FROM vendors WHERE LOWER(name) = LOWER(%s)", (name,))
        if existing:
            return jsonify({
                'success': True,
                'vendor': {'id': existing['id'], 'name': existing['name'], 'phone': phone, 'balance': 0},
                'message': 'Vendor already exists and was selected.'
            })

        vendor_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, email, address1, payment_terms, balance, is_active)
            VALUES (%s, %s, %s, %s, %s, 0, TRUE)
            RETURNING id;
        """, (name, phone, email, address1, payment_terms))

        return jsonify({
            'success': True,
            'vendor': {
                'id': vendor_id,
                'name': name,
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
