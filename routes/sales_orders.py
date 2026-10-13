from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val
from datetime import datetime, date, timedelta
import re
from routes.auth import user_can_edit_prices, user_can_view_costs

sales_orders_bp = Blueprint('sales_orders', __name__)

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

def _get_product_bom_components(cur, product_id):
    """
    Returns list of BOM components for product_id if it's a combined product:
    [{component_product_id, quantity, component_name, unit_cost}]
    If not a combined product, returns empty list [].
    """
    if not product_id:
        return []
    cur.execute("""
        SELECT pb.component_product_id, pb.quantity, p.name as component_name,
               COALESCE(p.standard_cost, pb.cost, 0) as unit_cost
        FROM product_boms pb
        JOIN products p ON pb.component_product_id = p.id
        WHERE pb.product_id = %s
        ORDER BY pb.id ASC
    """, (product_id,))
    return cur.fetchall()

def _reserve_order_stock(cur, location_id, product_id, qty):
    """Reserves inventory: if combined kit, reserves all components; otherwise reserves product."""
    if not location_id or not product_id or qty <= 0:
        return
    comps = _get_product_bom_components(cur, product_id)
    if comps:
        for c in comps:
            c_pid = c['component_product_id']
            c_qty = qty * float(c['quantity'])
            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
                VALUES (%s, %s, '', 0, %s)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET reserved_quantity = inventory.reserved_quantity + EXCLUDED.reserved_quantity,
                              updated_at = CURRENT_TIMESTAMP;
            """, (c_pid, location_id, c_qty))
    else:
        cur.execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
            VALUES (%s, %s, '', 0, %s)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET reserved_quantity = inventory.reserved_quantity + EXCLUDED.reserved_quantity,
                          updated_at = CURRENT_TIMESTAMP;
        """, (product_id, location_id, qty))

def _unreserve_order_stock(cur, location_id, product_id, qty):
    """Releases reserved stock: if combined kit, unreserves components; otherwise unreserves product."""
    if not location_id or not product_id or qty <= 0:
        return
    comps = _get_product_bom_components(cur, product_id)
    if comps:
        for c in comps:
            c_pid = c['component_product_id']
            c_qty = qty * float(c['quantity'])
            cur.execute("""
                UPDATE inventory 
                SET reserved_quantity = GREATEST(0, reserved_quantity - %s),
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s AND location_id = %s;
            """, (c_qty, c_pid, location_id))
    else:
        cur.execute("""
            UPDATE inventory 
            SET reserved_quantity = GREATEST(0, reserved_quantity - %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE product_id = %s AND location_id = %s;
        """, (qty, product_id, location_id))

def _deduct_order_stock(cur, order, product_id, qty, product_name=None, reason_prefix="Fulfillment Shipment"):
    """
    Deducts physical stock from inventory and logs audit ledger in inventory_logs.
    If product_id is a combined kit (has product_boms), auto-deducts EACH component product!
    """
    loc_id = order.get('location_id')
    if not loc_id or not product_id or qty <= 0:
        return
    
    order_num = order.get('order_number') or f"SO-{order.get('id')}"
    p_name = product_name or 'Item'
    comps = _get_product_bom_components(cur, product_id)

    if comps:
        for c in comps:
            c_pid = c['component_product_id']
            c_name = c['component_name']
            c_unit_cost = float(c.get('unit_cost') or 0.0)
            c_qty = qty * float(c['quantity'])

            cur.execute("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (c_pid, loc_id))
            inv = cur.fetchone()
            old_q = float(inv['quantity']) if inv else 0.0

            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
                VALUES (%s, %s, '', -%s, 0)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET quantity = inventory.quantity - %s,
                              reserved_quantity = GREATEST(0, inventory.reserved_quantity - %s),
                              updated_at = CURRENT_TIMESTAMP;
            """, (c_pid, loc_id, c_qty, c_qty, c_qty))

            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    from_location_id, quantity, qty_before, qty_after, unit_cost, reason
                ) VALUES (%s, 'SALE_SHIP', 'SO', %s, %s, %s, %s, %s, %s, %s);
            """, (c_pid, order_num, loc_id, c_qty, old_q, old_q - c_qty, c_unit_cost,
                  f"{reason_prefix} (Kit Component for {p_name}: {c_name} x{c_qty:g})"))
    else:
        cur.execute("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (product_id, loc_id))
        inv = cur.fetchone()
        old_q = float(inv['quantity']) if inv else 0.0

        cur.execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
            VALUES (%s, %s, '', -%s, 0)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET quantity = inventory.quantity - %s,
                          reserved_quantity = GREATEST(0, inventory.reserved_quantity - %s),
                          updated_at = CURRENT_TIMESTAMP;
        """, (product_id, loc_id, qty, qty, qty))

        cur.execute("""
            INSERT INTO inventory_logs (
                product_id, movement_type, reference_type, reference_id,
                from_location_id, quantity, qty_before, qty_after, reason
            ) VALUES (%s, 'SALE_SHIP', 'SO', %s, %s, %s, %s, %s, %s);
        """, (product_id, order_num, loc_id, qty, old_q, old_q - qty, f"{reason_prefix} for {p_name}"))

def _revert_order_stock(cur, location_id, product_id, qty, was_shipped=False):
    """
    Reverts stock:
    If was_shipped=True: adds back quantity and re-reserves (or restores physical stock).
    If was_shipped=False: unreserves reserved_quantity.
    Handles components if product is a combined kit.
    """
    if not location_id or not product_id or qty <= 0:
        return
    comps = _get_product_bom_components(cur, product_id)
    if comps:
        for c in comps:
            c_pid = c['component_product_id']
            c_qty = qty * float(c['quantity'])
            if was_shipped:
                cur.execute("""
                    UPDATE inventory
                    SET quantity = quantity + %s,
                        reserved_quantity = reserved_quantity + %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = %s AND location_id = %s
                """, (c_qty, c_qty, c_pid, location_id))
            else:
                cur.execute("""
                    UPDATE inventory
                    SET reserved_quantity = GREATEST(0, reserved_quantity - %s),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = %s AND location_id = %s
                """, (c_qty, c_pid, location_id))
    else:
        if was_shipped:
            cur.execute("""
                UPDATE inventory
                SET quantity = quantity + %s,
                    reserved_quantity = reserved_quantity + %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s AND location_id = %s
            """, (qty, qty, product_id, location_id))
        else:
            cur.execute("""
                UPDATE inventory
                SET reserved_quantity = GREATEST(0, reserved_quantity - %s),
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s AND location_id = %s
            """, (qty, product_id, location_id))

@sales_orders_bp.route('/sales')
def list_orders():
    view_mode = request.args.get('view', '').strip()
    session_branch_id = session.get('active_branch_id')
    raw_branch = request.args.get('branch')
    if raw_branch is not None:
        branch_filter = raw_branch.strip().lower()
    elif session_branch_id:
        branch_filter = str(session_branch_id)
    else:
        branch_filter = 'main'

    if view_mode != 'table' and not request.args.get('search') and not request.args.get('status') and not request.args.get('page') and raw_branch is None:
        if session_branch_id:
            latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (int(session_branch_id),))
        else:
            latest = query_one("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 1")
        if latest:
            return redirect(url_for('sales_orders.detail_order', id=latest['id'], branch=branch_filter))

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    offset = (page - 1) * per_page

    status = request.args.get('status', '').strip()
    payment_status = request.args.get('payment_status', '').strip()
    search = request.args.get('search', '').strip()
    customer_id = request.args.get('customer_id', '').strip()

    where_clauses = ["1=1"]
    params = []

    # Branch isolation: Main store orders (branch_id IS NULL) are kept strictly separate from branch orders
    if branch_filter == 'main':
        where_clauses.append("so.branch_id IS NULL")
    elif branch_filter == 'all':
        pass  # Show all combined (Main HQ enterprise overview)
    else:
        try:
            b_id = int(branch_filter)
            where_clauses.append("so.branch_id = %s")
            params.append(b_id)
        except ValueError:
            where_clauses.append("so.branch_id IS NULL")
            branch_filter = 'main'

    if status:
        st_upper = status.strip().upper()
        if st_upper in ('PAID', 'INVOICED'):
            where_clauses.append("(UPPER(so.status) IN ('PAID', 'INVOICED') OR (UPPER(so.payment_status) = 'PAID' AND UPPER(so.status) NOT IN ('OPEN', 'CANCELLED', 'QUOTE')))")
        elif st_upper == 'OPEN':
            where_clauses.append("UPPER(so.status) = 'OPEN'")
        elif st_upper in ('FULLY SHIPPED', 'SHIPPED'):
            where_clauses.append("UPPER(so.status) IN ('FULLY SHIPPED', 'SHIPPED')")
        elif st_upper in ('IN_PROGRESS', 'IN PROGRESS'):
            where_clauses.append("UPPER(so.status) IN ('IN_PROGRESS', 'PICKED', 'PACKED')")
        elif st_upper == 'CANCELLED':
            where_clauses.append("UPPER(so.status) = 'CANCELLED'")
        elif st_upper == 'QUOTE':
            where_clauses.append("UPPER(so.status) = 'QUOTE'")
        else:
            where_clauses.append("UPPER(so.status) = %s")
            params.append(st_upper)

    if payment_status:
        where_clauses.append("UPPER(so.payment_status) = %s")
        params.append(payment_status.strip().upper())

    if customer_id:
        where_clauses.append("so.customer_id = %s")
        params.append(int(customer_id))

    if search:
        where_clauses.append("(so.order_number ILIKE %s OR c.name ILIKE %s OR c.phone ILIKE %s OR so.delivery_man ILIKE %s OR so.delivery_helper ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp, sp, sp])

    where_sql = " AND ".join(where_clauses)

    count_sql = f"""
        SELECT COUNT(*) as cnt 
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE {where_sql}
    """
    total_count = query_one(count_sql, tuple(params))['cnt']
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    list_sql = f"""
        SELECT 
            so.id, so.order_number, so.order_date, so.due_date,
            so.status, so.payment_status,
            so.total_amount, so.paid_amount, so.balance_due,
            so.sales_rep, so.tracking_number, so.branch_id,
            so.payment_method, so.completed_by,
            b.name as branch_name, b.code as branch_code,
            c.name as customer_name,
            c.phone as customer_phone,
            l.name as location_name,
            COUNT(sol.id) as line_count
        FROM sales_orders so
        LEFT JOIN branches b ON so.branch_id = b.id
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        LEFT JOIN sales_order_lines sol ON so.id = sol.sales_order_id
        WHERE {where_sql}
        GROUP BY so.id, b.name, b.code, c.name, c.phone, l.name, so.payment_method, so.completed_by
        ORDER BY so.order_date DESC, so.id DESC
        LIMIT %s OFFSET %s
    """
    rows_params = params.copy()
    rows_params.extend([per_page, offset])
    orders = query_all(list_sql, tuple(rows_params))

    # Summary counts by status scoped to the active store/branch filter
    status_where = ["1=1"]
    status_p = []
    if branch_filter == 'main':
        status_where.append("branch_id IS NULL")
    elif branch_filter != 'all':
        try:
            b_id = int(branch_filter)
            status_where.append("branch_id = %s")
            status_p.append(b_id)
        except ValueError:
            status_where.append("branch_id IS NULL")

    status_sql = f"""
        SELECT UPPER(status) as norm_status, COUNT(*) as cnt
        FROM sales_orders
        WHERE {' AND '.join(status_where)}
        GROUP BY norm_status
    """
    status_counts = query_all(status_sql, tuple(status_p))
    stats_dict = {r['norm_status']: r['cnt'] for r in status_counts}

    branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")

    return render_template('sales/list.html',
                           orders=orders,
                           status=status,
                           payment_status=payment_status,
                           search=search,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           stats_dict=stats_dict,
                           branches=branches,
                           branch_filter=branch_filter)

@sales_orders_bp.route('/sales/create', methods=['GET', 'POST'])
def create_order():
    if request.method == 'GET':
        customers = query_all("SELECT id, name, phone, discount_percent FROM customers WHERE is_active = TRUE ORDER BY name LIMIT 500")
        locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
        return render_template('sales/create.html', customers=customers, locations=locations)

    try:
        customer_id = int(request.form.get('customer_id'))
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
        notes = request.form.get('notes', '').strip()
        sales_rep = request.form.get('sales_rep', '').strip()
        discount_amount = max(0.0, float(request.form.get('discount_amount', 0) or 0))
        shipping_fee = max(0.0, float(request.form.get('shipping_fee', 0) or 0))
        tax_rate = max(0.0, min(100.0, float(request.form.get('tax_rate', 0) or 0)))

        # Parse line items from form
        prod_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')
        discounts = request.form.getlist('discount_percent[]')
        descriptions = request.form.getlist('description[]')
        addon_pids = request.form.getlist('addon_product_id[]')
        addon_qtys = request.form.getlist('addon_quantity[]')
        combine_opt_ids = request.form.getlist('combine_option_id[]')

        if not prod_ids:
            flash("Please add at least one line item.", "error")
            return redirect(url_for('sales_orders.create_order'))

        # Generate unique order number using database sequence
        seq_val = get_next_sequence_val('so_number_seq')
        order_number = f"SO-{seq_val:06d}"

        # Calculate totals & validate items
        subtotal = 0.0
        lines_data = []

        for idx in range(len(prod_ids)):
            pid = int(prod_ids[idx])
            qty = max(0.0001, float(quantities[idx] or 1))
            price = max(0.0, float(unit_prices[idx] or 0))
            disc = max(0.0, min(100.0, float(discounts[idx] or 0))) if idx < len(discounts) else 0.0
            desc = descriptions[idx] if idx < len(descriptions) else ''
            
            addon_pid = None
            if idx < len(addon_pids) and addon_pids[idx] and str(addon_pids[idx]).strip() not in ('', '0', 'None', 'null'):
                try:
                    addon_pid = int(addon_pids[idx])
                except (ValueError, TypeError):
                    addon_pid = None
            addon_qty = float(addon_qtys[idx] or 1.0) if idx < len(addon_qtys) and addon_qtys[idx] else 1.0
            combine_opt_id = None
            if idx < len(combine_opt_ids) and combine_opt_ids[idx] and str(combine_opt_ids[idx]).strip() not in ('', '0', 'None', 'null'):
                try:
                    combine_opt_id = int(combine_opt_ids[idx])
                except (ValueError, TypeError):
                    combine_opt_id = None

            line_sub = (qty * price) * (1.0 - (disc / 100.0))

            if not user_can_edit_prices():
                p_info = query_one("SELECT default_price FROM products WHERE id = %s", (pid,))
                if p_info:
                    price = float(p_info['default_price'] or 0.0)
                disc = 0.0
                line_sub = qty * price

            subtotal += line_sub

            # Get product cost
            cost_row = query_one("SELECT average_cost, standard_cost FROM products WHERE id = %s", (pid,))
            cost_price = float(cost_row['average_cost'] or cost_row['standard_cost'] or 0) if cost_row else 0.0

            lines_data.append((idx + 1, pid, desc, qty, price, disc, line_sub, cost_price, addon_pid, addon_qty, combine_opt_id))

        tax_amount = (subtotal - discount_amount) * (tax_rate / 100.0) if tax_rate > 0 else 0.0
        total_amount = max(0.0, subtotal - discount_amount + tax_amount + shipping_fee)
        balance_due = total_amount

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sales_orders (
                    order_number, customer_id, location_id, order_date,
                    status, payment_status, subtotal, tax_rate, tax_amount,
                    discount_amount, shipping_fee, total_amount, paid_amount, balance_due,
                    sales_rep, notes
                ) VALUES (%s, %s, %s, %s, 'OPEN', 'UNPAID', %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                RETURNING id;
            """, (
                order_number, customer_id, location_id, order_date,
                subtotal, tax_rate, tax_amount,
                discount_amount, shipping_fee, total_amount, balance_due,
                sales_rep, notes
            ))
            order_id = cur.fetchone()['id']

            for line in lines_data:
                cur.execute("""
                    INSERT INTO sales_order_lines (
                        sales_order_id, line_num, product_id, description,
                        quantity, unit_price, discount_percent, subtotal, cost_price,
                        addon_product_id, addon_quantity, combine_option_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (order_id, line[0], line[1], line[2], line[3], line[4], line[5], line[6], line[7], line[8], line[9], line[10]))

                # Reserve inventory (auto-reserves components if combined kit)
                if location_id:
                    _reserve_order_stock(cur, location_id, line[1], line[3])

                    # Also reserve inventory for add-on product if present
                    if line[8]:
                        addon_tot = line[3] * line[9]
                        _reserve_order_stock(cur, location_id, line[8], addon_tot)

            # Update customer balance
            cur.execute("""
                UPDATE customers 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (balance_due, customer_id))

        flash(f"Sales Order {order_number} created successfully!", "success")
        return redirect(url_for('sales_orders.detail_order', id=order_id))

    except Exception as e:
        flash(f"Error creating order: {e}", "error")
        return redirect(url_for('sales_orders.create_order'))

