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
            SUM(ABS(sal.diff_qty)) as total_diff_units
        FROM stock_adjustments sa
        JOIN locations l ON sa.location_id = l.id
        LEFT JOIN stock_adjustment_lines sal ON sa.id = sal.adjustment_id
        GROUP BY sa.id, l.name
        ORDER BY sa.adjustment_date DESC, sa.id DESC
        LIMIT 50
    """)
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    return render_template('inventory/adjustments.html', adjustments=adjustments, locations=locations)

@inventory_bp.route('/inventory/adjustments/create', methods=['POST'])
def create_adjustment():
    try:
        location_id = int(request.form.get('location_id'))
        reason = request.form.get('reason', 'Recount').strip()
        notes = request.form.get('notes', '').strip()
        product_id = int(request.form.get('product_id'))
        new_qty = float(request.form.get('new_qty', 0))

        if new_qty < 0:
            flash("Physical counted stock quantity cannot be negative.", "error")
            return redirect(url_for('inventory.list_adjustments'))

        seq_val = get_next_sequence_val('adj_number_seq')
        adj_number = f"ADJ-{seq_val:05d}"

        with get_db_cursor(commit=True) as cur:
            # Lock existing inventory row
            cur.execute("""
                SELECT COALESCE(quantity, 0) as qty 
                FROM inventory 
                WHERE product_id = %s AND location_id = %s 
                FOR UPDATE
            """, (product_id, location_id))
            cur_inv = cur.fetchone()
            old_qty = float(cur_inv['qty']) if cur_inv else 0.0
            diff_qty = new_qty - old_qty

            # Product Cost
            cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            unit_cost = float(prod['average_cost'] or prod['standard_cost'] or 0) if prod else 0.0

            cur.execute("""
                INSERT INTO stock_adjustments (adjustment_number, location_id, reason, status, notes)
                VALUES (%s, %s, %s, 'COMPLETED', %s)
                RETURNING id;
            """, (adj_number, location_id, reason, notes))
            adj_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO stock_adjustment_lines (adjustment_id, product_id, old_qty, new_qty, diff_qty, unit_cost)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (adj_id, product_id, old_qty, new_qty, diff_qty, unit_cost))

            # Update inventory via upsert
            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES (%s, %s, '', %s)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
            """, (product_id, location_id, new_qty))

            # Ledger entry
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    to_location_id, quantity, qty_before, qty_after, unit_cost, reason, notes
                ) VALUES (%s, 'ADJUSTMENT', 'ADJUST', %s, %s, %s, %s, %s, %s, %s, %s);
            """, (product_id, adj_number, location_id, diff_qty, old_qty, new_qty, unit_cost, reason, notes))

        flash(f"Stock Adjustment {adj_number} applied successfully! (Diff: {diff_qty:+g} units)", "success")
        return redirect(url_for('inventory.list_adjustments'))

    except Exception as e:
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
