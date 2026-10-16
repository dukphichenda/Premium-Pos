from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/inventory')
def overview():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category_id', '').strip()
    location_id = request.args.get('location_id', '').strip()

    where_clauses = ["p.is_active = TRUE"]
    params = []

    if search:
        where_clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])

    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(int(category_id))

    where_sql = " AND ".join(where_clauses)

    # Fetch active warehouses (exclude system staging pseudo-locations)
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, id ASC")
    categories = query_all("SELECT id, name FROM categories WHERE is_active = TRUE ORDER BY name")

    # Inventory grid items
    items_query = f"""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.reorder_point, p.reorder_quantity,
            c.name as category_name,
            (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END) as unit_cost,
            COALESCE(tot.total_qty, 0) as total_qty,
            COALESCE(tot.reserved_qty, 0) as reserved_qty,
            (COALESCE(tot.total_qty, 0) * (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END)) as total_value
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty, SUM(reserved_quantity) as reserved_qty
            FROM inventory
            GROUP BY product_id
        ) tot ON p.id = tot.product_id
        WHERE {where_sql}
        ORDER BY p.id ASC
        LIMIT 100
    """
    items = query_all(items_query, tuple(params))

    # Fetch inventory breakdown per location for these items
    location_matrix = {}
    if items:
        prod_ids = [it['id'] for it in items]
        stock_rows = query_all("""
            SELECT product_id, location_id, quantity
            FROM inventory
            WHERE product_id = ANY(%s)
        """, (prod_ids,))
        for sr in stock_rows:
            key = (sr['product_id'], sr['location_id'])
            location_matrix[key] = float(sr['quantity'])

    return render_template('inventory/overview.html',
                           items=items,
                           locations=locations,
                           categories=categories,
                           location_matrix=location_matrix,
                           search=search,
                           category_id=category_id,
                           location_id=location_id)

@inventory_bp.route('/inventory/adjustments')
def list_adjustments():
    adjustments = query_all("""
        SELECT 
            sa.*,
            l.name as location_name,
            COUNT(sal.id) as item_count,
            COALESCE(SUM(ABS(sal.diff_qty)), 0) as total_diff_units
        FROM stock_adjustments sa
        LEFT JOIN locations l ON sa.location_id = l.id
        LEFT JOIN stock_adjustment_lines sal ON sa.id = sal.adjustment_id
        GROUP BY sa.id, l.name
        ORDER BY sa.adjustment_date DESC, sa.id DESC
        LIMIT 100
    """)
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    return render_template('inventory/adjustments.html', adjustments=adjustments, locations=locations)

def _get_next_adj_number():
    try:
        row = query_one("SELECT MAX(SUBSTRING(adjustment_number FROM '[0-9]+')::bigint) as max_val FROM stock_adjustments WHERE adjustment_number ~ 'ADJ-[0-9]+'")
        max_val = row['max_val'] if row and row.get('max_val') else 0
        return f"ADJ-{max_val + 1:05d}"
    except Exception:
        seq = get_next_sequence_val('adj_number_seq')
        return f"ADJ-{seq:05d}"

@inventory_bp.route('/inventory/adjustments/new')
def new_adjustment():
    """Renders modern inFlow Stock Adjustment editor matching inFlow Cloud UI."""
    next_adj_num = _get_next_adj_number()
    locations = query_all("SELECT id, name, is_default, is_central FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, is_central DESC, name ASC")
    categories = query_all("""
        SELECT c.id, c.name, COUNT(p.id) as product_count 
        FROM categories c 
        LEFT JOIN products p ON c.id = p.category_id AND p.is_active = TRUE AND p.is_sellable = TRUE
        GROUP BY c.id, c.name 
        ORDER BY c.name ASC
    """)
    total_active_row = query_one("SELECT COUNT(*) as count FROM products WHERE is_active = TRUE AND is_sellable = TRUE")
    total_active_prods = total_active_row['count'] if total_active_row else 0

    return render_template(
        'inventory/adjustment_form.html',
        is_detail=False,
        next_adj_num=next_adj_num,
        locations=locations,
        categories=categories,
        total_active_prods=total_active_prods,
        today_date=datetime.now().strftime('%b %d, %Y')
    )