def _get_drawer_and_metadata(date_filter='All', status_filter='Open, In Progress, Paid', customer_search='', customer_filter=None, scheme_id=100, branch_id=None):
    drawer_where = ["1=1"]
    drawer_params = []

    # Branch isolation: drawer sidebar strictly isolates branch orders vs main store orders
    if branch_id is None or str(branch_id).lower() == 'main':
        drawer_where.append("so.branch_id IS NULL")
    elif str(branch_id).lower() == 'all':
        pass
    else:
        try:
            bid = int(branch_id)
            drawer_where.append("so.branch_id = %s")
            drawer_params.append(bid)
        except (ValueError, TypeError):
            drawer_where.append("so.branch_id IS NULL")

    # Filter drawer orders
    if customer_search:
        drawer_where.append("(c.name ILIKE %s OR c.contact_name ILIKE %s)")
        sp = f"%{customer_search}%"
        drawer_params.extend([sp, sp])
    elif customer_filter and customer_filter != 'all':
        try:
            drawer_where.append("so.customer_id = %s")
            drawer_params.append(int(customer_filter))
        except (ValueError, TypeError):
            pass

    # Date filter presets (matching inFlow Desktop Recording_20261008_1053)
    if date_filter == 'Today':
        drawer_where.append("so.order_date = CURRENT_DATE")
    elif date_filter == 'This Week':
        drawer_where.append("date_trunc('week', so.order_date::timestamp) = date_trunc('week', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Month':
        drawer_where.append("date_trunc('month', so.order_date::timestamp) = date_trunc('month', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Quarter':
        drawer_where.append("date_trunc('quarter', so.order_date::timestamp) = date_trunc('quarter', CURRENT_DATE::timestamp)")
    elif date_filter == 'This Year':
        drawer_where.append("date_trunc('year', so.order_date::timestamp) = date_trunc('year', CURRENT_DATE::timestamp)")
    elif date_filter == 'Yesterday':
        drawer_where.append("so.order_date = CURRENT_DATE - INTERVAL '1 day'")
    elif date_filter == 'Last Week':
        drawer_where.append("date_trunc('week', so.order_date::timestamp) = date_trunc('week', CURRENT_DATE::timestamp - INTERVAL '1 week')")
    elif date_filter == 'Last Month':
        drawer_where.append("date_trunc('month', so.order_date::timestamp) = date_trunc('month', CURRENT_DATE::timestamp - INTERVAL '1 month')")
    elif date_filter == 'Last Quarter':
        drawer_where.append("date_trunc('quarter', so.order_date::timestamp) = date_trunc('quarter', CURRENT_DATE::timestamp - INTERVAL '3 months')")
    elif date_filter == 'Last Year':
        drawer_where.append("date_trunc('year', so.order_date::timestamp) = date_trunc('year', CURRENT_DATE::timestamp - INTERVAL '1 year')")
    elif date_filter == 'Last 7 Days':
        drawer_where.append("so.order_date >= CURRENT_DATE - INTERVAL '7 days' AND so.order_date <= CURRENT_DATE")
    elif date_filter == 'Last 30 Days':
        drawer_where.append("so.order_date >= CURRENT_DATE - INTERVAL '30 days' AND so.order_date <= CURRENT_DATE")

    # Status filter (supports multi-select comma separated statuses)
    if status_filter and status_filter.strip() and status_filter.strip().lower() != 'all':
        tokens = [t.strip().lower() for t in status_filter.split(',') if t.strip()]
        status_clauses = []
        for token in tokens:
            if token == 'quote':
                status_clauses.append("UPPER(so.status) = 'QUOTE'")
            elif token == 'open':
                status_clauses.append("UPPER(so.status) = 'OPEN'")
            elif token in ('in progress', 'in_progress'):
                status_clauses.append("UPPER(so.status) IN ('IN_PROGRESS', 'PICKED', 'PACKED')")
            elif token in ('fully shipped', 'shipped'):
                status_clauses.append("UPPER(so.status) = 'SHIPPED'")
            elif token == 'invoiced':
                status_clauses.append("UPPER(so.status) IN ('INVOICED', 'PAID')")
            elif token == 'paid':
                status_clauses.append("(UPPER(so.status) IN ('PAID', 'INVOICED') OR (UPPER(so.payment_status) = 'PAID' AND UPPER(so.status) NOT IN ('OPEN', 'CANCELLED', 'QUOTE')))")
            elif token == 'cancelled':
                status_clauses.append("UPPER(so.status) = 'CANCELLED'")
            elif token == 'completed':
                status_clauses.append("UPPER(so.status) IN ('SHIPPED', 'INVOICED', 'PAID')")
            elif token == 'all':
                status_clauses = []
                break
        if status_clauses:
            drawer_where.append("(" + " OR ".join(status_clauses) + ")")

    # Exclude phantom empty orders with no customer and 0 total
    drawer_where.append("NOT (so.customer_id IS NULL AND so.total_amount = 0)")

    drawer_sql = f"""
        SELECT 
            so.id, 
            so.order_number, 
            so.order_date, 
            CASE 
                WHEN UPPER(so.status) = 'CANCELLED' THEN 'Cancelled'
                WHEN UPPER(so.status) = 'QUOTE' THEN 'Quote'
                WHEN UPPER(so.status) IN ('IN_PROGRESS', 'PICKED', 'PACKED') THEN 'In Progress'
                WHEN UPPER(so.status) = 'SHIPPED' THEN 'Fully Shipped'
                WHEN UPPER(so.status) = 'OPEN' THEN 'Open'
                WHEN UPPER(so.status) IN ('PAID', 'INVOICED') OR UPPER(so.payment_status) = 'PAID' THEN 'Paid'
                ELSE 'Open'
            END as status, 
            COALESCE(so.po_number, '') as po_number,
            so.shipped_date,
            COALESCE(so.total_amount, 0) as total_amount, 
            COALESCE(so.paid_amount, 0) as paid_amount, 
            COALESCE(so.balance_due, 0) as balance_due, 
            COALESCE(so.payment_method, '') as payment_method,
            COALESCE(so.completed_by, '') as completed_by,
            COALESCE(so.delivery_man, '') as delivery_man,
            COALESCE(so.delivery_fee_khr, 0) as delivery_fee_khr,
            COALESCE(c.name, 'N/A') as customer_name,
            COALESCE(l.name, '') as location_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE {' AND '.join(drawer_where)}
        ORDER BY so.id DESC
        LIMIT 100
    """
    sidebar_orders = query_all(drawer_sql, tuple(drawer_params))

    all_customers = query_all("""
        SELECT 
            id, name, contact_name, phone, 
            COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as customer_address,
            COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as address1,
            balance 
        FROM customers 
        WHERE is_active = TRUE 
        ORDER BY name ASC
    """)
    all_locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY id")
    pricing_schemes = query_all("SELECT id, name, is_active FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")
    if not pricing_schemes:
        pricing_schemes = query_all("SELECT id, name, is_active FROM pricing_schemes ORDER BY id")

    # Build complete mapping of {product_id: {scheme_id: unit_price}}
    all_prices = query_all("SELECT product_id, pricing_scheme_id, unit_price FROM product_prices")
    product_prices_map = {}
    for pr in all_prices:
        pid = pr['product_id']
        if pid not in product_prices_map:
            product_prices_map[pid] = {}
        product_prices_map[pid][pr['pricing_scheme_id']] = float(pr['unit_price'] or 0)

    all_products = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.description, 
            COALESCE(p.uom, 'pcs.') as uom,
            COALESCE(p.sales_uom, '') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_uom_ratio_std,
            COALESCE(p.purchasing_uom, '') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, 1.0) as purchasing_uom_ratio_std,
            COALESCE(c.name, 'GENERAL') as category_name,
            COALESCE(pp.unit_price, p.default_price, 0) as price,
            p.price_decimals,
            COALESCE(SUM(inv.quantity), 0) as stock_on_hand,
            COALESCE(SUM(inv.reserved_quantity), 0) as stock_reserved
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN product_prices pp ON p.id = pp.product_id AND pp.pricing_scheme_id = %s
        LEFT JOIN inventory inv ON p.id = inv.product_id
        WHERE p.is_active = TRUE
        GROUP BY p.id, c.name, pp.unit_price, p.default_price, p.price_decimals
        ORDER BY p.sku ASC
    """, (scheme_id,))

    company = query_one("SELECT * FROM companies LIMIT 1")
    all_branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")
    all_delivery_men = query_all("SELECT id, name, phone FROM delivery_men WHERE is_active = TRUE ORDER BY name ASC")

    return {
        'sidebar_orders': sidebar_orders,
        'all_customers': all_customers,
        'all_locations': all_locations,
        'pricing_schemes': pricing_schemes,
        'all_products': all_products,
        'product_prices_map': product_prices_map,
        'company': company,
        'all_branches': all_branches,
        'all_delivery_men': all_delivery_men,
        'active_branch_filter': branch_id or 'main'
    }

@sales_orders_bp.route('/sales/delivery_men', methods=['GET'], endpoint='list_delivery_men')
@sales_orders_bp.route('/sales/delivery_men_json', methods=['GET'], endpoint='get_delivery_men')
def list_delivery_men():
    # Detect if caller specifically wants JSON (e.g. AJAX autocomplete or drawer)
    wants_json = (
        request.args.get('format') == 'json' or 
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 
        request.is_json
    )
    if wants_json:
        men = query_all("SELECT id, name, phone, is_active FROM delivery_men WHERE is_active = TRUE ORDER BY name ASC")
        return jsonify({'success': True, 'delivery_men': men})

    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'all').strip().lower()
    period = request.args.get('period', 'all').strip().lower()
    start_date_param = request.args.get('start_date', '').strip()
    end_date_param = request.args.get('end_date', '').strip()

    today = date.today()
    filter_start_date = None
    filter_end_date = None
    period_label = "All Time (Lifetime)"

    if period == 'today':
        filter_start_date = today
        filter_end_date = today
        period_label = f"Today ({today.strftime('%d %b %Y')})"
    elif period == 'yesterday':
        filter_start_date = today - timedelta(days=1)
        filter_end_date = filter_start_date
        period_label = f"Yesterday ({filter_start_date.strftime('%d %b %Y')})"
    elif period == 'this_week':
        filter_start_date = today - timedelta(days=today.weekday())
        filter_end_date = today
        period_label = f"This Week ({filter_start_date.strftime('%d %b')} – {filter_end_date.strftime('%d %b %Y')})"
    elif period == 'this_month':
        filter_start_date = today.replace(day=1)
        filter_end_date = today
        period_label = f"This Month ({today.strftime('%B %Y')})"
    elif period == 'last_month':
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        filter_start_date = last_prev_month.replace(day=1)
        filter_end_date = last_prev_month
        period_label = f"Last Month ({filter_start_date.strftime('%B %Y')})"
    elif period == 'this_year':
        filter_start_date = today.replace(month=1, day=1)
        filter_end_date = today
        period_label = f"This Year ({today.year})"
    elif period == 'custom' or start_date_param or end_date_param:
        period = 'custom'
        try:
            if start_date_param:
                filter_start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            if end_date_param:
                filter_end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
            elif filter_start_date:
                # If only start_date is provided (e.g. single day selection), filter for that exact day
                filter_end_date = filter_start_date

            if filter_start_date and filter_end_date:
                if filter_start_date == filter_end_date:
                    period_label = f"Date: {filter_start_date.strftime('%d %b %Y')}"
                else:
                    period_label = f"{filter_start_date.strftime('%d %b %Y')} to {filter_end_date.strftime('%d %b %Y')}"
            elif filter_start_date:
                period_label = f"From {filter_start_date.strftime('%d %b %Y')}"
            elif filter_end_date:
                period_label = f"Up to {filter_end_date.strftime('%d %b %Y')}"
        except (ValueError, TypeError):
            filter_start_date = None
            filter_end_date = None
            period = 'all'
            period_label = "All Time (Lifetime)"
    else:
        period = 'all'
        period_label = "All Time (Lifetime)"

    # Query all delivery personnel
    all_dm = query_all("SELECT id, name, phone, is_active, created_at FROM delivery_men ORDER BY is_active DESC, name ASC")
    active_names = [dm['name'] for dm in all_dm if dm['is_active']]
    if not active_names:
        active_names = [dm['name'] for dm in all_dm]

    name_to_dm = {dm['name']: dm for dm in all_dm}
    stats_by_id = {
        dm['id']: {
            'total_orders': 0,
            'completed_orders': 0,
            'fee_khr': 0.0,
            'shared_orders': 0,
            'last_delivery_date': None
        } for dm in all_dm
    }

    # Query sales orders within time period
    order_query = """
        SELECT 
            so.id, 
            so.order_number, 
            so.order_date, 
            so.status, 
            so.delivery_man, 
            so.delivery_helper, 
            COALESCE(so.delivery_fee_khr, 0) as delivery_fee_khr
        FROM sales_orders so
        WHERE UPPER(so.status) != 'CANCELLED'
    """
    order_params = []
    if filter_start_date:
        order_query += " AND so.order_date >= %s"
        order_params.append(filter_start_date)
    if filter_end_date:
        order_query += " AND so.order_date <= %s"
        order_params.append(filter_end_date)

    order_query += " ORDER BY so.order_date DESC, so.id DESC"
    all_period_orders = query_all(order_query, tuple(order_params))

    total_period_fee_khr = 0.0
    total_period_delivered_orders = set()

    for o in all_period_orders:
        fee = float(o['delivery_fee_khr'] or 0)
        status_upper = (o['status'] or '').upper()
        is_completed = status_upper in ('COMPLETED', 'SHIPPED', 'DELIVERED', 'INVOICED', 'PAID')
        o_date = o['order_date']

        raw_man = (o['delivery_man'] or '').strip()
        raw_helper = (o['delivery_helper'] or '').strip()

        if not raw_man and not raw_helper and fee <= 0:
            continue

        participants = []
        is_all = False
        if raw_man.upper() in ('ALL', 'ALL DELIVERY PERSONS', 'ALL ACTIVE'):
            is_all = True
            participants = list(active_names)
        else:
            if ',' in raw_man:
                parts = [p.strip() for p in raw_man.split(',') if p.strip()]
                participants.extend(parts)
            elif raw_man:
                participants.append(raw_man)

        if raw_helper and raw_helper not in participants:
            participants.append(raw_helper)

        # Deduplicate participants
        unique_participants = []
        for p in participants:
            if p and p not in unique_participants:
                unique_participants.append(p)

        if unique_participants:
            total_period_delivered_orders.add(o['id'])
            total_period_fee_khr += fee
            num_p = len(unique_participants)
            split_fee = fee / num_p if num_p > 0 else fee

            for p_name in unique_participants:
                dm = name_to_dm.get(p_name)
                if dm:
                    dm_id = dm['id']
                    stats_by_id[dm_id]['total_orders'] += 1
                    if is_completed:
                        stats_by_id[dm_id]['completed_orders'] += 1
                    stats_by_id[dm_id]['fee_khr'] += split_fee
                    if num_p > 1 or is_all:
                        stats_by_id[dm_id]['shared_orders'] += 1
                    if o_date:
                        cur_last = stats_by_id[dm_id]['last_delivery_date']
                        if cur_last is None or o_date > cur_last:
                            stats_by_id[dm_id]['last_delivery_date'] = o_date
        elif fee > 0:
            # Order has delivery fee charged without specific delivery man
            total_period_fee_khr += fee
            total_period_delivered_orders.add(o['id'])

    # Build final list
    delivery_men = []
    for dm in all_dm:
        if search:
            s_low = search.lower()
            if s_low not in dm['name'].lower() and s_low not in (dm['phone'] or '').lower():
                continue
        if status_filter == 'active' and not dm['is_active']:
            continue
        if status_filter == 'inactive' and dm['is_active']:
            continue

        dm_stats = stats_by_id.get(dm['id'], {})
        dm_copy = dict(dm)
        dm_copy['total_orders'] = dm_stats.get('total_orders', 0)
        dm_copy['completed_orders'] = dm_stats.get('completed_orders', 0)
        dm_copy['total_fee_khr'] = int(round(dm_stats.get('fee_khr', 0.0)))
        dm_copy['shared_orders'] = dm_stats.get('shared_orders', 0)
        dm_copy['last_delivery_date'] = dm_stats.get('last_delivery_date')
        delivery_men.append(dm_copy)

    # Sort: active first, then highest fee earned in period, then name
    delivery_men.sort(key=lambda d: (not d['is_active'], -d['total_fee_khr'], d['name']))

    stats = {
        'total': len(all_dm),
        'active': len([d for d in all_dm if d['is_active']]),
        'inactive': len([d for d in all_dm if not d['is_active']]),
        'total_deliveries': len(total_period_delivered_orders),
        'total_fees_khr': int(round(total_period_fee_khr)),
        'period': period,
        'period_label': period_label,
        'start_date': filter_start_date.strftime('%Y-%m-%d') if filter_start_date else '',
        'end_date': filter_end_date.strftime('%Y-%m-%d') if filter_end_date else '',
    }

    return render_template('sales/delivery_men.html',
                           delivery_men=delivery_men,
                           stats=stats,
                           search=search,
                           status_filter=status_filter)

@sales_orders_bp.route('/sales/delivery_men/add', methods=['POST'])
def add_delivery_man():
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    
    if 'is_active' in data:
        is_active = True if data.get('is_active') in (True, '1', 'true', 'on', 'yes') else False
    else:
        is_active = True

    if not name:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Delivery person name is required.'}), 400
        flash('Delivery person name is required.', 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

    try:
        execute("""
            INSERT INTO delivery_men (name, phone, is_active)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE 
            SET is_active = EXCLUDED.is_active, 
                phone = COALESCE(NULLIF(EXCLUDED.phone, ''), delivery_men.phone);
        """, (name, phone or None, is_active))
        row = query_one("SELECT id, name, phone, is_active FROM delivery_men WHERE name = %s", (name,))
        if is_ajax:
            return jsonify({'success': True, 'message': f"Delivery person '{name}' saved successfully.", 'delivery_man': row})
        flash(f"Delivery person '{name}' added successfully.", 'success')
        return redirect(url_for('sales_orders.list_delivery_men'))
    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error saving delivery person: {str(e)}", 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

@sales_orders_bp.route('/sales/delivery_men/add_ajax', methods=['POST'])
def add_delivery_man_ajax():
    return add_delivery_man()

@sales_orders_bp.route('/sales/delivery_men/<int:id>/edit', methods=['POST'])
def edit_delivery_man(id):
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    is_active = True if data.get('is_active') in (True, '1', 'true', 'on', 'yes') else False

    if not name:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Delivery person name cannot be empty.'}), 400
        flash('Delivery person name cannot be empty.', 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

    existing = query_one("SELECT * FROM delivery_men WHERE id = %s", (id,))
    if not existing:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Delivery person not found.'}), 404
        flash('Delivery person not found.', 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

    old_name = existing['name']
    try:
        execute("""
            UPDATE delivery_men 
            SET name = %s, phone = %s, is_active = %s 
            WHERE id = %s
        """, (name, phone or None, is_active, id))

        if old_name != name:
            execute("UPDATE sales_orders SET delivery_man = %s WHERE delivery_man = %s", (name, old_name))
            execute("UPDATE sales_orders SET delivery_helper = %s WHERE delivery_helper = %s", (name, old_name))

        if is_ajax:
            return jsonify({'success': True, 'message': f"Updated {name}."})
        flash(f"Delivery person '{name}' updated successfully.", 'success')
        return redirect(url_for('sales_orders.list_delivery_men'))
    except Exception as e:
        if is_ajax:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error updating delivery person: {str(e)}", 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

@sales_orders_bp.route('/sales/delivery_men/<int:id>/toggle', methods=['POST'])
def toggle_delivery_man(id):
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    dm = query_one("SELECT * FROM delivery_men WHERE id = %s", (id,))
    if not dm:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Delivery person not found.'}), 404
        flash('Delivery person not found.', 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

    new_status = not dm['is_active']
    execute("UPDATE delivery_men SET is_active = %s WHERE id = %s", (new_status, id))
    status_label = 'Activated' if new_status else 'Deactivated'

    if is_ajax:
        return jsonify({'success': True, 'is_active': new_status, 'message': f"{dm['name']} {status_label.lower()}."})
    flash(f"Delivery person '{dm['name']}' has been {status_label.lower()}.", 'info')
    return redirect(url_for('sales_orders.list_delivery_men'))

@sales_orders_bp.route('/sales/delivery_men/<int:id>/delete', methods=['POST'])
def delete_delivery_man(id):
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    dm = query_one("SELECT * FROM delivery_men WHERE id = %s", (id,))
    if not dm:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Delivery person not found.'}), 404
        flash('Delivery person not found.', 'danger')
        return redirect(url_for('sales_orders.list_delivery_men'))

    used_count = query_one("""
        SELECT COUNT(*) as cnt 
        FROM sales_orders 
        WHERE delivery_man = %s OR delivery_helper = %s
    """, (dm['name'], dm['name']))['cnt']

    if used_count > 0:
        execute("UPDATE delivery_men SET is_active = FALSE WHERE id = %s", (id,))
        msg = f"'{dm['name']}' has {used_count} past sales order(s). Deactivated instead of permanently deleted to protect order records."
        if is_ajax:
            return jsonify({'success': True, 'deactivated': True, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('sales_orders.list_delivery_men'))
    else:
        execute("DELETE FROM delivery_men WHERE id = %s", (id,))
        msg = f"Delivery person '{dm['name']}' deleted successfully."
        if is_ajax:
            return jsonify({'success': True, 'deleted': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('sales_orders.list_delivery_men'))

@sales_orders_bp.route('/sales/new')
def new_order():
    # Resolve active branch context
    branch_param = request.args.get('branch')
    session_branch_id = session.get('active_branch_id')
    branch_id = None
    if session_branch_id:
        try:
            branch_id = int(session_branch_id)
        except (ValueError, TypeError):
            branch_id = None
    elif branch_param:
        if str(branch_param).lower() not in ('main', 'all', 'none', '') and str(branch_param).isdigit():
            branch_id = int(branch_param)

    branch = query_one("SELECT * FROM branches WHERE id = %s", (branch_id,)) if branch_id else None

    # Shared Central fulfillment warehouse (Location 100)
    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    default_loc = central_wh or query_one("SELECT id, name FROM locations LIMIT 1")
    default_loc_id = default_loc['id'] if default_loc else 100
    default_loc_name = default_loc['name'] if default_loc else 'Main Warehouse'

    from datetime import date
    copy_from_id = request.args.get('copy_from')
    is_copied_draft = False
    lines = []

    if copy_from_id and copy_from_id.isdigit():
        source_order = query_one("""
            SELECT 
                so.*,
                b.name as branch_name,
                b.code as branch_code,
                c.name as customer_name,
                COALESCE(NULLIF(so.customer_contact, ''), NULLIF(c.contact_name, ''), '') as customer_contact,
                COALESCE(NULLIF(so.customer_phone, ''), NULLIF(c.phone, ''), '') as customer_phone,
                c.email as customer_email,
                COALESCE(NULLIF(so.customer_address, ''), NULLIF(c.shipping_address, ''), NULLIF(c.address1, ''), NULLIF(c.billing_address, ''), NULLIF(c.address2, ''), '') as customer_address,
                c.city as customer_city,
                c.balance as customer_balance,
                c.payment_terms as customer_payment_terms,
                l.name as location_name,
                ps.name as pricing_scheme_name
            FROM sales_orders so
            LEFT JOIN branches b ON so.branch_id = b.id
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN locations l ON so.location_id = l.id
            LEFT JOIN pricing_schemes ps ON so.pricing_scheme_id = ps.id
            WHERE so.id = %s
        """, (int(copy_from_id),))

        if source_order:
            is_copied_draft = True
            order = dict(source_order)
            order['id'] = 0
            order['order_number'] = ''  # Unsaved in-memory draft!
            order['branch_id'] = branch['id'] if branch else source_order.get('branch_id')
            order['branch_name'] = branch['name'] if branch else source_order.get('branch_name')
            order['branch_code'] = branch['code'] if branch else source_order.get('branch_code')
            order['status'] = 'Open'
            order['payment_status'] = 'UNPAID'
            order['paid_amount'] = 0.0
            order['balance_due'] = float(source_order.get('total_amount') or 0.0)
            order['order_date'] = date.today()

            import re
            raw_notes = (order.get('notes') or '').strip()
            order['notes'] = re.sub(r'^Copied from SO-\d+(\.\s*)?', '', raw_notes).strip()

            lines = query_all("""
                SELECT 
                    sol.*,
                    COALESCE(sol.pricing_scheme_id, so.pricing_scheme_id, 100) as pricing_scheme_id,
                    p.name as product_name,
                    p.sku as product_sku,
                    COALESCE(p.combine_type, 'single') as product_combine_type,
                    COALESCE(p.uom, 'pcs.') as base_uom,
                    COALESCE(p.sales_uom, '') as sales_uom,
                    COALESCE(p.sales_uom_ratio_std, 1.0) as sales_uom_ratio_std,
                    COALESCE(p.purchasing_uom, '') as purchasing_uom,
                    COALESCE(p.purchasing_uom_ratio_std, 1.0) as purchasing_uom_ratio_std,
                    COALESCE(sol.uom, p.uom, 'pcs.') as display_uom,
                    COALESCE(sol.quantity_display, sol.quantity, 1) as display_qty,
                    COALESCE(inv.quantity, 0) as stock_on_hand,
                    COALESCE(inv.reserved_quantity, 0) as stock_reserved,
                    (COALESCE(inv.quantity, 0) - COALESCE(inv.reserved_quantity, 0)) as stock_available,
                    COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as description,
                    addon_p.name as addon_product_name,
                    addon_p.sku as addon_product_sku,
                    addon_p.default_price as addon_default_price,
                    pco.option_name as combine_option_name
                FROM sales_order_lines sol
                JOIN products p ON sol.product_id = p.id
                LEFT JOIN sales_orders so ON sol.sales_order_id = so.id
                LEFT JOIN inventory inv ON p.id = inv.product_id AND inv.location_id = %s
                LEFT JOIN products addon_p ON sol.addon_product_id = addon_p.id
                LEFT JOIN product_combine_options pco ON sol.combine_option_id = pco.id
                WHERE sol.sales_order_id = %s
                ORDER BY sol.line_num ASC
            """, (order.get('location_id') or default_loc_id, int(copy_from_id)))
        else:
            order = {
                'id': 0,
                'order_number': '',
                'branch_id': branch['id'] if branch else None,
                'branch_name': branch['name'] if branch else '',
                'branch_code': branch['code'] if branch else '',
                'customer_id': None,
                'customer_name': '',
                'customer_contact': '',
                'customer_phone': '',
                'customer_email': '',
                'customer_address': '',
                'customer_city': '',
                'customer_balance': 0.0,
                'customer_payment_terms': 'Due on Receipt',
                'location_id': default_loc_id,
                'location_name': default_loc_name,
                'order_date': date.today(),
                'status': 'Open',
                'payment_status': 'UNPAID',
                'subtotal': 0.0,
                'tax_rate': 0.0,
                'tax_amount': 0.0,
                'discount_amount': 0.0,
                'shipping_fee': 0.0,
                'total_amount': 0.0,
                'paid_amount': 0.0,
                'balance_due': 0.0,
                'sales_rep': (branch.get('manager_name') if branch else '') or '',
                'po_number': '',
                'carrier': '',
                'tracking_number': '',
                'destination_province': '',
                'package_count': 1,
                'delivery_man': source_order.get('delivery_man') or '' if source_order else '',
                'delivery_helper': source_order.get('delivery_helper') or '' if source_order else '',
                'delivery_fee_khr': source_order.get('delivery_fee_khr') or 0 if source_order else 0,
                'delivery_notes': source_order.get('delivery_notes') or '' if source_order else '',
                'payment_method': source_order.get('payment_method') or '' if source_order else '',
                'cod_amount': 0.0,
                'notes': '',
                'pricing_scheme_id': 100,
                'pricing_scheme_name': 'Retail 1'
            }
    else:
        order = {
            'id': 0,
            'order_number': '',  # Blank as in inFlow recording until Save
            'branch_id': branch['id'] if branch else None,
            'branch_name': branch['name'] if branch else '',
            'branch_code': branch['code'] if branch else '',
            'customer_id': None,
            'customer_name': '',
            'customer_contact': '',
            'customer_phone': '',
            'customer_email': '',
            'customer_address': '',
            'customer_city': '',
            'customer_balance': 0.0,
            'customer_payment_terms': 'Due on Receipt',
            'location_id': default_loc_id,
            'location_name': default_loc_name,
            'order_date': date.today(),
            'status': 'Open',
            'payment_status': 'UNPAID',
            'subtotal': 0.0,
            'tax_rate': 0.0,
            'tax_amount': 0.0,
            'discount_amount': 0.0,
            'shipping_fee': 0.0,
            'total_amount': 0.0,
            'paid_amount': 0.0,
            'balance_due': 0.0,
            'sales_rep': (branch.get('manager_name') if branch else '') or '',
            'po_number': '',
            'carrier': '',
            'tracking_number': '',
            'destination_province': '',
            'package_count': 1,
            'delivery_man': '',
            'delivery_helper': '',
            'delivery_fee_khr': 0,
            'delivery_notes': '',
            'payment_method': '',
            'cod_amount': 0.0,
            'notes': '',
            'pricing_scheme_id': 100,
            'pricing_scheme_name': 'Retail 1'
        }

    target_cust_id = request.args.get('customer_id')
    if target_cust_id and str(target_cust_id).isdigit():
        cust_row = query_one("""
            SELECT *, 
                   COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as display_address
            FROM customers WHERE id = %s
        """, (int(target_cust_id),))
        if cust_row:
            order['customer_id'] = cust_row['id']
            order['customer_name'] = cust_row['name']
            order['customer_contact'] = cust_row.get('contact_name') or ''
            order['customer_phone'] = cust_row.get('phone') or ''
            order['customer_email'] = cust_row.get('email') or ''
            order['customer_address'] = cust_row.get('display_address') or ''
            order['customer_city'] = cust_row.get('city') or ''
            order['customer_balance'] = float(cust_row.get('balance') or 0.0)
            order['customer_payment_terms'] = cust_row.get('payment_terms') or 'Due on Receipt'
            if cust_row.get('default_pricing_scheme_id'):
                order['pricing_scheme_id'] = cust_row['default_pricing_scheme_id']

    if 'date_filter' in request.args:
        date_filter = request.args.get('date_filter', 'All')
        session['so_date_filter'] = date_filter
    elif 'so_date_filter' in session:
        date_filter = session['so_date_filter']
    else:
        date_filter = 'All'

    if 'status_filter' in request.args:
        status_filter = request.args.get('status_filter', 'Open, In Progress, Paid')
        session['so_status_filter'] = status_filter
    elif 'so_status_filter' in session:
        status_filter = session['so_status_filter']
    else:
        status_filter = 'Open, In Progress, Paid'

    if 'customer_search' in request.args:
        customer_search = request.args.get('customer_search', '').strip()
        session['so_customer_search'] = customer_search
    elif 'so_customer_search' in session:
        customer_search = session.get('so_customer_search', '')
    else:
        customer_search = ''

    customer_filter = request.args.get('customer_id')

    if branch:
        req_branch = str(branch['id'])
    elif 'branch' in request.args:
        req_branch = request.args.get('branch') or 'main'
        session['so_branch_filter'] = req_branch
    elif 'so_branch_filter' in session:
        req_branch = session['so_branch_filter']
    else:
        req_branch = 'main'
    scheme_id = order.get('pricing_scheme_id') or 100
    drawer_data = _get_drawer_and_metadata(date_filter, status_filter, customer_search, customer_filter, scheme_id=scheme_id, branch_id=req_branch)

    for l in lines:
        l['is_backordered'] = (float(l['stock_on_hand'] or 0) < float(l['quantity'] or 0))
        pid = l['product_id']
        ps_id = l.get('pricing_scheme_id') or scheme_id or 100
        l['case_price'] = drawer_data['product_prices_map'].get(pid, {}).get(ps_id, float(l['unit_price'] or 0))

    return render_template('sales/detail.html',
                           order=order,
                           lines=lines,
                           sidebar_orders=drawer_data['sidebar_orders'],
                           date_filter=date_filter,
                           status_filter=status_filter,
                           customer_search=customer_search,
                           customer_filter=customer_filter,
                           branch_scope=req_branch,
                           all_branches=drawer_data['all_branches'],
                           all_customers=drawer_data['all_customers'],
                           all_locations=drawer_data['all_locations'],
                           pricing_schemes=drawer_data['pricing_schemes'],
                           all_products=drawer_data['all_products'],
                           product_prices_map=drawer_data['product_prices_map'],
                           all_delivery_men=drawer_data['all_delivery_men'],
                           order_payment_method='',
                           payments=[],
                           company=drawer_data['company'],
                           is_paid=False,
                           is_new=True,
                           is_copied_draft=is_copied_draft,
                           current_branch=branch,
                           is_branch_order=bool(branch))

@sales_orders_bp.route('/sales/<int:id>')
def detail_order(id):
    order = query_one("""
        SELECT 
            so.*,
            b.name as branch_name,
            b.code as branch_code,
            c.name as customer_name,
            COALESCE(NULLIF(so.customer_contact, ''), NULLIF(c.contact_name, ''), '') as customer_contact,
            COALESCE(NULLIF(so.customer_phone, ''), NULLIF(c.phone, ''), '') as customer_phone,
            c.email as customer_email,
            COALESCE(NULLIF(so.customer_address, ''), NULLIF(c.shipping_address, ''), NULLIF(c.address1, ''), NULLIF(c.billing_address, ''), NULLIF(c.address2, ''), '') as customer_address,
            c.city as customer_city,
            c.balance as customer_balance,
            c.payment_terms as customer_payment_terms,
            l.name as location_name,
            ps.name as pricing_scheme_name
        FROM sales_orders so
        LEFT JOIN branches b ON so.branch_id = b.id
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        LEFT JOIN pricing_schemes ps ON so.pricing_scheme_id = ps.id
        WHERE so.id = %s
    """, (id,))

    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    session_bid = session.get('active_branch_id')
    if session_bid:
        try:
            s_bid = int(session_bid)
            if order.get('branch_id') != s_bid:
                flash("You do not have permission to view orders from another store or Main Store.", "warning")
                return redirect(url_for('branches.branch_orders', id=s_bid))
        except (ValueError, TypeError):
            pass

    lines = query_all("""
        SELECT 
            sol.*,
            COALESCE(sol.pricing_scheme_id, so.pricing_scheme_id, 100) as pricing_scheme_id,
            p.name as product_name,
            p.sku as product_sku,
            COALESCE(p.combine_type, 'single') as product_combine_type,
            COALESCE(p.uom, 'pcs.') as base_uom,
            COALESCE(p.sales_uom, '') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_uom_ratio_std,
            COALESCE(p.purchasing_uom, '') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, 1.0) as purchasing_uom_ratio_std,
            COALESCE(sol.uom, p.uom, 'pcs.') as display_uom,
            COALESCE(sol.quantity_display, sol.quantity, 1) as display_qty,
            COALESCE(inv.quantity, 0) as stock_on_hand,
            COALESCE(inv.reserved_quantity, 0) as stock_reserved,
            (COALESCE(inv.quantity, 0) - COALESCE(inv.reserved_quantity, 0)) as stock_available,
            COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as description,
            addon_p.name as addon_product_name,
            addon_p.sku as addon_product_sku,
            addon_p.default_price as addon_default_price,
            pco.option_name as combine_option_name
        FROM sales_order_lines sol
        JOIN products p ON sol.product_id = p.id
        LEFT JOIN sales_orders so ON sol.sales_order_id = so.id
        LEFT JOIN inventory inv ON p.id = inv.product_id AND inv.location_id = %s
        LEFT JOIN products addon_p ON sol.addon_product_id = addon_p.id
        LEFT JOIN product_combine_options pco ON sol.combine_option_id = pco.id
        WHERE sol.sales_order_id = %s
        ORDER BY sol.line_num ASC
    """, (order['location_id'], id))

    if 'date_filter' in request.args:
        date_filter = request.args.get('date_filter', 'All')
        session['so_date_filter'] = date_filter
    elif 'so_date_filter' in session:
        date_filter = session['so_date_filter']
    else:
        date_filter = 'All'

    if 'status_filter' in request.args:
        status_filter = request.args.get('status_filter', 'Open, In Progress, Paid')
        session['so_status_filter'] = status_filter
    elif 'so_status_filter' in session:
        status_filter = session['so_status_filter']
    else:
        status_filter = 'Open, In Progress, Paid'

    if 'customer_search' in request.args:
        customer_search = request.args.get('customer_search', '').strip()
        session['so_customer_search'] = customer_search
    elif 'so_customer_search' in session:
        customer_search = session.get('so_customer_search', '')
    else:
        customer_search = ''

    customer_filter = request.args.get('customer_id')

    # Allow user to switch branch filter in drawer or default to the order's branch scope
    if session_bid:
        branch_scope = str(session_bid)
    elif 'branch' in request.args:
        branch_scope = request.args.get('branch') or 'main'
        session['so_branch_filter'] = branch_scope
    elif 'so_branch_filter' in session:
        branch_scope = session['so_branch_filter']
    else:
        default_branch = str(order['branch_id']) if order.get('branch_id') else 'main'
        branch_scope = default_branch

    scheme_id = order.get('pricing_scheme_id') or 100
    drawer_data = _get_drawer_and_metadata(date_filter, status_filter, customer_search, customer_filter, scheme_id=scheme_id, branch_id=branch_scope)

    # Mark backorder flag if stock is insufficient and resolve case price / display UOM
    for l in lines:
        l['is_backordered'] = (float(l['stock_on_hand'] or 0) < float(l['quantity'] or 0))
        pid = l['product_id']
        ps_id = l.get('pricing_scheme_id') or scheme_id or 100
        l['case_price'] = drawer_data['product_prices_map'].get(pid, {}).get(ps_id, float(l['unit_price'] or 0))

        # Self-heal legacy display UOM if missing or generic
        suom = (l.get('sales_uom') or '').strip()
        sratio = float(l.get('sales_uom_ratio_std') or 1.0)
        curr_uom = (l.get('display_uom') or '').strip()
        if suom and sratio > 1:
            if not curr_uom or curr_uom.lower() in ('pcs', 'pcs.', ''):
                case_pr = float(l['case_price'] or 0)
                unit_pr = float(l.get('unit_price') or 0)
                qty = float(l.get('quantity') or 0)
                disp_q = float(l.get('display_qty') or 0)
                if case_pr > 0 and abs(unit_pr - case_pr) < (case_pr * 0.15):
                    l['display_uom'] = suom
                    if disp_q == qty and qty >= sratio and (qty % sratio == 0):
                        l['display_qty'] = qty / sratio
            elif _match_uom(curr_uom, suom):
                l['display_uom'] = suom

    # Payment receipts history
    payments = query_all("""
        SELECT * FROM order_payments 
        WHERE order_type = 'SO' AND order_id = %s 
        ORDER BY payment_date DESC, id DESC
    """, (id,))

    st_norm = str(order.get('status') or '').strip().upper()
    pay_norm = str(order.get('payment_status') or '').strip().upper()
    is_paid = (
        st_norm in ('PAID', 'INVOICED') or
        (st_norm not in ('OPEN', 'CANCELLED', 'QUOTE') and pay_norm == 'PAID')
    )

    branch_obj = query_one("SELECT * FROM branches WHERE id = %s", (order['branch_id'],)) if order.get('branch_id') else None
    order_payment_method = (order.get('payment_method') or (payments[0]['payment_method'] if payments else '') or '').strip()

    return render_template('sales/detail.html',
                           order=order,
                           lines=lines,
                           sidebar_orders=drawer_data['sidebar_orders'],
                           date_filter=date_filter,
                           status_filter=status_filter,
                           customer_search=customer_search,
                           customer_filter=customer_filter,
                           branch_scope=branch_scope,
                           all_branches=drawer_data['all_branches'],
                           all_customers=drawer_data['all_customers'],
                           all_locations=drawer_data['all_locations'],
                           pricing_schemes=drawer_data['pricing_schemes'],
                           all_products=drawer_data['all_products'],
                           product_prices_map=drawer_data['product_prices_map'],
                           all_delivery_men=drawer_data['all_delivery_men'],
                           order_payment_method=order_payment_method,
                           company=drawer_data['company'],
                           payments=payments,
                           is_paid=is_paid,
                           is_new=False,
                           current_branch=branch_obj,
                           is_branch_order=bool(branch_obj))

@sales_orders_bp.route('/sales/<int:id>/save', methods=['POST'])
@sales_orders_bp.route('/sales/new/save', methods=['POST'])
def save_order(id=0):
    is_new = (id == 0)
    order = None
    if not is_new:
        order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
        if not order:
            if request.is_json:
                return jsonify({'error': 'Order not found'}), 404
            flash("Order not found.", "error")
            return redirect(url_for('sales_orders.list_orders'))

    is_already_completed = False
    if not is_new and order:
        st_val = str(order.get('status') or '').strip().upper()
        pay_val = str(order.get('payment_status') or '').strip().upper()
        is_already_completed = (st_val in ('PAID', 'FULLY SHIPPED', 'INVOICED')) or (st_val not in ('CANCELLED', 'QUOTE') and pay_val == 'PAID')

    data = request.get_json(silent=True) or request.form

    try:
        customer_id = int(data.get('customer_id') or (order['customer_id'] if order else 0) or 0) or None
        location_id = int(data.get('location_id') or (order['location_id'] if order else 0) or 0) or None
        
        raw_date = data.get('order_date')
        from datetime import datetime as dt_parser, date
        order_date = (order['order_date'] if order else date.today())
        if raw_date:
            for fmt in ('%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
                try:
                    order_date = dt_parser.strptime(str(raw_date).strip(), fmt).date()
                    break
                except (ValueError, TypeError):
                    pass

        sales_rep = (data.get('sales_rep') or (order['sales_rep'] if order else '') or '').strip()
        
        # When notes are submitted, use submitted value (allowing empty string to delete notes!)
        if 'notes' in data:
            notes = str(data.get('notes') or '').strip()
        else:
            notes = (order.get('notes') if order else '') or ''

        # When change date of the bill the previous date must add to remark
        if not is_new and order and order.get('order_date'):
            old_date = order['order_date']
            if old_date and order_date and old_date != order_date:
                old_date_str = old_date.strftime('%d-%b-%Y')
                date_note = f"Previous bill date: {old_date_str}"
                if date_note not in notes:
                    notes = f"{notes}\n{date_note}".strip() if notes else date_note

        if 'address' in data or 'customer_address' in data:
            customer_address = str(data.get('address') or data.get('customer_address') or '').strip()
        else:
            customer_address = (order.get('customer_address') if order else '') or ''

        if 'contact' in data or 'customer_contact' in data:
            customer_contact = str(data.get('contact') or data.get('customer_contact') or '').strip()
        else:
            customer_contact = (order.get('customer_contact') if order else '') or ''

        if 'phone' in data or 'customer_phone' in data:
            customer_phone = str(data.get('phone') or data.get('customer_phone') or '').strip()
        else:
            customer_phone = (order.get('customer_phone') if order else '') or ''

        pricing_scheme_id = int(data.get('pricing_scheme_id') or (order.get('pricing_scheme_id') if order else 100) or 100)
        paid_amount = float(data.get('paid_amount', (order['paid_amount'] if order else 0) or 0))
        mark_complete_pay = (str(data.get('mark_complete_pay', '0')) == '1')

        # Delivery & Payment logistics fields
        if 'delivery_man' in data:
            delivery_man = str(data.get('delivery_man') or '').strip()
            if delivery_man.lower() in ('none', '-- none (unassigned) --', 'null', ''):
                delivery_man = ''
            if not delivery_man:
                delivery_helper = ''
            elif 'delivery_helper' in data:
                delivery_helper = str(data.get('delivery_helper') or '').strip()
            else:
                delivery_helper = (order.get('delivery_helper') if order else '') or ''
        else:
            delivery_man = (order.get('delivery_man') if order else '') or ''
            delivery_helper = (order.get('delivery_helper') if order else '') or ''

        if 'delivery_notes' in data:
            delivery_notes = str(data.get('delivery_notes') or '').strip()
        else:
            delivery_notes = (order.get('delivery_notes') if order else '') or ''

        if 'delivery_fee_khr' in data:
            try:
                delivery_fee_khr = float(data.get('delivery_fee_khr') or 0)
            except (ValueError, TypeError):
                delivery_fee_khr = 0.0
        else:
            try:
                delivery_fee_khr = float((order.get('delivery_fee_khr') if order else 0) or 0)
            except (ValueError, TypeError):
                delivery_fee_khr = 0.0

        if 'payment_method' in data:
            payment_method = str(data.get('payment_method') or '').strip()
        else:
            payment_method = (order.get('payment_method') if order else '') or ''

        lines_data = data.get('lines_json') or data.get('lines')
        if isinstance(lines_data, str):
            import json
            try:
                lines_data = json.loads(lines_data)
            except Exception:
                lines_data = None

        if lines_data is None and request.form:
            import re
            lines_dict = {}
            for k, v in request.form.items():
                m = re.match(r'lines\[(\d+)\]\[(\w+)\]', k)
                if m:
                    idx, field = int(m.group(1)), m.group(2)
                    if idx not in lines_dict:
                        lines_dict[idx] = {}
                    lines_dict[idx][field] = v
                if lines_dict:
                    lines_data = [lines_dict[i] for i in sorted(lines_dict.keys())]

        # Resolve branch context
        if not is_new:
            # Existing sales orders maintain immutable branch ownership
            branch_id = order['branch_id']
        else:
            if session.get('active_branch_id'):
                try:
                    branch_id = int(session['active_branch_id'])
                except (ValueError, TypeError):
                    branch_id = None
            else:
                raw_b = data.get('branch_id') or request.form.get('branch_id') or data.get('branch') or request.form.get('branch')
                if raw_b and str(raw_b).lower() not in ('main', 'all', 'none', '') and str(raw_b).isdigit():
                    branch_id = int(raw_b)
                else:
                    branch_id = None

        with get_db_cursor(commit=True) as cur:
            # Auto-save delivery personnel into delivery_men table so they are permanently saved in the list
            candidate_names = []
            for dm_field in [delivery_man, delivery_helper]:
                if dm_field and dm_field.strip().upper() not in ('ALL', 'ALL DELIVERY PERSONS', 'ALL ACTIVE'):
                    if ',' in dm_field:
                        candidate_names.extend([p.strip() for p in dm_field.split(',') if p.strip()])
                    else:
                        candidate_names.append(dm_field.strip())

            for dm_name in candidate_names:
                if dm_name and dm_name.upper() not in ('ALL', 'ALL DELIVERY PERSONS', 'ALL ACTIVE'):
                    cur.execute("""
                        INSERT INTO delivery_men (name, is_active)
                        VALUES (%s, TRUE)
                        ON CONFLICT (name) DO UPDATE SET is_active = TRUE;
                    """, (dm_name,))

            if is_new:
                if branch_id:
                    branch = query_one("SELECT * FROM branches WHERE id = %s", (branch_id,))
                    if branch:
                        prefix = (branch.get('so_prefix') or f"SO-{branch['code']}-").strip().upper()
                        if not prefix.endswith('-'):
                            prefix += '-'
                        cur.execute(f"CREATE SEQUENCE IF NOT EXISTS so_branch_{branch_id}_seq START 1;")
                        cur.execute(f"SELECT nextval('so_branch_{branch_id}_seq') as seq;")
                        seq_val = cur.fetchone()['seq']
                        order_number = f"{prefix}{seq_val:05d}"
                    else:
                        seq_val = get_next_sequence_val('so_number_seq')
                        order_number = f"SO-{seq_val:06d}"
                else:
                    seq_val = get_next_sequence_val('so_number_seq')
                    order_number = f"SO-{seq_val:06d}"

                cur.execute("""
                    INSERT INTO sales_orders (
                        order_number, customer_id, location_id, order_date,
                        status, payment_status, subtotal, tax_rate, tax_amount,
                        discount_amount, shipping_fee, total_amount, paid_amount, balance_due,
                        sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone,
                        branch_id, delivery_man, delivery_helper, delivery_fee_khr, delivery_notes, payment_method
                    ) VALUES (%s, %s, %s, %s, 'OPEN', 'UNPAID', 0, 0, 0, 0, 0, 0, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (order_number, customer_id, location_id, order_date, sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone, branch_id, delivery_man or None, delivery_helper or None, delivery_fee_khr, delivery_notes or None, payment_method or None))
                id = cur.fetchone()['id']
            else:
                order_number = order['order_number']
                cur.execute("""
                    UPDATE sales_orders
                    SET customer_id = %s,
                        location_id = %s,
                        order_date = %s,
                        sales_rep = %s,
                        notes = %s,
                        pricing_scheme_id = %s,
                        customer_address = %s,
                        customer_contact = %s,
                        customer_phone = %s,
                        delivery_man = %s,
                        delivery_helper = %s,
                        delivery_fee_khr = %s,
                        delivery_notes = %s,
                        payment_method = COALESCE(NULLIF(%s, ''), payment_method),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (customer_id, location_id, order_date, sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone, delivery_man or None, delivery_helper or None, delivery_fee_khr, delivery_notes or None, payment_method or None, id))

            if customer_id:
                cur.execute("""
                    UPDATE customers
                    SET address1 = CASE WHEN (address1 IS NULL OR address1 = '') THEN %s ELSE address1 END,
                        shipping_address = CASE WHEN (shipping_address IS NULL OR shipping_address = '') THEN %s ELSE shipping_address END,
                        contact_name = CASE WHEN (contact_name IS NULL OR contact_name = '') THEN %s ELSE contact_name END,
                        phone = CASE WHEN (phone IS NULL OR phone = '') THEN %s ELSE phone END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (customer_address or None, customer_address or None, customer_contact or None, customer_phone or None, customer_id))

            if lines_data is not None and isinstance(lines_data, list):
                cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (id,))
                subtotal = 0.0
                for idx, item in enumerate(lines_data):
                    pid = int(item.get('product_id') or 0)
                    if not pid:
                        continue
                    desc = item.get('description', '')
                    display_qty = float(item.get('quantity', 1))
                    unit_price = float(item.get('unit_price', 0))
                    disc = float(item.get('discount_percent', 0))
                    uom = (item.get('uom') or '').strip()

                    # Look up product unit conversion ratio
                    cur.execute("""
                        SELECT uom, sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std 
                        FROM products WHERE id = %s
                    """, (pid,))
                    prow = cur.fetchone()
                    ratio = 1.0
                    if prow:
                        if uom and prow.get('sales_uom') and _match_uom(uom, prow.get('sales_uom')):
                            ratio = float(prow.get('sales_uom_ratio_std') or 1.0)
                        elif uom and prow.get('purchasing_uom') and _match_uom(uom, prow.get('purchasing_uom')):
                            ratio = float(prow.get('purchasing_uom_ratio_std') or 1.0)

                    line_scheme_id = int(item.get('pricing_scheme_id') or pricing_scheme_id or 100)

                    # Enforce official catalog/tier price if user is not authorized to edit prices
                    if not user_can_edit_prices():
                        cur.execute("""
                            SELECT COALESCE(pp.unit_price, p.default_price, 0) as official_price
                            FROM products p
                            LEFT JOIN product_prices pp ON p.id = pp.product_id AND pp.pricing_scheme_id = %s
                            WHERE p.id = %s
                        """, (line_scheme_id, pid))
                        pr_row = cur.fetchone()
                        official_case_price = float(pr_row['official_price'] or 0.0) if pr_row else 0.0
                        pcs_per_case = float(prow.get('sales_uom_ratio_std') or 1.0) if (prow and prow.get('sales_uom') and float(prow.get('sales_uom_ratio_std') or 1.0) > 1) else 1.0
                        price_per_base = official_case_price / pcs_per_case if pcs_per_case > 0 else official_case_price
                        unit_price = price_per_base * ratio
                        disc = 0.0

                    std_qty = display_qty * ratio
                    line_sub = (display_qty * unit_price) * (1.0 - (disc / 100.0))
                    subtotal += line_sub

                    addon_pid = item.get('addon_product_id')
                    addon_pid = int(addon_pid) if (addon_pid and str(addon_pid).strip() not in ('', '0', 'None', 'null')) else None
                    addon_qty = float(item.get('addon_quantity') or 1.0)
                    combine_opt_id = item.get('combine_option_id')
                    combine_opt_id = int(combine_opt_id) if (combine_opt_id and str(combine_opt_id).strip() not in ('', '0', 'None', 'null')) else None

                    cur.execute("""
                        INSERT INTO sales_order_lines (
                            sales_order_id, line_num, product_id, description,
                            quantity, unit_price, discount_percent, subtotal,
                            uom, quantity_display, pricing_scheme_id,
                            addon_product_id, addon_quantity, combine_option_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (id, idx + 1, pid, desc, std_qty, unit_price, disc, line_sub, uom, display_qty, line_scheme_id, addon_pid, addon_qty, combine_opt_id))

                    # Reserve inventory with standard quantity (auto-reserves components if combined kit)
                    # For already completed/shipped orders, inventory was already deducted upon completion.
                    if location_id and not is_already_completed:
                        _reserve_order_stock(cur, location_id, pid, std_qty)

                        # Also reserve inventory for add-on product if present
                        if addon_pid:
                            addon_tot_qty = std_qty * addon_qty
                            _reserve_order_stock(cur, location_id, addon_pid, addon_tot_qty)

                total_amount = subtotal
                if mark_complete_pay:
                    status = 'PAID'
                    payment_status = 'PAID'
                    paid_amount = total_amount
                    balance_due = 0.0
                    pay_method = payment_method or 'Cash'
                    user_login_name = session.get('username') or session.get('display_name') or 'admin'
                    cur.execute("""
                        UPDATE sales_orders
                        SET subtotal = %s, total_amount = %s, paid_amount = %s, balance_due = %s,
                            status = %s, payment_status = %s, invoiced_date = CURRENT_TIMESTAMP,
                            shipped_date = CURRENT_DATE,
                            payment_method = %s,
                            completed_by = %s
                        WHERE id = %s
                    """, (subtotal, total_amount, paid_amount, balance_due, status, payment_status, pay_method, user_login_name, id))
                    if total_amount > 0:
                        cur.execute("""
                            INSERT INTO order_payments (order_type, order_id, amount, payment_method, notes)
                            VALUES ('SO', %s, %s, %s, %s)
                        """, (id, total_amount, pay_method, f"Completed by {user_login_name}"))
                elif is_already_completed:
                    # Order was already completed: preserve completion status and synchronize paid amount if fully settled
                    status = order.get('status') or 'PAID'
                    payment_status = order.get('payment_status') or 'PAID'
                    prev_total = float(order.get('total_amount') or 0)
                    prev_paid = float(order.get('paid_amount') or 0)
                    if prev_paid >= prev_total and prev_total > 0:
                        paid_amount = total_amount
                        balance_due = 0.0
                    else:
                        paid_amount = prev_paid
                        balance_due = max(0.0, total_amount - paid_amount)

                    cur.execute("""
                        UPDATE sales_orders
                        SET subtotal = %s, total_amount = %s, paid_amount = %s, balance_due = %s,
                            status = %s, payment_status = %s
                        WHERE id = %s
                    """, (subtotal, total_amount, paid_amount, balance_due, status, payment_status, id))

                    if prev_paid >= prev_total and prev_total > 0:
                        cur.execute("""
                            UPDATE order_payments
                            SET amount = %s
                            WHERE order_type = 'SO' AND order_id = %s
                        """, (total_amount, id))
                else:
                    balance_due = max(0.0, total_amount - paid_amount)
                    cur.execute("""
                        UPDATE sales_orders
                        SET subtotal = %s, total_amount = %s, paid_amount = %s, balance_due = %s
                        WHERE id = %s
                    """, (subtotal, total_amount, paid_amount, balance_due, id))

                if is_new and customer_id and balance_due > 0:
                    cur.execute("""
                        UPDATE customers 
                        SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (balance_due, customer_id))

        cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
        date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
        status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
        branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(branch_id) if branch_id else 'main')

        session['so_date_filter'] = date_filter
        session['so_status_filter'] = status_filter
        session['so_customer_search'] = cust_search
        session['so_branch_filter'] = branch_param

        redirect_kwargs = {
            'id': id,
            'branch': branch_param,
            'date_filter': date_filter,
            'status_filter': status_filter
        }
        if cust_search:
            redirect_kwargs['customer_search'] = cust_search
        redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

        if request.is_json:
            return jsonify({'success': True, 'message': 'Saved successfully', 'order_id': id, 'order_number': order_number, 'redirect_url': redirect_url})
        flash(f"Sales Order {order_number} saved successfully!", "success")
        return redirect(redirect_url)

    except Exception as e:
        if request.is_json:
            return jsonify({'error': str(e)}), 400
        flash(f"Error saving order: {e}", "error")
        cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
        date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
        status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
        branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(branch_id) if branch_id else 'main')
        err_kwargs = {
            'branch': branch_param,
            'date_filter': date_filter,
            'status_filter': status_filter
        }
        if cust_search:
            err_kwargs['customer_search'] = cust_search
        return redirect(url_for('sales_orders.new_order', **err_kwargs) if is_new else url_for('sales_orders.detail_order', id=id, **err_kwargs))

