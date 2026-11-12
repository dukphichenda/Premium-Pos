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

def _get_history_adjustments(limit=60):
    return query_all("""
        SELECT 
            sa.id,
            sa.adjustment_number,
            sa.adjustment_date,
            sa.reason,
            COALESCE(sa.status, 'COMPLETED') as status,
            l.name as location_name,
            COUNT(sal.id) as item_count,
            COALESCE(SUM(ABS(sal.diff_qty)), 0) as total_diff_units
        FROM stock_adjustments sa
        LEFT JOIN locations l ON sa.location_id = l.id
        LEFT JOIN stock_adjustment_lines sal ON sa.id = sal.adjustment_id
        GROUP BY sa.id, l.name
        ORDER BY sa.adjustment_date DESC, sa.id DESC
        LIMIT %s
    """, (limit,))

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
    """Renders modern inFlow Stock Adjustment editor matching inFlow Cloud UI with Adjustment History sidebar."""
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
    history_adjustments = _get_history_adjustments(60)

    return render_template(
        'inventory/adjustment_form.html',
        is_detail=False,
        is_draft=False,
        draft_id=None,
        draft_lines_json="[]",
        next_adj_num=next_adj_num,
        locations=locations,
        categories=categories,
        total_active_prods=total_active_prods,
        history_adjustments=history_adjustments,
        today_date=datetime.now().strftime('%b %d, %Y')
    )

@inventory_bp.route('/inventory/adjustments/<int:id>')
def detail_adjustment(id):
    """View details of a past stock adjustment or resume a draft in editable mode."""
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
            p.sales_uom,
            p.sales_uom_ratio,
            p.sales_uom_ratio_std,
            p.purchasing_uom,
            p.purchasing_uom_ratio,
            p.purchasing_uom_ratio_std,
            p.image_url as product_image_url,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(inv.quantity, 0) as current_on_hand_qty,
            COALESCE(open_so.reserved_qty, 0) as reserved_qty
        FROM stock_adjustment_lines sal
        JOIN products p ON sal.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory inv ON p.id = inv.product_id AND inv.location_id = %s AND COALESCE(inv.sublocation, '') = COALESCE(sal.sublocation, '')
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
    history_adjustments = _get_history_adjustments(60)

    import json
    custom_fields = {}
    if adj.get('custom_fields_json'):
        try:
            custom_fields = json.loads(adj['custom_fields_json']) if isinstance(adj['custom_fields_json'], str) else adj['custom_fields_json']
        except Exception:
            custom_fields = {}

    is_draft = (adj.get('status') == 'DRAFT')
    draft_lines_json = "[]"
    if is_draft:
        draft_items = []
        for l in lines:
            draft_items.append({
                'product_id': l['product_id'],
                'name': l['product_name'],
                'sku': l['product_sku'],
                'uom': l.get('uom') or l.get('product_uom') or 'Pcs',
                'uom_factor': float(l.get('uom_factor') or 1.0),
                'base_uom': l.get('product_uom') or 'Pcs',
                'sales_uom': l.get('sales_uom') or '',
                'sales_uom_ratio': float(l.get('sales_uom_ratio_std') or l.get('sales_uom_ratio') or 1.0),
                'purchasing_uom': l.get('purchasing_uom') or '',
                'purchasing_uom_ratio': float(l.get('purchasing_uom_ratio_std') or l.get('purchasing_uom_ratio') or 1.0),
                'image_url': l.get('product_image_url') or '',
                'category_name': l.get('category_name') or 'General',
                'sublocation': l.get('sublocation') or '',
                'on_hand_qty': float(l.get('current_on_hand_qty') if l.get('current_on_hand_qty') is not None else (l.get('old_qty') or 0.0)),
                'reserved_qty': float(l.get('reserved_qty') or 0.0),
                'unit_cost': float(l.get('unit_cost') or 0.0),
                'change_qty': float(l.get('diff_qty') or 0.0),
                'final_qty': float(l.get('new_qty') or 0.0)
            })
        draft_lines_json = json.dumps(draft_items)

    formatted_adj_date = adj['adjustment_date'].strftime('%b %d, %Y') if hasattr(adj['adjustment_date'], 'strftime') else str(adj['adjustment_date'])

    return render_template(
        'inventory/adjustment_form.html',
        adjustment=adj,
        lines=lines,
        is_detail=(not is_draft),
        is_draft=is_draft,
        draft_id=id if is_draft else None,
        draft_lines_json=draft_lines_json,
        custom_fields=custom_fields,
        locations=locations,
        categories=categories,
        total_active_prods=total_active_prods,
        history_adjustments=history_adjustments,
        today_date=formatted_adj_date
    )