@inventory_bp.route('/inventory/adjustments/<int:id>')
def detail_adjustment(id):
    """View details of a past stock adjustment in the inFlow Cloud design layout with Print support."""
    adj = query_one("""
        SELECT sa.*, l.name as location_name
        FROM stock_adjustments sa
        LEFT JOIN locations l ON sa.location_id = l.id
        WHERE sa.id = %s
    """, (id,))
    if not adj:
        flash("Stock Adjustment not found.", "error")
        return redirect(url_for('inventory.list_adjustments'))

    lines = query_all("""
        SELECT 
            sal.*,
            p.name as product_name,
            p.sku as product_sku,
            p.uom as product_uom,
            p.image_url as product_image_url,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(open_so.reserved_qty, 0) as reserved_qty
        FROM stock_adjustment_lines sal
        JOIN products p ON sal.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory inv ON p.id = inv.product_id AND inv.location_id = %s AND inv.sublocation = sal.sublocation
        LEFT JOIN (
            SELECT sol.product_id, SUM(sol.quantity) as reserved_qty
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            WHERE so.status = 'OPEN' 
              AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
              AND (so.location_id = %s OR (so.location_id IS NULL AND %s = (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)))
            GROUP BY sol.product_id
        ) open_so ON p.id = open_so.product_id
        WHERE sal.adjustment_id = %s
        ORDER BY sal.id ASC
    """, (adj['location_id'], adj['location_id'], adj['location_id'], id))

    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE ORDER BY is_default DESC, name ASC")
    categories = query_all("SELECT c.id, c.name, COUNT(p.id) as product_count FROM categories c LEFT JOIN products p ON c.id = p.category_id AND p.is_active = TRUE GROUP BY c.id, c.name ORDER BY c.name ASC")

    import json
    custom_fields = {}
    if adj.get('custom_fields_json'):
        try:
            custom_fields = json.loads(adj['custom_fields_json']) if isinstance(adj['custom_fields_json'], str) else adj['custom_fields_json']
        except Exception:
            custom_fields = {}

    return render_template(
        'inventory/adjustment_form.html',
        adjustment=adj,
        lines=lines,
        is_detail=True,
        custom_fields=custom_fields,
        locations=locations,
        categories=categories
    )