@sales_orders_bp.route('/sales/<int:id>/complete_pay', methods=['POST'])
def complete_pay(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    data = request.get_json(silent=True) or request.form or {}
    payment_method = (data.get('payment_method') or order.get('payment_method') or 'Cash').strip()
    user_login_name = session.get('username') or session.get('display_name') or 'admin'

    total = float(order['total_amount'] or 0)
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE sales_orders
            SET status = 'PAID',
                payment_status = 'PAID',
                paid_amount = %s,
                balance_due = 0,
                payment_method = %s,
                completed_by = %s,
                shipped_date = COALESCE(shipped_date, CURRENT_DATE),
                invoiced_date = COALESCE(invoiced_date, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (total, payment_method, user_login_name, id))

        # Deduct physical inventory upon Complete & Pay (auto-deducts components if combined kit)
        cur.execute("""
            SELECT sol.product_id, sol.quantity, sol.addon_product_id, sol.addon_quantity,
                   p.name as product_name, ap.name as addon_name
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            LEFT JOIN products ap ON sol.addon_product_id = ap.id
            WHERE sol.sales_order_id = %s
        """, (id,))
        lines = cur.fetchall()
        for l in lines:
            if l['product_id']:
                qty = float(l['quantity'] or 0)
                _deduct_order_stock(cur, order, l['product_id'], qty, l.get('product_name'), "Fulfillment Complete & Pay")

                if l.get('addon_product_id'):
                    a_qty = qty * float(l.get('addon_quantity') or 1.0)
                    _deduct_order_stock(cur, order, l['addon_product_id'], a_qty, l.get('addon_name') or 'Add-on', "Fulfillment Add-on")

        rem = float(order['balance_due'] or 0)
        if rem > 0:
            cur.execute("""
                INSERT INTO order_payments (order_type, order_id, amount, payment_method, notes)
                VALUES ('SO', %s, %s, %s, %s)
            """, (id, rem, payment_method, f"Completed by {user_login_name}"))

    date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(order.get('branch_id')) if order.get('branch_id') else 'main')

    session['so_date_filter'] = date_filter
    session['so_status_filter'] = status_filter
    session['so_customer_search'] = cust_search
    session['so_branch_filter'] = branch_param

    redirect_kwargs = {
        'id': id,
        'branch': branch_param,
        'date_filter': date_filter,
        'status_filter': status_filter
    }
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search
    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

    if request.is_json:
        return jsonify({'success': True, 'message': f'Order completed and marked paid by {payment_method}!', 'payment_method': payment_method, 'redirect_url': redirect_url})

    flash(f"Order is shipped and paid by {payment_method}!", "success")
    return redirect(redirect_url)