@inventory_bp.route('/api/inventory/products-for-adjustment')
def api_products_for_adjustment():
    """
    API returning products for stock adjustment selection:
    Supports One-by-One query, Multi-Category batching, or All products.
    Supports ordering/sorting by category, letter/latter, lowest stock, or highest stock.
    Includes on_hand_qty, reserved_qty, available_qty, unit_cost, and UOM ratios.
    """
    location_id = request.args.get('location_id', type=int)
    if not location_id:
        def_loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1") or query_one("SELECT id FROM locations LIMIT 1")
        location_id = def_loc['id'] if def_loc else 100

    # Parse single or multiple category IDs (supports ?category_id=1&category_id=2 or ?category_ids=1,2)
    raw_cat_ids = request.args.getlist('category_id') + request.args.getlist('category_ids') + request.args.getlist('category_ids[]')
    selected_cat_ids = []
    for raw in raw_cat_ids:
        for p in str(raw).split(','):
            p = p.strip()
            if p.isdigit():
                selected_cat_ids.append(int(p))
    selected_cat_ids = list(dict.fromkeys(selected_cat_ids))

    q = (request.args.get('q') or '').strip()
    fetch_all = request.args.get('all', 'false').lower() in ('1', 'true', 'yes')
    sort_by = (request.args.get('sort_by') or '').strip().lower()

    where_clauses = ["p.is_active = TRUE", "p.is_sellable = TRUE"]
    params = [location_id, location_id]

    if selected_cat_ids:
        where_clauses.append("p.category_id = ANY(%s)")
        params.append(selected_cat_ids)

    if q:
        where_clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)")
        term = f"%{q}%"
        params.extend([term, term, term])

    # Dynamic arrangement / sorting requested by user:
    # 1. By category: COALESCE(c.name, 'General') ASC, p.name ASC
    # 2. By letter / latter: p.name ASC
    # 3. By lowest stock: COALESCE(i.quantity, 0) ASC, p.name ASC
    # 4. By highest stock: COALESCE(i.quantity, 0) DESC, p.name ASC
    if sort_by in ('category', 'by_category'):
        order_by_sql = "ORDER BY LOWER(COALESCE(c.name, 'General')) ASC, LOWER(p.name) ASC"
    elif sort_by in ('lowest', 'lowest_stock', 'stock_asc', 'low_stock'):
        order_by_sql = "ORDER BY COALESCE(i.quantity, 0) ASC, LOWER(p.name) ASC"
    elif sort_by in ('highest', 'highest_stock', 'stock_desc', 'high_stock'):
        order_by_sql = "ORDER BY COALESCE(i.quantity, 0) DESC, LOWER(p.name) ASC"
    elif sort_by in ('letter', 'latter', 'name', 'alphabetical', 'name_asc'):
        order_by_sql = "ORDER BY LOWER(p.name) ASC"
    else:
        order_by_sql = "ORDER BY LOWER(p.name) ASC"

    where_sql = " AND ".join(where_clauses)
    limit_sql = "" if (fetch_all or selected_cat_ids) else "LIMIT 60"

    sql = f"""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.image_url, p.category_id,
            p.sales_uom, p.sales_uom_ratio, p.sales_uom_ratio_std,
            p.purchasing_uom, p.purchasing_uom_ratio, p.purchasing_uom_ratio_std,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(i.quantity, 0) as on_hand_qty,
            COALESCE(NULLIF(i.reserved_quantity, 0), open_so.reserved_qty, 0) as reserved_qty,
            COALESCE(i.quantity - COALESCE(NULLIF(i.reserved_quantity, 0), open_so.reserved_qty, 0), 0) as available_qty,
            COALESCE(i.sublocation, '') as sublocation,
            COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) as unit_cost
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i ON p.id = i.product_id AND i.location_id = %s
        LEFT JOIN (
            SELECT sol.product_id, SUM(sol.quantity) as reserved_qty
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            WHERE so.status NOT IN ('PAID', 'SHIPPED', 'CANCELLED', 'INVOICED')
              AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
              AND (
                  COALESCE(
                      CASE WHEN so.location_id IN (SELECT id FROM locations WHERE name LIKE '<%%>') THEN NULL ELSE so.location_id END,
                      (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)
                  ) = %s
              )
            GROUP BY sol.product_id
        ) open_so ON p.id = open_so.product_id
        WHERE {where_sql}
        {order_by_sql}
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
                'base_uom': p.get('uom') or 'Pcs',
                'sales_uom': p.get('sales_uom') or '',
                'sales_uom_ratio': float(p.get('sales_uom_ratio_std') or p.get('sales_uom_ratio') or 1.0),
                'purchasing_uom': p.get('purchasing_uom') or '',
                'purchasing_uom_ratio': float(p.get('purchasing_uom_ratio_std') or p.get('purchasing_uom_ratio') or 1.0),
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
    Creates or updates stock adjustments with draft/complete support, multi-product batching, and UOMs.
    If status == 'DRAFT': saves adjustments & lines without altering inventory quantities or writing inventory logs.
    If status == 'COMPLETED': updates inventory quantities and writes atomic inventory logs.
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
                        'sublocation': request.form.get('sublocation', '').strip(),
                        'uom': request.form.get('uom', '').strip(),
                        'uom_factor': float(request.form.get('uom_factor', 1.0))
                    }]
                else:
                    lines_data = []

            data = {
                'adjustment_id': request.form.get('adjustment_id'),
                'status': request.form.get('status', 'COMPLETED'),
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

        status = (data.get('status') or 'COMPLETED').strip().upper()
        if status not in ('DRAFT', 'COMPLETED'):
            status = 'COMPLETED'

        adjustment_id = data.get('adjustment_id')
        if adjustment_id:
            try:
                adjustment_id = int(adjustment_id)
            except Exception:
                adjustment_id = None

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
            # 1. Insert or Update stock_adjustments header
            if adjustment_id:
                cur.execute("""
                    UPDATE stock_adjustments SET
                        location_id = %s,
                        adjustment_date = %s,
                        reason = %s,
                        status = %s,
                        notes = %s,
                        custom_fields_json = %s,
                        created_by = %s
                    WHERE id = %s
                    RETURNING id, adjustment_number;
                """, (location_id, adj_date, reason, status, notes, custom_fields_json, current_username, adjustment_id))
                updated_row = cur.fetchone()
                if updated_row:
                    adj_id = updated_row['id']
                    adj_number = updated_row['adjustment_number'] or adj_number
                else:
                    cur.execute("""
                        INSERT INTO stock_adjustments (
                            adjustment_number, location_id, adjustment_date, reason, status, notes, custom_fields_json, created_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (adj_number, location_id, adj_date, reason, status, notes, custom_fields_json, current_username))
                    adj_id = cur.fetchone()['id']
                # Clean existing lines for this adjustment
                cur.execute("DELETE FROM stock_adjustment_lines WHERE adjustment_id = %s;", (adj_id,))
            else:
                cur.execute("""
                    INSERT INTO stock_adjustments (
                        adjustment_number, location_id, adjustment_date, reason, status, notes, custom_fields_json, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (adj_number, location_id, adj_date, reason, status, notes, custom_fields_json, current_username))
                adj_id = cur.fetchone()['id']

            total_diff_count = 0
            for item in lines:
                product_id = int(item['product_id'])
                subloc = (item.get('sublocation') or '').strip()
                line_uom = (item.get('uom') or '').strip()
                line_uom_factor = float(item.get('uom_factor') or 1.0)
                if line_uom_factor <= 0:
                    line_uom_factor = 1.0

                # Query current on_hand qty
                if status == 'COMPLETED':
                    cur.execute("""
                        SELECT COALESCE(quantity, 0) as qty 
                        FROM inventory 
                        WHERE product_id = %s AND location_id = %s AND sublocation = %s
                        FOR UPDATE
                    """, (product_id, location_id, subloc))
                else:
                    cur.execute("""
                        SELECT COALESCE(quantity, 0) as qty 
                        FROM inventory 
                        WHERE product_id = %s AND location_id = %s AND sublocation = %s
                    """, (product_id, location_id, subloc))

                cur_inv = cur.fetchone()
                old_qty = float(cur_inv['qty']) if cur_inv else 0.0

                # Determine change / new_qty (in base units)
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

                # Product cost
                cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s", (product_id,))
                prod = cur.fetchone()
                unit_cost = float(prod['average_cost'] or prod['standard_cost'] or 0) if prod else 0.0

                # 2. Insert line with UOM and uom_factor
                cur.execute("""
                    INSERT INTO stock_adjustment_lines (
                        adjustment_id, product_id, old_qty, new_qty, diff_qty, unit_cost, sublocation, uom, uom_factor
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (adj_id, product_id, old_qty, new_qty, diff_qty, unit_cost, subloc, line_uom, line_uom_factor))

                # 3. If COMPLETED, update inventory and inventory_logs
                if status == 'COMPLETED':
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (product_id, location_id, sublocation)
                        DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                    """, (product_id, location_id, subloc, new_qty))

                    cur.execute("""
                        INSERT INTO inventory_logs (
                            product_id, movement_type, reference_type, reference_id,
                            to_location_id, quantity, qty_before, qty_after, unit_cost, reason, notes
                        ) VALUES (%s, 'ADJUSTMENT', 'ADJUST', %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (product_id, adj_number, location_id, diff_qty, old_qty, new_qty, unit_cost, reason, notes))

                total_diff_count += 1

        if status == 'DRAFT':
            msg = f"Draft {adj_number} saved successfully! You can resume and adjust later."
        else:
            msg = f"Stock Adjustment {adj_number} applied successfully! ({total_diff_count} item(s) adjusted)"

        if request.is_json:
            return jsonify({
                'success': True,
                'status': status,
                'is_draft': (status == 'DRAFT'),
                'message': msg,
                'adjustment_id': adj_id,
                'adjustment_number': adj_number,
                'redirect_url': url_for('inventory.detail_adjustment', id=adj_id)
            })

        flash(msg, "success")
        return redirect(url_for('inventory.detail_adjustment', id=adj_id))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error executing stock adjustment: {e}", "error")
        return redirect(url_for('inventory.list_adjustments'))

def _get_next_trf_number():
    try:
        row = query_one("SELECT MAX(CAST(SUBSTRING(transfer_number FROM 'TRF-([0-9]+)') AS INTEGER)) as max_val FROM stock_transfers WHERE transfer_number ~ '^TRF-[0-9]+$'")
        max_val = row['max_val'] if row and row.get('max_val') else 0
        return f"TRF-{max_val + 1:05d}"
    except Exception:
        seq = get_next_sequence_val('trf_number_seq')
        return f"TRF-{seq:05d}"

@inventory_bp.route('/inventory/transfers')
def list_transfers():
    status_filter = (request.args.get('status') or 'all').strip().upper()
    search = (request.args.get('q') or '').strip()
    from_loc = request.args.get('from_location_id', '').strip()
    to_loc = request.args.get('to_location_id', '').strip()

    stats_row = query_one("""
        SELECT 
            COUNT(*) as total_count,
            COUNT(*) FILTER (WHERE UPPER(COALESCE(status, '')) IN ('DRAFT', 'REQUESTED')) as draft_count,
            COUNT(*) FILTER (WHERE UPPER(COALESCE(status, '')) = 'COMPLETED') as completed_count
        FROM stock_transfers
    """) or {}
    total_units_row = query_one("""
        SELECT COALESCE(SUM(stl.quantity), 0) as total_units 
        FROM stock_transfer_lines stl 
        JOIN stock_transfers st ON stl.transfer_id = st.id 
        WHERE UPPER(COALESCE(st.status, '')) = 'COMPLETED'
    """) or {}

    where_clauses = ["1=1"]
    params = []
    if status_filter in ['DRAFT', 'REQUESTED']:
        where_clauses.append("UPPER(COALESCE(st.status, '')) IN ('DRAFT', 'REQUESTED')")
    elif status_filter == 'COMPLETED':
        where_clauses.append("UPPER(COALESCE(st.status, '')) = 'COMPLETED'")

    if search:
        where_clauses.append("(st.transfer_number ILIKE %s OR st.notes ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if from_loc:
        where_clauses.append("st.from_location_id = %s")
        params.append(int(from_loc))
    if to_loc:
        where_clauses.append("st.to_location_id = %s")
        params.append(int(to_loc))

    transfers = query_all(f"""
        SELECT 
            st.*,
            fl.name as from_location_name,
            tl.name as to_location_name,
            COUNT(stl.id) as item_count,
            COALESCE(SUM(stl.quantity), 0) as total_units
        FROM stock_transfers st
        JOIN locations fl ON st.from_location_id = fl.id
        JOIN locations tl ON st.to_location_id = tl.id
        LEFT JOIN stock_transfer_lines stl ON st.id = stl.transfer_id
        WHERE {" AND ".join(where_clauses)}
        GROUP BY st.id, fl.name, tl.name
        ORDER BY st.transfer_date DESC, st.id DESC
        LIMIT 100
    """, params)

    locations = query_all("SELECT id, name, is_default, is_central FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, is_central DESC, name ASC")

    return render_template(
        'inventory/transfers.html',
        transfers=transfers,
        locations=locations,
        status_filter=status_filter,
        search=search,
        from_loc=from_loc,
        to_loc=to_loc,
        stats={
            'total': stats_row.get('total_count', 0),
            'draft': stats_row.get('draft_count', 0),
            'completed': stats_row.get('completed_count', 0),
            'total_units': total_units_row.get('total_units', 0)
        }
    )

@inventory_bp.route('/inventory/transfers/new')
def new_transfer():
    """Create a new multi-product warehouse transfer, starting as Draft request."""
    next_trf_num = _get_next_trf_number()
    locations = query_all("SELECT id, name, is_default, is_central FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, is_central DESC, name ASC")
    from_loc = locations[0]['id'] if locations else None
    to_loc = locations[1]['id'] if len(locations) > 1 else (locations[0]['id'] if locations else None)

    history_transfers = query_all("""
        SELECT 
            st.id, st.transfer_number, st.transfer_date, st.status, st.notes,
            fl.name as from_location_name, tl.name as to_location_name,
            COUNT(stl.id) as item_count,
            COALESCE(SUM(stl.quantity), 0) as total_units
        FROM stock_transfers st
        JOIN locations fl ON st.from_location_id = fl.id
        JOIN locations tl ON st.to_location_id = tl.id
        LEFT JOIN stock_transfer_lines stl ON st.id = stl.transfer_id
        GROUP BY st.id, fl.name, tl.name
        ORDER BY st.transfer_date DESC, st.id DESC
        LIMIT 40
    """)

    return render_template(
        'inventory/transfer_form.html',
        is_detail=False,
        is_edit=False,
        transfer={
            'id': None,
            'transfer_number': next_trf_num,
            'from_location_id': from_loc,
            'to_location_id': to_loc,
            'transfer_date': datetime.now().strftime('%Y-%m-%d'),
            'notes': '',
            'status': 'DRAFT'
        },
        locations=locations,
        lines=[],
        lines_json='[]',
        history_transfers=history_transfers,
        today_date=datetime.now().strftime('%b %d, %Y')
    )

@inventory_bp.route('/inventory/transfers/<int:id>')
def view_transfer(id):
    """View transfer details or continue editing/completing a Draft transfer."""
    trf = query_one("""
        SELECT st.*, fl.name as from_location_name, tl.name as to_location_name
        FROM stock_transfers st
        JOIN locations fl ON st.from_location_id = fl.id
        JOIN locations tl ON st.to_location_id = tl.id
        WHERE st.id = %s
    """, (id,))
    if not trf:
        flash("Stock Transfer not found.", "error")
        return redirect(url_for('inventory.list_transfers'))

    # Fetch lines with live stock in source warehouse
    lines = query_all("""
        SELECT 
            stl.*,
            p.sku as product_sku,
            p.name as product_name,
            p.image_url as product_image_url,
            p.uom as product_uom,
            p.sales_uom,
            p.sales_uom_ratio,
            p.sales_uom_ratio_std,
            p.purchasing_uom,
            p.purchasing_uom_ratio,
            p.purchasing_uom_ratio_std,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(src_inv.quantity, 0) as current_on_hand,
            COALESCE(open_so.reserved_qty, 0) as current_reserved,
            (COALESCE(src_inv.quantity, 0) - COALESCE(open_so.reserved_qty, 0)) as current_available
        FROM stock_transfer_lines stl
        JOIN products p ON stl.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory src_inv ON src_inv.product_id = p.id AND src_inv.location_id = %s
        LEFT JOIN (
            SELECT sol.product_id, SUM(sol.quantity) as reserved_qty
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            WHERE so.status = 'OPEN' 
              AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
              AND (so.location_id = %s OR (so.location_id IS NULL AND %s = (SELECT id FROM locations WHERE is_default = TRUE LIMIT 1)))
            GROUP BY sol.product_id
        ) open_so ON p.id = open_so.product_id
        WHERE stl.transfer_id = %s
        ORDER BY stl.id ASC
    """, (trf['from_location_id'], trf['from_location_id'], trf['from_location_id'], id))

    locations = query_all("SELECT id, name, is_default, is_central FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, is_central DESC, name ASC")
    is_completed = (trf.get('status') or '').upper() == 'COMPLETED'

    lines_data = []
    for l in lines:
        lines_data.append({
            'product_id': l['product_id'],
            'sku': l.get('product_sku') or '',
            'name': l.get('product_name') or '',
            'image_url': l.get('product_image_url') or '',
            'category_name': l.get('category_name') or '',
            'uom': l.get('uom') or l.get('product_uom') or 'pcs.',
            'base_uom': l.get('product_uom') or 'pcs.',
            'uom_factor': float(l.get('uom_factor') or 1.0),
            'sales_uom': l.get('sales_uom') or '',
            'sales_uom_ratio': float(l.get('sales_uom_ratio') or l.get('sales_uom_ratio_std') or 1.0),
            'purchasing_uom': l.get('purchasing_uom') or '',
            'purchasing_uom_ratio': float(l.get('purchasing_uom_ratio') or l.get('purchasing_uom_ratio_std') or 1.0),
            'source_on_hand': float(l.get('current_on_hand') if l.get('current_on_hand') is not None else (l.get('source_on_hand') or 0)),
            'source_reserved': float(l.get('current_reserved') or 0),
            'source_available': float(l.get('current_available') if l.get('current_available') is not None else (l.get('source_available') or 0)),
            'quantity': float(l.get('quantity') or 1)
        })
    lines_json = json.dumps(lines_data)

    history_transfers = query_all("""
        SELECT 
            st.id, st.transfer_number, st.transfer_date, st.status, st.notes,
            fl.name as from_location_name, tl.name as to_location_name,
            COUNT(stl.id) as item_count,
            COALESCE(SUM(stl.quantity), 0) as total_units
        FROM stock_transfers st
        JOIN locations fl ON st.from_location_id = fl.id
        JOIN locations tl ON st.to_location_id = tl.id
        LEFT JOIN stock_transfer_lines stl ON st.id = stl.transfer_id
        GROUP BY st.id, fl.name, tl.name
        ORDER BY st.transfer_date DESC, st.id DESC
        LIMIT 40
    """)

    return render_template(
        'inventory/transfer_form.html',
        is_detail=is_completed,
        is_edit=(not is_completed),
        transfer=trf,
        locations=locations,
        lines=lines,
        lines_json=lines_json,
        history_transfers=history_transfers,
        today_date=datetime.now().strftime('%b %d, %Y')
    )

@inventory_bp.route('/inventory/transfers/save', methods=['POST'])
def save_transfer():
    """Save transfer request as DRAFT or execute COMPLETED stock movement."""
    try:
        data = request.get_json(force=True) or {}
        transfer_id = data.get('transfer_id')
        transfer_number = (data.get('transfer_number') or '').strip()
        from_location_id = int(data.get('from_location_id') or 0)
        to_location_id = int(data.get('to_location_id') or 0)
        transfer_date = data.get('transfer_date') or datetime.now().strftime('%Y-%m-%d')
        notes = (data.get('notes') or '').strip()
        status = (data.get('status') or 'DRAFT').upper()
        lines = data.get('lines', [])

        if not from_location_id or not to_location_id:
            return jsonify({'success': False, 'message': 'Please select both source and destination warehouses.'}), 400

        if from_location_id == to_location_id:
            return jsonify({'success': False, 'message': 'Source and destination warehouse cannot be the same.'}), 400

        if not lines or len(lines) == 0:
            return jsonify({'success': False, 'message': 'Please add at least one product to transfer.'}), 400

        if not transfer_number:
            transfer_number = _get_next_trf_number()

        with get_db_cursor(commit=True) as cur:
            # 1. If completing, validate stock availability in source location
            if status == 'COMPLETED':
                if transfer_id:
                    cur.execute("SELECT status FROM stock_transfers WHERE id = %s", (transfer_id,))
                    existing = cur.fetchone()
                    if existing and existing['status'] == 'COMPLETED':
                        return jsonify({'success': False, 'message': 'This transfer has already been completed.'}), 400

                insufficient_items = []
                for l in lines:
                    pid = int(l['product_id'])
                    qty = float(l.get('quantity') or 0)
                    factor = float(l.get('uom_factor') or 1.0)
                    base_qty = qty * factor

                    if qty <= 0:
                        return jsonify({'success': False, 'message': f"Invalid transfer quantity ({qty}) on line item."}), 400

                    # Lock source warehouse inventory
                    cur.execute("""
                        SELECT COALESCE(quantity, 0) as qty, COALESCE(reserved_quantity, 0) as reserved
                        FROM inventory
                        WHERE product_id = %s AND location_id = %s
                        FOR UPDATE
                    """, (pid, from_location_id))
                    inv_row = cur.fetchone()
                    src_on_hand = float(inv_row['qty']) if inv_row else 0.0

                    if src_on_hand < base_qty:
                        cur.execute("SELECT sku, name FROM products WHERE id = %s", (pid,))
                        p_info = cur.fetchone() or {'sku': '', 'name': f'Product #{pid}'}
                        insufficient_items.append(f"{p_info['sku']} {p_info['name']} (Available: {src_on_hand:g}, Required: {base_qty:g})")

                if insufficient_items:
                    return jsonify({
                        'success': False,
                        'message': "Cannot complete transfer due to insufficient stock in source warehouse:<br>• " + "<br>• ".join(insufficient_items)
                    }), 400

            # 2. Insert or update header in stock_transfers
            if transfer_id:
                cur.execute("""
                    UPDATE stock_transfers
                    SET transfer_number = %s, from_location_id = %s, to_location_id = %s,
                        status = %s, transfer_date = %s, notes = %s
                    WHERE id = %s
                    RETURNING id;
                """, (transfer_number, from_location_id, to_location_id, status, transfer_date, notes, transfer_id))
                trf_id = transfer_id
            else:
                cur.execute("""
                    INSERT INTO stock_transfers (transfer_number, from_location_id, to_location_id, status, transfer_date, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (transfer_number, from_location_id, to_location_id, status, transfer_date, notes))
                trf_id = cur.fetchone()['id']

            # 3. Replace lines
            cur.execute("DELETE FROM stock_transfer_lines WHERE transfer_id = %s", (trf_id,))
            for l in lines:
                pid = int(l['product_id'])
                qty = float(l.get('quantity') or 0)
                uom = l.get('uom') or 'pcs.'
                factor = float(l.get('uom_factor') or 1.0)
                src_on_hand = float(l.get('source_on_hand') or 0)
                src_avail = float(l.get('source_available') or 0)

                cur.execute("""
                    INSERT INTO stock_transfer_lines (transfer_id, product_id, quantity, uom, uom_factor, source_on_hand, source_available)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (trf_id, pid, qty, uom, factor, src_on_hand, src_avail))

            # 4. If COMPLETED, execute atomic inventory deduction & addition
            if status == 'COMPLETED':
                for l in lines:
                    pid = int(l['product_id'])
                    qty = float(l.get('quantity') or 0)
                    factor = float(l.get('uom_factor') or 1.0)
                    base_qty = qty * factor

                    cur.execute("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s", (pid, from_location_id))
                    src_row = cur.fetchone()
                    qty_before_src = float(src_row['qty']) if src_row else 0.0

                    # Deduct from source warehouse
                    cur.execute("""
                        UPDATE inventory 
                        SET quantity = quantity - %s, updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s AND location_id = %s;
                    """, (base_qty, pid, from_location_id))

                    # Add to destination warehouse (upsert)
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                        VALUES (%s, %s, '', %s)
                        ON CONFLICT (product_id, location_id, sublocation)
                        DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                    """, (pid, to_location_id, base_qty))

                    # Audit log in inventory_logs
                    cur.execute("""
                        INSERT INTO inventory_logs (
                            product_id, movement_type, reference_type, reference_id,
                            from_location_id, to_location_id, quantity, qty_before, qty_after, reason, notes
                        ) VALUES (%s, 'TRANSFER', 'TRANSFER', %s, %s, %s, %s, %s, %s, 'Warehouse Transfer Out', %s);
                    """, (pid, transfer_number, from_location_id, to_location_id, -base_qty, qty_before_src, qty_before_src - base_qty, notes))

        msg = f"Stock Transfer {transfer_number} completed successfully!" if status == 'COMPLETED' else f"Transfer request {transfer_number} saved as Draft."
        return jsonify({
            'success': True,
            'transfer_id': trf_id,
            'transfer_number': transfer_number,
            'status': status,
            'message': msg
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@inventory_bp.route('/inventory/transfers/<int:id>/delete', methods=['POST'])
def delete_transfer(id):
    """Delete a transfer request draft."""
    try:
        trf = query_one("SELECT id, status, transfer_number FROM stock_transfers WHERE id = %s", (id,))
        if not trf:
            return jsonify({'success': False, 'message': 'Transfer not found.'}), 404
        if (trf.get('status') or '').upper() == 'COMPLETED':
            return jsonify({'success': False, 'message': 'Cannot delete an already completed transfer.'}), 400

        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM stock_transfer_lines WHERE transfer_id = %s", (id,))
            cur.execute("DELETE FROM stock_transfers WHERE id = %s", (id,))

        return jsonify({'success': True, 'message': f"Transfer draft {trf['transfer_number']} deleted."})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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