@inventory_bp.route('/api/inventory/products-for-adjustment')
def api_products_for_adjustment():
    """
    API returning products for stock adjustment selection:
    Supports One-by-One query, Category batching, or All products.
    Includes on_hand_qty, reserved_qty (accurately accounting only open unpaid SOs), available_qty, and cost.
    """
    location_id = request.args.get('location_id', type=int)
    if not location_id:
        def_loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1") or query_one("SELECT id FROM locations LIMIT 1")
        location_id = def_loc['id'] if def_loc else 100

    category_id = request.args.get('category_id', type=int)
    q = (request.args.get('q') or '').strip()
    fetch_all = request.args.get('all', 'false').lower() in ('1', 'true', 'yes')

    where_clauses = ["p.is_active = TRUE", "p.is_sellable = TRUE"]
    params = [location_id, location_id, location_id]

    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(category_id)

    if q:
        where_clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)")
        term = f"%{q}%"
        params.extend([term, term, term])

    where_sql = " AND ".join(where_clauses)
    limit_sql = "" if (fetch_all or category_id) else "LIMIT 60"

    sql = f"""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.image_url, p.category_id,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(i.quantity, 0) as on_hand_qty,
            COALESCE(open_so.reserved_qty, 0) as reserved_qty,
            COALESCE(i.quantity - COALESCE(open_so.reserved_qty, 0), 0) as available_qty,
            COALESCE(i.sublocation, '') as sublocation,
            COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i ON p.id = i.product_id AND i.location_id = %s
        LEFT JOIN (
            SELECT sol.product_id, SUM(sol.quantity) as reserved_qty
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            WHERE so.status = 'OPEN' 
              AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
              AND (so.location_id = %s OR (so.location_id IS NULL AND %s = (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)))
            GROUP BY sol.product_id
        ) open_so ON p.id = open_so.product_id
        WHERE {where_sql}
        ORDER BY p.name ASC
        {limit_sql}
    """
    products = query_all(sql, tuple(params))
    return jsonify({
        'success': True,
        'count': len(products),
        'location_id': location_id,
        'products': [
            {
                'id': p['id'],
                'sku': p['sku'],
                'name': p['name'],
                'uom': p.get('uom') or 'Pcs',
                'image_url': p.get('image_url') or '',
                'category_id': p.get('category_id'),
                'category_name': p.get('category_name') or 'General',
                'on_hand_qty': float(p.get('on_hand_qty') or 0.0),
                'reserved_qty': float(p.get('reserved_qty') or 0.0),
                'available_qty': float(p.get('available_qty') or 0.0),
                'sublocation': p.get('sublocation') or '',
                'unit_cost': float(p.get('unit_cost') or 0.0)
            } for p in products
        ]
    })