@sales_orders_bp.route('/sales/<int:id>/reopen', methods=['POST'])
def reopen_order(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    with get_db_cursor(commit=True) as cur:
        # Reverse inventory movements: add back stock and re-reserve (handles kit components)
        cur.execute("""
            SELECT product_id, quantity, addon_product_id, addon_quantity 
            FROM sales_order_lines 
            WHERE sales_order_id = %s
        """, (id,))
        lines = cur.fetchall()
        loc_id = order['location_id']
        for l in lines:
            if loc_id and l['product_id']:
                qty = float(l['quantity'] or 0)
                _revert_order_stock(cur, loc_id, l['product_id'], qty, was_shipped=True)

                if l.get('addon_product_id'):
                    a_qty = qty * float(l.get('addon_quantity') or 1.0)
                    _revert_order_stock(cur, loc_id, l['addon_product_id'], a_qty, was_shipped=True)

        cur.execute("""
            UPDATE sales_orders
            SET status = 'OPEN',
                payment_status = 'UNPAID',
                paid_amount = 0,
                balance_due = total_amount,
                completed_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (id,))

        cur.execute("DELETE FROM order_payments WHERE order_type = 'SO' AND order_id = %s", (id,))

    date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(order.get('branch_id')) if order.get('branch_id') else 'main')

    session['so_date_filter'] = date_filter
    session['so_status_filter'] = status_filter
    session['so_customer_search'] = cust_search
    session['so_branch_filter'] = branch_param

    redirect_kwargs = {
        'id': id,
        'branch': branch_param,
        'date_filter': date_filter,
        'status_filter': status_filter
    }
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search
    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

    if request.is_json:
        return jsonify({'success': True, 'message': 'Order is Re-opened! You can now edit the order.', 'redirect_url': redirect_url})

    flash("Order is Re-opened! You can now edit the order.", "success")
    return redirect(redirect_url)

@sales_orders_bp.route('/sales/<int:id>/cancel_order', methods=['POST'])
def cancel_order_direct(id):
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE sales_orders
            SET status = 'CANCELLED',
                balance_due = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (id,))

    date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or 'main'

    session['so_date_filter'] = date_filter
    session['so_status_filter'] = status_filter
    session['so_customer_search'] = cust_search
    session['so_branch_filter'] = branch_param

    redirect_kwargs = {
        'id': id,
        'branch': branch_param,
        'date_filter': date_filter,
        'status_filter': status_filter
    }
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search
    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

    if request.is_json:
        return jsonify({'success': True, 'message': 'Order cancelled.', 'redirect_url': redirect_url})

    flash("Order cancelled.", "warning")
    return redirect(redirect_url)

@sales_orders_bp.route('/sales/<int:id>/delete', methods=['POST'])
def delete_order(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'error': 'Order not found'}), 404
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders', view='table'))

    order_number = order['order_number']
    customer_id = order['customer_id']
    balance_due = float(order.get('balance_due') or 0.0)
    location_id = order.get('location_id')
    branch_id = order.get('branch_id')
    status = (order.get('status') or '').upper()

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. Revert reserved or deducted inventory (auto-handles kit components)
            if location_id:
                cur.execute("""
                    SELECT product_id, SUM(quantity) as qty
                    FROM sales_order_lines
                    WHERE sales_order_id = %s
                    GROUP BY product_id
                """, (id,))
                for r in cur.fetchall():
                    pid, q = r['product_id'], float(r['qty'] or 0)
                    if pid and q > 0:
                        _revert_order_stock(cur, location_id, pid, q, was_shipped=(status in ('SHIPPED', 'PAID')))

                # Also revert addon products
                cur.execute("""
                    SELECT addon_product_id, SUM(quantity * COALESCE(addon_quantity, 1.0)) as qty
                    FROM sales_order_lines
                    WHERE sales_order_id = %s AND addon_product_id IS NOT NULL
                    GROUP BY addon_product_id
                """, (id,))
                for r in cur.fetchall():
                    apid, aq = r['addon_product_id'], float(r['qty'] or 0)
                    if apid and aq > 0:
                        _revert_order_stock(cur, location_id, apid, aq, was_shipped=(status in ('SHIPPED', 'PAID')))

            # 2. Revert customer balance
            if customer_id and balance_due > 0:
                cur.execute("""
                    UPDATE customers
                    SET balance = GREATEST(0, balance - %s),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (balance_due, customer_id))

            # 3. Cleanly delete order lines, payments, and the order itself
            cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (id,))
            cur.execute("DELETE FROM order_payments WHERE order_type = 'SO' AND order_id = %s", (id,))
            cur.execute("DELETE FROM sales_orders WHERE id = %s", (id,))

            # 4. Re-synchronize numbering sequence so new orders continue properly without gaps
            if branch_id:
                cur.execute(f"CREATE SEQUENCE IF NOT EXISTS so_branch_{branch_id}_seq START 1;")
                cur.execute("""
                    SELECT COALESCE(MAX(NULLIF(regexp_replace(order_number, '\\D', '', 'g'), '')::bigint), 0) as max_seq
                    FROM sales_orders
                    WHERE branch_id = %s
                """, (branch_id,))
                max_b_row = cur.fetchone()
                max_b = max_b_row['max_seq'] if max_b_row and max_b_row.get('max_seq') is not None else 0
                if max_b > 0:
                    cur.execute(f"SELECT setval('so_branch_{branch_id}_seq', %s, true);", (max_b,))
                else:
                    cur.execute(f"SELECT setval('so_branch_{branch_id}_seq', 1, false);")
            else:
                cur.execute("""
                    SELECT COALESCE(MAX(NULLIF(regexp_replace(order_number, '^SO-0*', ''), '')::bigint), 0) as max_seq
                    FROM sales_orders
                    WHERE branch_id IS NULL AND order_number ~ '^SO-\\d+';
                """)
                max_m_row = cur.fetchone()
                max_m = max_m_row['max_seq'] if max_m_row and max_m_row.get('max_seq') is not None else 0
                if max_m > 0:
                    cur.execute("SELECT setval('so_number_seq', %s, true);", (max_m,))
                else:
                    cur.execute("SELECT setval('so_number_seq', 1, false);")

        if request.is_json:
            return jsonify({'success': True, 'message': f'Order {order_number} deleted successfully.'})
        flash(f"Order {order_number} deleted successfully. Records cleaned and numbering resynchronized.", "success")
        if branch_id:
            return redirect(url_for('branches.branch_orders', id=branch_id))
        elif session.get('active_branch_id'):
            return redirect(url_for('branches.branch_orders', id=session['active_branch_id']))
        return redirect(url_for('sales_orders.list_orders', view='table', branch='main'))

    except Exception as e:
        logger.error(f"Error deleting sales order {id}: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'error': str(e)}), 500
        flash(f"Error deleting order: {e}", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

@sales_orders_bp.route('/sales/<int:id>/status', methods=['POST'])
def update_status(id):
    new_status = request.form.get('status', '').strip().upper()
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    allowed_statuses = ('PICKED', 'PACKED', 'SHIPPED', 'INVOICED', 'CANCELLED')
    if new_status not in allowed_statuses:
        flash(f"Invalid order status: '{new_status}'.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    current_status = order['status']

    # Validation: Prevent illegal transitions
    if current_status == 'CANCELLED':
        flash("Cannot update status of a cancelled order.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    if new_status == 'SHIPPED':
        if current_status in ('SHIPPED', 'INVOICED'):
            flash("Order has already been shipped. Duplicate fulfillment was prevented.", "warning")
            return redirect(url_for('sales_orders.detail_order', id=id))

    if new_status == 'CANCELLED':
        if current_status in ('SHIPPED', 'INVOICED'):
            flash("Cannot cancel an order that has already been shipped or invoiced.", "error")
            return redirect(url_for('sales_orders.detail_order', id=id))

    with get_db_cursor(commit=True) as cur:
        if new_status == 'PICKED':
            cur.execute("UPDATE sales_orders SET status = 'PICKED', picked_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
        elif new_status == 'PACKED':
            cur.execute("UPDATE sales_orders SET status = 'PACKED', packed_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
        elif new_status == 'SHIPPED':
            carrier = request.form.get('carrier', 'Express Delivery')
            tracking = request.form.get('tracking_number', '')

            # Query lines within transaction
            cur.execute("""
                SELECT sol.product_id, sol.quantity, sol.addon_product_id, sol.addon_quantity,
                       p.name as product_name, ap.name as addon_name
                FROM sales_order_lines sol
                LEFT JOIN products p ON sol.product_id = p.id
                LEFT JOIN products ap ON sol.addon_product_id = ap.id
                WHERE sol.sales_order_id = %s
            """, (id,))
            lines = cur.fetchall()

            for l in lines:
                pid = l['product_id']
                qty = float(l['quantity'])
                addon_pid = l.get('addon_product_id')
                addon_qty = qty * float(l.get('addon_quantity') or 1.0) if addon_pid else 0.0

                _deduct_order_stock(cur, order, pid, qty, l.get('product_name'), "Fulfillment Shipment")

                if addon_pid and addon_qty > 0:
                    _deduct_order_stock(cur, order, addon_pid, addon_qty, l.get('addon_name') or 'Add-on', f"Fulfillment Add-on for {l.get('product_name') or 'Item'}")

            cur.execute("""
                UPDATE sales_orders 
                SET status = 'SHIPPED', shipped_date = CURRENT_TIMESTAMP, carrier = %s, tracking_number = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (carrier, tracking, id))

        elif new_status == 'INVOICED':
            if not order['shipped_date']:
                # If not previously shipped, fulfill physical inventory and clear reserved quantity
                cur.execute("""
                    SELECT sol.product_id, sol.quantity, sol.addon_product_id, sol.addon_quantity,
                           p.name as product_name, ap.name as addon_name
                    FROM sales_order_lines sol
                    LEFT JOIN products p ON sol.product_id = p.id
                    LEFT JOIN products ap ON sol.addon_product_id = ap.id
                    WHERE sol.sales_order_id = %s
                """, (id,))
                lines = cur.fetchall()
                for l in lines:
                    pid = l['product_id']
                    qty = float(l['quantity'])
                    addon_pid = l.get('addon_product_id')
                    addon_qty = qty * float(l.get('addon_quantity') or 1.0) if addon_pid else 0.0

                    _deduct_order_stock(cur, order, pid, qty, l.get('product_name'), "Direct Invoice Fulfillment")

                    if addon_pid and addon_qty > 0:
                        _deduct_order_stock(cur, order, addon_pid, addon_qty, l.get('addon_name') or 'Add-on', f"Direct Invoice Add-on for {l.get('product_name') or 'Item'}")

                cur.execute("""
                    UPDATE sales_orders 
                    SET status = 'INVOICED', shipped_date = CURRENT_TIMESTAMP, invoiced_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (id,))
            else:
                cur.execute("""
                    UPDATE sales_orders 
                    SET status = 'INVOICED', invoiced_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (id,))

        elif new_status == 'CANCELLED':
            # Release reserved inventory (auto-unreserves components if combined kit)
            cur.execute("SELECT product_id, quantity, addon_product_id, addon_quantity FROM sales_order_lines WHERE sales_order_id = %s", (id,))
            lines = cur.fetchall()
            for l in lines:
                _unreserve_order_stock(cur, order['location_id'], l['product_id'], float(l['quantity']))

                if l.get('addon_product_id'):
                    a_qty = float(l['quantity']) * float(l.get('addon_quantity') or 1.0)
                    _unreserve_order_stock(cur, order['location_id'], l['addon_product_id'], a_qty)

            # Revert open balance from customer
            if float(order['balance_due'] or 0) > 0 and order['customer_id']:
                cur.execute("""
                    UPDATE customers
                    SET balance = GREATEST(0, balance - %s), updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (order['balance_due'], order['customer_id']))

            cur.execute("UPDATE sales_orders SET status = 'CANCELLED', balance_due = 0, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))

    date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(order.get('branch_id')) if order.get('branch_id') else 'main')

    redirect_kwargs = {
        'id': id,
        'branch': branch_param,
        'date_filter': date_filter,
        'status_filter': status_filter
    }
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search

    flash(f"Order status updated to {new_status}!", "success")
    return redirect(url_for('sales_orders.detail_order', **redirect_kwargs))

@sales_orders_bp.route('/sales/<int:id>/pay', methods=['POST'])
def record_payment(id):
    try:
        amount = float(request.form.get('amount', 0) or 0)
        if amount <= 0:
            flash("Payment amount must be greater than zero.", "error")
            return redirect(url_for('sales_orders.detail_order', id=id))

        method = request.form.get('method', 'Cash').strip()
        reference = request.form.get('reference', '').strip()
        notes = request.form.get('notes', '').strip()

        order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for('sales_orders.list_orders'))

        if order['status'] == 'CANCELLED':
            flash("Cannot record payment for a cancelled order.", "error")
            return redirect(url_for('sales_orders.detail_order', id=id))

        new_paid = float(order['paid_amount'] or 0) + amount
        new_balance = max(0.0, float(order['total_amount'] or 0) - new_paid)
        new_pay_status = 'PAID' if new_balance <= 0 else 'PARTIAL'

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE sales_orders 
                SET paid_amount = %s,
                    balance_due = %s,
                    payment_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (new_paid, new_balance, new_pay_status, id))

            cur.execute("""
                INSERT INTO order_payments (
                    order_type, order_id, amount, payment_method, reference, notes
                ) VALUES ('SO', %s, %s, %s, %s, %s);
            """, (id, amount, method, reference, notes))

            # Deduct from customer balance
            if order['customer_id']:
                cur.execute("""
                    UPDATE customers
                    SET balance = GREATEST(0, balance - %s), updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (amount, order['customer_id']))

        date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
        status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
        cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
        branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(order.get('branch_id')) if order.get('branch_id') else 'main')

        redirect_kwargs = {
            'id': id,
            'branch': branch_param,
            'date_filter': date_filter,
            'status_filter': status_filter
        }
        if cust_search:
            redirect_kwargs['customer_search'] = cust_search

        flash(f"Payment of ${amount:.2f} ({method}) recorded! Balance remaining: ${new_balance:.2f}", "success")
        return redirect(url_for('sales_orders.detail_order', **redirect_kwargs))

    except Exception as e:
        flash(f"Error recording payment: {e}", "error")
        date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
        status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
        cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
        branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or 'main'
        err_kwargs = {'id': id, 'branch': branch_param, 'date_filter': date_filter, 'status_filter': status_filter}
        if cust_search:
            err_kwargs['customer_search'] = cust_search
        return redirect(url_for('sales_orders.detail_order', **err_kwargs))

@sales_orders_bp.route('/sales/<int:id>/print')
def print_invoice(id):
    doc_type = request.args.get('type', 'invoice').lower() # invoice, pick, pack, receipt
    order = query_one("""
        SELECT 
            so.*,
            c.name as customer_name,
            COALESCE(NULLIF(so.customer_contact, ''), NULLIF(c.contact_name, ''), '') as customer_contact,
            COALESCE(NULLIF(so.customer_phone, ''), NULLIF(c.phone, ''), '') as customer_phone,
            c.email as customer_email,
            COALESCE(NULLIF(so.customer_address, ''), NULLIF(c.shipping_address, ''), NULLIF(c.address1, ''), NULLIF(c.billing_address, ''), NULLIF(c.address2, ''), '') as customer_address,
            c.city as customer_city,
            c.tax_number as customer_tax_number,
            l.name as location_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE so.id = %s
    """, (id,))

    if not order:
        return "Order not found", 404

    lines = query_all("""
        SELECT 
            sol.*,
            COALESCE(p.name, 'Item') as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            COALESCE(sol.uom, p.uom, 'ea') as product_uom,
            COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as line_description
        FROM sales_order_lines sol
        LEFT JOIN products p ON sol.product_id = p.id
        WHERE sol.sales_order_id = %s
        ORDER BY sol.line_num ASC
    """, (id,))

    company = query_one("SELECT * FROM companies LIMIT 1")
    inv_settings = query_one("SELECT * FROM invoice_settings LIMIT 1")
    if not inv_settings:
        inv_settings = {
            'font_family': 'Kantumruy Pro',
            'primary_color': '#0284C7',
            'secondary_color': '#0F172A',
            'logo_url': company.get('logo_url') if company else None,
            'shop_name_kh': 'ក្រុមហ៊ុន អ៊ិនហ្វ្លូ ត្រេឌីង (ខេមបូឌា)',
            'shop_name_en': company.get('name', 'inFlow Premium Business') if company else 'inFlow Premium Business',
            'shop_address_kh': 'រាជធានីភ្នំពេញ, ព្រះរាជាណាចក្រកម្ពុជា',
            'shop_address_en': company.get('address1', 'Phnom Penh, Cambodia') if company else 'Phnom Penh, Cambodia',
            'phone': company.get('phone', '+855 23 888 999') if company else '+855 23 888 999',
            'email': company.get('email', '') if company else '',
            'website': company.get('website', '') if company else '',
            'vat_tin': company.get('tax_number', '') if company else '',
            'invoice_title_kh': 'វិក្កយបត្រ',
            'invoice_title_en': 'INVOICE',
            'enable_khr_total': True,
            'khr_exchange_rate': 4100.00,
            'qr_code_url': '/static/uploads/invoice/sample_khqr.png',
            'bank_name': 'ABA Bank (KHQR / Bakong)',
            'account_name': 'INFLOW TRADING CO LTD',
            'account_number': '001 234 567 (USD) | 001 234 568 (KHR)',
            'payment_terms': 'ទូទាត់ភ្លាមៗ / Due on receipt',
            'footer_notes_kh': 'ទំនិញដែលបានទិញរួចមិនអាចប្តូរវិញបានទេ! សូមអរគុណចំពោះការគាំទ្ររបស់លោកអ្នក!',
            'footer_notes_en': 'Goods sold are not returnable. Thank you for your business!',
            'show_signature': True,
            'show_sku': True,
            'show_tax': True
        }

    # Branch specific invoice styles & branding override
    if order.get('branch_id'):
        branch = query_one("SELECT * FROM branches WHERE id = %s", (order['branch_id'],))
        if branch:
            if branch.get('color'):
                inv_settings['primary_color'] = branch['color']
            b_settings = branch.get('settings_json')
            if isinstance(b_settings, str):
                try:
                    b_settings = json.loads(b_settings)
                except Exception:
                    b_settings = {}
            elif not isinstance(b_settings, dict):
                b_settings = {}
            
            for k in ['template_style', 'invoice_title_kh', 'invoice_title_en', 'shop_name_kh',
                      'shop_name_en', 'shop_address_kh', 'shop_address_en', 'phone', 'email', 'website',
                      'vat_tin', 'logo_url', 'qr_code_url', 'bank_name', 'account_name',
                      'account_number', 'payment_terms', 'footer_notes_kh', 'footer_notes_en',
                      'show_signature', 'show_sku', 'show_tax', 'enable_khr_total', 'khr_exchange_rate',
                      'primary_color', 'secondary_color', 'font_family', 'paper_size',
                      'qr_size', 'qr_position', 'bank_info_size', 'bank_info_position',
                      'qr_offset_x', 'qr_offset_y', 'bank_offset_x', 'bank_offset_y']:
                if k in b_settings and b_settings[k] not in (None, ''):
                    inv_settings[k] = b_settings[k]

            if not b_settings.get('shop_name_en') and branch.get('name'):
                inv_settings['shop_name_en'] = branch['name']
            if not b_settings.get('phone') and branch.get('phone'):
                inv_settings['phone'] = branch['phone']
            if not b_settings.get('shop_address_en') and branch.get('address'):
                inv_settings['shop_address_en'] = branch['address']

    # Exchange rate (allow query parameter override if passed, e.g. ?rate=4120)
    rate_param = request.args.get('rate')
    try:
        rate = float(rate_param) if rate_param else float(inv_settings.get('khr_exchange_rate') or 4100.0)
    except (ValueError, TypeError):
        rate = float(inv_settings.get('khr_exchange_rate') or 4100.0)

    total_usd = float(order.get('total_amount') or 0.0)
    paid_usd = float(order.get('paid_amount') or 0.0)
    balance_usd = float(order.get('balance_due') or 0.0)

    # In Cambodia, KHR is typically rounded to nearest 100 Riels
    total_khr = int(round(total_usd * rate, -2))
    paid_khr = int(round(paid_usd * rate, -2))
    balance_khr = int(round(balance_usd * rate, -2))

    if doc_type == 'label':
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

        selected_carrier = request.args.get('carrier') or order.get('carrier') or (delivery_services[0]['name'] if delivery_services else 'Virak Buntham')
        package_count = max(1, int(request.args.get('packages') or order.get('package_count') or 1))
        delivery_notes = request.args.get('notes') or order.get('delivery_notes') or ''

        raw_cost = request.args.get('cost') or request.args.get('cod')
        if raw_cost is not None:
            try:
                product_cost = max(0.0, float(raw_cost))
            except (ValueError, TypeError):
                product_cost = float(order.get('total_amount') or order.get('balance_due') or 0.0)
        else:
            product_cost = float(order.get('total_amount') if order.get('total_amount') is not None else (order.get('balance_due') or 0.0))

        raw_sender = (inv_settings.get('phone') if inv_settings else None) or (company.get('phone') if company else None) or ''
        sender_phone = ''
        if raw_sender:
            sender_phone = re.split(r'[/\\;,|]', str(raw_sender))[0].strip()
        if not sender_phone:
            sender_phone = '010 264 731'

        return render_template('sales/delivery_label_print.html',
                               order=order,
                               lines=lines,
                               company=company,
                               inv_settings=inv_settings,
                               sender_phone=sender_phone,
                               delivery_services=delivery_services,
                               selected_carrier=selected_carrier,
                               package_count=package_count,
                               delivery_notes=delivery_notes,
                               product_cost=product_cost)

    return render_template('sales/invoice_print.html',
                           order=order,
                           lines=lines,
                           company=company,
                           inv_settings=inv_settings,
                           doc_type=doc_type,
                           khr_rate=rate,
                           total_khr=total_khr,
                           paid_khr=paid_khr,
                           balance_khr=balance_khr)


@sales_orders_bp.route('/api/delivery-services', methods=['GET', 'POST'])
def manage_delivery_services():
    if request.method == 'GET':
        name_filter = request.args.get('name')
        if name_filter:
            services = query_all("SELECT * FROM delivery_services WHERE is_active = TRUE AND name ILIKE %s ORDER BY id ASC", (name_filter,))
        else:
            services = query_all("SELECT * FROM delivery_services WHERE is_active = TRUE ORDER BY id ASC")
        return jsonify({'services': [dict(s) for s in services]})

    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    code = (data.get('code') or '').strip()
    phone = (data.get('phone') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    existing = query_one("SELECT id, is_active FROM delivery_services WHERE name ILIKE %s", (name,))
    if existing:
        if not existing['is_active']:
            execute("UPDATE delivery_services SET is_active = TRUE, code = %s, phone = %s WHERE id = %s", (code, phone, existing['id']))
            return jsonify({'success': True, 'id': existing['id'], 'name': name, 'message': 'Reactivated service'})
        return jsonify({'success': False, 'error': 'Delivery service already exists'}), 400

    new_id = execute_returning_id("INSERT INTO delivery_services (name, code, phone) VALUES (%s, %s, %s) RETURNING id;", (name, code, phone))
    return jsonify({'success': True, 'id': new_id, 'name': name, 'message': 'Added successfully'})


@sales_orders_bp.route('/api/delivery-services/<int:id>', methods=['DELETE', 'POST'])
def delete_delivery_service(id):
    execute("UPDATE delivery_services SET is_active = FALSE WHERE id = %s", (id,))
    return jsonify({'success': True, 'message': 'Delivery service deleted successfully'})


@sales_orders_bp.route('/sales/<int:id>/update-shipping', methods=['POST'])
def update_sales_shipping(id):
    data = request.get_json(silent=True) or request.form
    carrier = (data.get('carrier') or '').strip()
    province = (data.get('destination_province') or '').strip()
    package_count = max(1, int(data.get('package_count') or 1))
    delivery_notes = (data.get('delivery_notes') or '').strip()
    cod_amount = max(0.0, float(data.get('cod_amount') or 0.0))

    execute("""
        UPDATE sales_orders
        SET carrier = %s,
            destination_province = %s,
            package_count = %s,
            delivery_notes = %s,
            cod_amount = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (carrier, province, package_count, delivery_notes, cod_amount, id))

    return jsonify({'success': True, 'message': 'Shipping details updated'})


@sales_orders_bp.route('/sales/<int:id>/update-delivery', methods=['POST'])
def update_sales_delivery(id):
    try:
        data = request.get_json(silent=True) or request.form
        delivery_man = (data.get('delivery_man') or '').strip()
        if delivery_man.lower() in ('none', '-- none (unassigned) --', 'null', ''):
            delivery_man = ''
        delivery_fee_khr = float(data.get('delivery_fee_khr') or 0.0)
        delivery_notes = (data.get('delivery_notes') or '').strip()

        with get_db_cursor(commit=True) as cur:
            if delivery_man and delivery_man.upper() not in ('ALL', 'ALL DELIVERY PERSONS', 'ALL ACTIVE'):
                names = [p.strip() for p in delivery_man.split(',') if p.strip()] if ',' in delivery_man else [delivery_man]
                for dm_name in names:
                    if dm_name and dm_name.upper() not in ('ALL', 'ALL DELIVERY PERSONS'):
                        cur.execute("""
                            INSERT INTO delivery_men (name, is_active)
                            VALUES (%s, TRUE)
                            ON CONFLICT (name) DO UPDATE SET is_active = TRUE;
                        """, (dm_name,))

            cur.execute("""
                UPDATE sales_orders
                SET delivery_man = %s,
                    delivery_fee_khr = %s,
                    delivery_notes = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (delivery_man or None, delivery_fee_khr, delivery_notes or None, id))

        return jsonify({'success': True, 'message': 'Delivery info updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@sales_orders_bp.route('/sales/<int:id>/export')
def export_sales_order(id):
    import csv, io
    from flask import Response
    doc_type = request.args.get('type', 'invoice').lower()
    order = query_one("""
        SELECT so.*, c.name as customer_name, l.name as location_name 
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE so.id = %s
    """, (id,))
    if not order:
        return "Order not found", 404
    lines = query_all("""
        SELECT sol.*, p.sku, COALESCE(p.name, 'Item') as name,
            COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as line_description
        FROM sales_order_lines sol 
        LEFT JOIN products p ON sol.product_id = p.id 
        WHERE sol.sales_order_id = %s 
        ORDER BY sol.line_num ASC
    """, (id,))
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Order Number", order['order_number']])
    writer.writerow(["Document Type", doc_type.upper()])
    writer.writerow(["Customer", order.get('customer_name') or 'N/A'])
    writer.writerow(["Order Date", str(order.get('order_date') or '')])
    writer.writerow(["Warehouse", order.get('location_name') or ''])
    writer.writerow(["Status", order.get('status') or ''])
    writer.writerow([])
    writer.writerow(["#", "SKU", "Product Name", "Quantity", "UOM", "Unit Price", "Discount %", "Subtotal"])
    for l in lines:
        qty_val = float(l.get('quantity_display') if l.get('quantity_display') is not None else l.get('quantity', 0))
        p_name = l.get('name') or 'Item'
        desc = (l.get('line_description') or l.get('description') or '').strip()
        if desc and desc != p_name:
            if desc.startswith('(') and desc.endswith(')'):
                p_name = f"{p_name} {desc}"
            else:
                p_name = f"{p_name} ({desc})"
        writer.writerow([
            l.get('line_num', 1),
            l.get('sku', ''),
            p_name,
            qty_val,
            l.get('uom', ''),
            float(l.get('unit_price') or 0),
            float(l.get('discount_percent') or 0),
            float(l.get('subtotal') or 0)
        ])
    writer.writerow([])
    writer.writerow(["", "", "", "", "", "", "Subtotal", float(order.get('subtotal') or 0)])
    writer.writerow(["", "", "", "", "", "", "Total Amount", float(order.get('total_amount') or 0)])
    writer.writerow(["", "", "", "", "", "", "Paid Amount", float(order.get('paid_amount') or 0)])
    writer.writerow(["", "", "", "", "", "", "Balance Due", float(order.get('balance_due') or 0)])
    order_notes = (order.get('notes') or order.get('delivery_notes') or '').strip()
    if order_notes:
        writer.writerow([])
        writer.writerow(["Remarks / Notes:", order_notes])
    
    filename = f"{order['order_number']}_{doc_type}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@sales_orders_bp.route('/sales/<int:id>/copy', methods=['POST', 'GET'])
def copy_order(id):
    if request.method == 'GET':
        cust_search = request.args.get('customer_search', '').strip()
        branch_id = request.args.get('branch', '').strip()
        params = {'copy_from': id}
        if cust_search:
            params['customer_search'] = cust_search
        if branch_id:
            params['branch'] = branch_id
        return redirect(url_for('sales_orders.new_order', **params))

    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Sales order not found'}), 404
        flash("Sales order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    req_data = request.get_json(silent=True) or {}
    source_lines = query_all("SELECT * FROM sales_order_lines WHERE sales_order_id = %s ORDER BY line_num ASC", (id,))

    seq_val = get_next_sequence_val('so_number_seq')
    new_order_number = f"SO-{seq_val:06d}"

    import re
    raw_notes = (req_data.get('notes') if 'notes' in req_data else order.get('notes') or '').strip()
    cleaned_notes = re.sub(r'^Copied from SO-\d+(\.\s*)?', '', raw_notes).strip()
    combined_notes = cleaned_notes

    client_lines = req_data.get('lines')
    pricing_scheme_id = int(req_data.get('pricing_scheme_id') or order.get('pricing_scheme_id') or 100)
    customer_id = int(req_data.get('customer_id') or order.get('customer_id') or 0) or None
    location_id = int(req_data.get('location_id') or order.get('location_id') or 0) or None
    sales_rep = (req_data.get('sales_rep') if 'sales_rep' in req_data else order.get('sales_rep') or '').strip()
    branch_id = order.get('branch_id')

    subtotal = 0.0
    processed_lines = []
    lines_to_copy = client_lines if (client_lines and isinstance(client_lines, list)) else source_lines

    for idx, l in enumerate(lines_to_copy):
        pid = int(l.get('product_id') or 0)
        if not pid:
            continue
        desc = (l.get('description') or '').strip()
        # Exact unit entered
        uom = (l.get('uom') or '').strip()
        # Exact displayed quantity
        display_qty = float(l.get('quantity_display') if l.get('quantity_display') is not None else (l.get('quantity') or 1.0))
        # Exact unit price
        unit_price = float(l.get('unit_price') or 0.0)
        # Exact discount
        disc = float(l.get('discount_percent') or 0.0)
        line_scheme_id = int(l.get('pricing_scheme_id') or pricing_scheme_id or 100)
        line_sub = (display_qty * unit_price) * (1.0 - (disc / 100.0))
        subtotal += line_sub
        cost_price = float(l.get('cost_price') or 0.0)

        addon_pid = l.get('addon_product_id')
        addon_pid = int(addon_pid) if (addon_pid and str(addon_pid).strip() not in ('', '0', 'None', 'null')) else None
        addon_qty = float(l.get('addon_quantity') or 1.0)
        combine_opt_id = l.get('combine_option_id')
        combine_opt_id = int(combine_opt_id) if (combine_opt_id and str(combine_opt_id).strip() not in ('', '0', 'None', 'null')) else None

        processed_lines.append({
            'product_id': pid,
            'description': desc,
            'uom': uom,
            'display_qty': display_qty,
            'unit_price': unit_price,
            'discount_percent': disc,
            'subtotal': line_sub,
            'cost_price': cost_price,
            'pricing_scheme_id': line_scheme_id,
            'addon_product_id': addon_pid,
            'addon_quantity': addon_qty,
            'combine_option_id': combine_opt_id
        })

    tax_rate = float(order.get('tax_rate') or 0.0)
    discount_amount = float(order.get('discount_amount') or 0.0)
    shipping_fee = float(order.get('shipping_fee') or 0.0)
    tax_amount = (subtotal - discount_amount) * (tax_rate / 100.0) if tax_rate > 0 else 0.0
    total_amount = max(0.0, subtotal - discount_amount + tax_amount + shipping_fee)
    balance_due = total_amount

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO sales_orders (
                order_number, customer_id, location_id, order_date,
                status, payment_status, subtotal, tax_rate, tax_amount,
                discount_amount, shipping_fee, total_amount, paid_amount, balance_due,
                sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone,
                branch_id
            ) VALUES (
                %s, %s, %s, CURRENT_DATE,
                'OPEN', 'UNPAID', %s, %s, %s,
                %s, %s, %s, 0, %s,
                %s, %s, %s, %s, %s, %s,
                %s
            ) RETURNING id;
        """, (
            new_order_number, customer_id, location_id,
            subtotal, tax_rate, tax_amount,
            discount_amount, shipping_fee, total_amount, balance_due,
            sales_rep, combined_notes, pricing_scheme_id,
            order.get('customer_address'), order.get('customer_contact'), order.get('customer_phone'),
            branch_id
        ))
        new_order_id = cur.fetchone()['id']

        for idx, pl in enumerate(processed_lines):
            cur.execute("SELECT uom, sales_uom, sales_uom_ratio_std, purchasing_uom, purchasing_uom_ratio_std FROM products WHERE id = %s", (pl['product_id'],))
            prow = cur.fetchone()
            ratio = 1.0
            resolved_uom = pl['uom']
            if prow:
                if resolved_uom and prow.get('sales_uom') and _match_uom(resolved_uom, prow.get('sales_uom')):
                    ratio = float(prow.get('sales_uom_ratio_std') or 1.0)
                elif resolved_uom and prow.get('purchasing_uom') and _match_uom(resolved_uom, prow.get('purchasing_uom')):
                    ratio = float(prow.get('purchasing_uom_ratio_std') or 1.0)
                elif not resolved_uom and prow.get('uom'):
                    resolved_uom = prow.get('uom')

            std_qty = pl['display_qty'] * ratio

            cur.execute("""
                INSERT INTO sales_order_lines (
                    sales_order_id, line_num, product_id, description,
                    quantity, unit_price, discount_percent, subtotal, cost_price,
                    pricing_scheme_id, quantity_display, uom,
                    addon_product_id, addon_quantity, combine_option_id
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s
                );
            """, (
                new_order_id, idx + 1, pl['product_id'], pl['description'],
                std_qty, pl['unit_price'], pl['discount_percent'],
                pl['subtotal'], pl['cost_price'],
                pl['pricing_scheme_id'], pl['display_qty'], resolved_uom,
                pl.get('addon_product_id'), pl.get('addon_quantity', 1.0), pl.get('combine_option_id')
            ))

            if pl['product_id'] and location_id:
                cur.execute("""
                    INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
                    VALUES (%s, %s, '', 0, %s)
                    ON CONFLICT (product_id, location_id, sublocation)
                    DO UPDATE SET reserved_quantity = inventory.reserved_quantity + EXCLUDED.reserved_quantity,
                                  updated_at = CURRENT_TIMESTAMP;
                """, (pl['product_id'], location_id, std_qty))

                if pl.get('addon_product_id'):
                    a_std_qty = std_qty * float(pl.get('addon_quantity') or 1.0)
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
                        VALUES (%s, %s, '', 0, %s)
                        ON CONFLICT (product_id, location_id, sublocation)
                        DO UPDATE SET reserved_quantity = inventory.reserved_quantity + EXCLUDED.reserved_quantity,
                                      updated_at = CURRENT_TIMESTAMP;
                    """, (pl['addon_product_id'], location_id, a_std_qty))

        if customer_id and balance_due > 0:
            cur.execute("""
                UPDATE customers 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (balance_due, customer_id))

    cust_search = request.args.get('customer_search') or (req_data.get('customer_search') if req_data else '') or ''
    branch_scope_param = str(branch_id) if branch_id else 'main'
    redirect_kwargs = {'id': new_order_id}
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search
    if branch_scope_param:
        redirect_kwargs['branch'] = branch_scope_param
    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'order_id': new_order_id,
            'order_number': new_order_number,
            'redirect_url': redirect_url,
            'message': f"Sales Order copied as {new_order_number}."
        })
    flash(f"Sales Order duplicated successfully as {new_order_number}!", "success")
    return redirect(redirect_url)


@sales_orders_bp.route('/sales/<int:id>/create-po', methods=['POST', 'GET'])
def create_po_from_sales(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Sales order not found'}), 404
        flash("Sales order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    lines = query_all("""
        SELECT sol.*, p.last_vendor_id, p.standard_cost, p.average_cost, p.last_purchase_cost, p.name as product_name 
        FROM sales_order_lines sol 
        LEFT JOIN products p ON sol.product_id = p.id 
        WHERE sol.sales_order_id = %s 
        ORDER BY sol.line_num ASC
    """, (id,))

    if not lines:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Sales order has no line items to convert to a Purchase Order.'}), 400
        flash("Sales order has no line items to convert to a Purchase Order.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    vendor_id = None
    for l in lines:
        if l.get('last_vendor_id'):
            vendor_id = l['last_vendor_id']
            break
    if not vendor_id:
        v = query_one("SELECT id FROM vendors WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        if v:
            vendor_id = v['id']
    if not vendor_id:
        if request.is_json:
            return jsonify({'success': False, 'error': 'No active vendor found. Please create a vendor first.'}), 400
        flash("No active vendor found. Please create a vendor first.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    seq_val = get_next_sequence_val('po_number_seq')
    po_number = f"PO-{seq_val:06d}"

    location_id = order.get('location_id')
    if not location_id:
        loc = query_one("SELECT id FROM locations WHERE is_active = TRUE ORDER BY is_default DESC, id ASC LIMIT 1")
        location_id = loc['id'] if loc else 1

    subtotal = 0.0
    po_lines = []
    for l in lines:
        qty = float(l.get('quantity') or 1)
        cost = float(l.get('last_purchase_cost') or l.get('standard_cost') or l.get('average_cost') or l.get('cost_price') or 0.0)
        line_sub = qty * cost
        subtotal += line_sub
        desc = l.get('description') or l.get('product_name') or ''
        po_lines.append({
            'product_id': l['product_id'],
            'description': desc,
            'quantity': qty,
            'unit_cost': cost,
            'subtotal': line_sub
        })

    total_amount = subtotal
    balance_due = total_amount
    po_notes = f"Generated from Sales Order {order['order_number']}"

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO purchase_orders (
                order_number, vendor_id, location_id, order_date, expected_date,
                status, payment_status, subtotal, shipping_fee, total_amount, paid_amount, balance_due, notes
            ) VALUES (
                %s, %s, %s, CURRENT_DATE, NULL,
                'ISSUED', 'UNPAID', %s, 0, %s, 0, %s, %s
            ) RETURNING id;
        """, (po_number, vendor_id, location_id, subtotal, total_amount, balance_due, po_notes))
        po_id = cur.fetchone()['id']

        for idx, pl in enumerate(po_lines):
            cur.execute("""
                INSERT INTO purchase_order_lines (
                    purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (po_id, idx + 1, pl['product_id'], pl['description'], pl['quantity'], pl['unit_cost'], pl['subtotal']))

        if balance_due > 0:
            cur.execute("""
                UPDATE vendors 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (balance_due, vendor_id))

    redirect_url = url_for('purchase_orders.detail_purchase', id=po_id)
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'po_id': po_id,
            'order_number': po_number,
            'redirect_url': redirect_url,
            'message': f"Purchase Order {po_number} created from {order['order_number']}."
        })
    flash(f"Purchase Order {po_number} created successfully from {order['order_number']}!", "success")
    return redirect(redirect_url)