@inventory_bp.route('/inventory/adjustments/create', methods=['POST'])
def create_adjustment():
    """
    Creates stock adjustments with multi-product batching support.
    Maintains full backward compatibility with single-product legacy calls.
    Updates inventory and writes atomic entries to stock_adjustments, lines, and inventory_logs.
    """
    try:
        import json
        from flask import session

        data = request.get_json(silent=True) if request.is_json else None
        if not data and request.form:
            raw_lines = request.form.get('lines_json')
            if raw_lines:
                try:
                    lines_data = json.loads(raw_lines)
                except Exception:
                    lines_data = []
            else:
                pid = request.form.get('product_id')
                if pid:
                    lines_data = [{
                        'product_id': int(pid),
                        'new_qty': float(request.form.get('new_qty', 0)),
                        'sublocation': request.form.get('sublocation', '').strip()
                    }]
                else:
                    lines_data = []

            data = {
                'location_id': request.form.get('location_id'),
                'adjustment_number': request.form.get('adjustment_number'),
                'adjustment_date': request.form.get('adjustment_date'),
                'reason': request.form.get('reason'),
                'notes': request.form.get('notes'),
                'custom_fields_json': request.form.get('custom_fields_json'),
                'lines': lines_data
            }

        if not data:
            if request.is_json:
                return jsonify({'success': False, 'error': 'No adjustment data provided'}), 400
            flash("No adjustment data provided.", "error")
            return redirect(url_for('inventory.list_adjustments'))

        location_id = int(data.get('location_id') or 100)
        reason = (data.get('reason') or 'Correction').strip()
        notes = (data.get('notes') or '').strip()
        adj_number = (data.get('adjustment_number') or '').strip()
        if not adj_number:
            adj_number = _get_next_adj_number()

        custom_fields_json = data.get('custom_fields_json')
        if isinstance(custom_fields_json, dict):
            custom_fields_json = json.dumps(custom_fields_json)

        lines = data.get('lines') or []
        if not lines:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Please add at least one product to adjust.'}), 400
            flash("Please add at least one product to adjust.", "error")
            return redirect(url_for('inventory.new_adjustment'))

        current_username = session.get('username') or session.get('display_name') or 'admin'
        adj_date = data.get('adjustment_date') or datetime.now().strftime('%Y-%m-%d')

        with get_db_cursor(commit=True) as cur:
            # 1. Insert stock_adjustments header
            cur.execute("""
                INSERT INTO stock_adjustments (
                    adjustment_number, location_id, adjustment_date, reason, status, notes, custom_fields_json, created_by
                )
                VALUES (%s, %s, %s, %s, 'COMPLETED', %s, %s, %s)
                RETURNING id;
            """, (adj_number, location_id, adj_date, reason, notes, custom_fields_json, current_username))
            adj_id = cur.fetchone()['id']

            total_diff_count = 0
            for item in lines:
                product_id = int(item['product_id'])
                subloc = (item.get('sublocation') or '').strip()

                # Lock existing inventory row
                cur.execute("""
                    SELECT COALESCE(quantity, 0) as qty 
                    FROM inventory 
                    WHERE product_id = %s AND location_id = %s AND sublocation = %s
                    FOR UPDATE
                """, (product_id, location_id, subloc))
                cur_inv = cur.fetchone()
                old_qty = float(cur_inv['qty']) if cur_inv else 0.0

                # Determine change / new_qty
                if 'change_qty' in item and item['change_qty'] is not None and str(item['change_qty']).strip() != '':
                    change = float(item['change_qty'])
                    new_qty = old_qty + change
                    diff_qty = change
                elif 'new_qty' in item and item['new_qty'] is not None:
                    new_qty = float(item['new_qty'])
                    diff_qty = new_qty - old_qty
                elif 'final_qty' in item and item['final_qty'] is not None:
                    new_qty = float(item['final_qty'])
                    diff_qty = new_qty - old_qty
                else:
                    continue

                if new_qty < 0 and abs(diff_qty) < 0.0001:
                    continue

                # Product cost
                cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s", (product_id,))
                prod = cur.fetchone()
                unit_cost = float(prod['average_cost'] or prod['standard_cost'] or 0) if prod else 0.0

                # 2. Insert line
                cur.execute("""
                    INSERT INTO stock_adjustment_lines (
                        adjustment_id, product_id, old_qty, new_qty, diff_qty, unit_cost, sublocation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (adj_id, product_id, old_qty, new_qty, diff_qty, unit_cost, subloc))

                # 3. Update inventory
                cur.execute("""
                    INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_id, location_id, sublocation)
                    DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                """, (product_id, location_id, subloc, new_qty))

                # 4. Inventory log ledger
                cur.execute("""
                    INSERT INTO inventory_logs (
                        product_id, movement_type, reference_type, reference_id,
                        to_location_id, quantity, qty_before, qty_after, unit_cost, reason, notes
                    ) VALUES (%s, 'ADJUSTMENT', 'ADJUST', %s, %s, %s, %s, %s, %s, %s, %s);
                """, (product_id, adj_number, location_id, diff_qty, old_qty, new_qty, unit_cost, reason, notes))

                total_diff_count += 1

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f"Stock Adjustment {adj_number} applied successfully! ({total_diff_count} item(s) adjusted)",
                'adjustment_id': adj_id,
                'adjustment_number': adj_number,
                'redirect_url': url_for('inventory.detail_adjustment', id=adj_id)
            })

        flash(f"Stock Adjustment {adj_number} applied successfully! ({total_diff_count} item(s) adjusted)", "success")
        return redirect(url_for('inventory.detail_adjustment', id=adj_id))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error executing stock adjustment: {e}", "error")
        return redirect(url_for('inventory.list_adjustments'))

@inventory_bp.route('/inventory/transfers')
def list_transfers():
    transfers = query_all("""
        SELECT 
            st.*,
            fl.name as from_location_name,
            tl.name as to_location_name,
            COUNT(stl.id) as item_count,
            SUM(stl.quantity) as total_units
        FROM stock_transfers st
        JOIN locations fl ON st.from_location_id = fl.id
        JOIN locations tl ON st.to_location_id = tl.id
        LEFT JOIN stock_transfer_lines stl ON st.id = stl.transfer_id
        GROUP BY st.id, fl.name, tl.name
        ORDER BY st.transfer_date DESC, st.id DESC
        LIMIT 50
    """)
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    return render_template('inventory/transfers.html', transfers=transfers, locations=locations)

@inventory_bp.route('/inventory/transfers/create', methods=['POST'])
def create_transfer():
    try:
        from_loc = int(request.form.get('from_location_id'))
        to_loc = int(request.form.get('to_location_id'))
        product_id = int(request.form.get('product_id'))
        transfer_qty = float(request.form.get('quantity', 0) or 0)
        notes = request.form.get('notes', '').strip()

        if transfer_qty <= 0:
            flash("Transfer quantity must be greater than zero.", "error")
            return redirect(url_for('inventory.list_transfers'))

        if from_loc == to_loc:
            flash("Source and destination warehouse cannot be the same.", "error")
            return redirect(url_for('inventory.list_transfers'))

        seq_val = get_next_sequence_val('trf_number_seq')
        transfer_num = f"TRF-{seq_val:05d}"

        with get_db_cursor(commit=True) as cur:
            # Row lock source warehouse inventory to eliminate race conditions
            cur.execute("""
                SELECT COALESCE(quantity, 0) as qty 
                FROM inventory 
                WHERE product_id = %s AND location_id = %s 
                FOR UPDATE
            """, (product_id, from_loc))
            src_inv = cur.fetchone()
            src_qty = float(src_inv['qty']) if src_inv else 0.0

            if src_qty < transfer_qty:
                flash(f"Insufficient stock in source warehouse (Available: {src_qty}, Requested: {transfer_qty})", "error")
                return redirect(url_for('inventory.list_transfers'))

            cur.execute("""
                INSERT INTO stock_transfers (transfer_number, from_location_id, to_location_id, status, notes)
                VALUES (%s, %s, %s, 'COMPLETED', %s)
                RETURNING id;
            """, (transfer_num, from_loc, to_loc, notes))
            trf_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO stock_transfer_lines (transfer_id, product_id, quantity)
                VALUES (%s, %s, %s);
            """, (trf_id, product_id, transfer_qty))

            # Deduct from source
            cur.execute("""
                UPDATE inventory 
                SET quantity = quantity - %s, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s AND location_id = %s;
            """, (transfer_qty, product_id, from_loc))

            # Add to destination via upsert
            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES (%s, %s, '', %s)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
            """, (product_id, to_loc, transfer_qty))

            # Audit ledger
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    from_location_id, to_location_id, quantity, qty_before, qty_after, reason, notes
                ) VALUES (%s, 'TRANSFER', 'TRANSFER', %s, %s, %s, %s, %s, %s, 'Warehouse Transfer', %s);
            """, (product_id, transfer_num, from_loc, to_loc, transfer_qty, src_qty, src_qty - transfer_qty, notes))

        flash(f"Stock Transfer {transfer_num} ({transfer_qty} units) executed successfully!", "success")
        return redirect(url_for('inventory.list_transfers'))

    except Exception as e:
        flash(f"Error executing transfer: {e}", "error")
        return redirect(url_for('inventory.list_transfers'))

@inventory_bp.route('/inventory/reorder')
def reorder_assistant():
    low_stock = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.reorder_point, p.reorder_quantity,
            p.standard_cost, p.average_cost,
            c.name as category_name,
            COALESCE(inv.total_qty, 0) as current_qty,
            GREATEST(p.reorder_quantity, p.reorder_point - COALESCE(inv.total_qty, 0)) as suggested_reorder_qty
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE p.is_active = TRUE 
          AND p.reorder_point > 0 
          AND COALESCE(inv.total_qty, 0) <= p.reorder_point
        ORDER BY (COALESCE(inv.total_qty, 0) - p.reorder_point) ASC
    """)
    vendors = query_all("SELECT id, name FROM vendors WHERE is_active = TRUE ORDER BY name")
    return render_template('inventory/reorder.html', low_stock=low_stock, vendors=vendors)