@sales_orders_bp.route('/sales/<int:id>/create-dropship-po', methods=['POST', 'GET'])
def create_dropship_po_from_sales(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Sales order not found'}), 404
        flash("Sales order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    lines = query_all("""
        SELECT sol.*, p.last_vendor_id, p.standard_cost, p.average_cost, p.last_purchase_cost, p.name as product_name 
        FROM sales_order_lines sol 
        LEFT JOIN products p ON sol.product_id = p.id 
        WHERE sol.sales_order_id = %s 
        ORDER BY sol.line_num ASC
    """, (id,))

    if not lines:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Sales order has no line items to convert to a Dropship Purchase Order.'}), 400
        flash("Sales order has no line items to convert to a Dropship Purchase Order.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    vendor_id = None
    for l in lines:
        if l.get('last_vendor_id'):
            vendor_id = l['last_vendor_id']
            break
    if not vendor_id:
        v = query_one("SELECT id FROM vendors WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        if v:
            vendor_id = v['id']
    if not vendor_id:
        if request.is_json:
            return jsonify({'success': False, 'error': 'No active vendor found. Please create a vendor first.'}), 400
        flash("No active vendor found. Please create a vendor first.", "error")
        return redirect(url_for('sales_orders.detail_order', id=id))

    seq_val = get_next_sequence_val('po_number_seq')
    po_number = f"PO-{seq_val:06d}"

    location_id = order.get('location_id')
    if not location_id:
        loc = query_one("SELECT id FROM locations WHERE is_active = TRUE ORDER BY is_default DESC, id ASC LIMIT 1")
        location_id = loc['id'] if loc else 1

    subtotal = 0.0
    po_lines = []
    for l in lines:
        qty = float(l.get('quantity') or 1)
        cost = float(l.get('last_purchase_cost') or l.get('standard_cost') or l.get('average_cost') or l.get('cost_price') or 0.0)
        line_sub = qty * cost
        subtotal += line_sub
        desc = l.get('description') or l.get('product_name') or ''
        po_lines.append({
            'product_id': l['product_id'],
            'description': desc,
            'quantity': qty,
            'unit_cost': cost,
            'subtotal': line_sub
        })

    total_amount = subtotal
    balance_due = total_amount

    cust = query_one("SELECT name FROM customers WHERE id = %s", (order['customer_id'],)) if order.get('customer_id') else None
    cust_name = cust['name'] if cust else 'Customer'
    po_notes = f"[DROPSHIP ORDER]\nDeliver directly to: {cust_name}\nAddress: {order.get('customer_address') or 'N/A'}\nContact: {order.get('customer_contact') or 'N/A'} ({order.get('customer_phone') or 'N/A'})\nReference Sales Order: {order['order_number']}"

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO purchase_orders (
                order_number, vendor_id, location_id, order_date, expected_date,
                status, payment_status, subtotal, shipping_fee, total_amount, paid_amount, balance_due, notes
            ) VALUES (
                %s, %s, %s, CURRENT_DATE, NULL,
                'ISSUED', 'UNPAID', %s, 0, %s, 0, %s, %s
            ) RETURNING id;
        """, (po_number, vendor_id, location_id, subtotal, total_amount, balance_due, po_notes))
        po_id = cur.fetchone()['id']

        for idx, pl in enumerate(po_lines):
            cur.execute("""
                INSERT INTO purchase_order_lines (
                    purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (po_id, idx + 1, pl['product_id'], pl['description'], pl['quantity'], pl['unit_cost'], pl['subtotal']))

        if balance_due > 0:
            cur.execute("""
                UPDATE vendors 
                SET balance = balance + %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (balance_due, vendor_id))

    redirect_url = url_for('purchase_orders.detail_purchase', id=po_id)
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'po_id': po_id,
            'order_number': po_number,
            'redirect_url': redirect_url,
            'message': f"Dropship Purchase Order {po_number} created for {cust_name}."
        })
    flash(f"Dropship Purchase Order {po_number} created successfully for {cust_name}!", "success")
    return redirect(redirect_url)

