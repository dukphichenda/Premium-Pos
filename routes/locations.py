from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import query_one, query_all, execute

locations_bp = Blueprint('locations', __name__)

@locations_bp.route('/locations')
def list_locations():
    status_filter = request.args.get('status', 'all').strip().lower()

    where_clause = "WHERE l.name NOT LIKE '<%%>'"
    if status_filter == 'active':
        where_clause += " AND l.is_active = TRUE"
    elif status_filter == 'inactive':
        where_clause += " AND l.is_active = FALSE"

    locations = query_all(f"""
        SELECT 
            l.*,
            COUNT(DISTINCT CASE WHEN i.quantity > 0 THEN i.product_id END) as stocked_products,
            COALESCE(SUM(i.quantity), 0) as total_units,
            COALESCE(SUM(i.quantity * (CASE WHEN p.costing_method = 'Average' THEN COALESCE(NULLIF(p.average_cost, 0), p.standard_cost, 0) ELSE COALESCE(NULLIF(p.standard_cost, 0), p.average_cost, 0) END)), 0) as total_valuation
        FROM locations l
        LEFT JOIN inventory i ON l.id = i.location_id
        LEFT JOIN products p ON i.product_id = p.id
        {where_clause}
        GROUP BY l.id
        ORDER BY l.is_default DESC, l.is_active DESC, l.name ASC
    """)
    return render_template('locations/list.html', locations=locations, status_filter=status_filter)

@locations_bp.route('/locations/create', methods=['POST'])
def create_location():
    try:
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip() or None
        address = request.form.get('address', '').strip() or None

        if not name:
            flash("Warehouse name is required.", "error")
            return redirect(url_for('locations.list_locations'))

        # Check duplicate name
        existing = query_one("SELECT id FROM locations WHERE LOWER(name) = LOWER(%s) AND name NOT LIKE '<%%>'", (name,))
        if existing:
            flash(f"Warehouse with name '{name}' already exists.", "error")
            return redirect(url_for('locations.list_locations'))

        execute("""
            INSERT INTO locations (name, code, address, is_active, is_default)
            VALUES (%s, %s, %s, TRUE, FALSE);
        """, (name, code, address))

        flash(f"Warehouse '{name}' created successfully!", "success")
        return redirect(url_for('locations.list_locations'))

    except Exception as e:
        flash(f"Error adding warehouse: {e}", "error")
        return redirect(url_for('locations.list_locations'))

@locations_bp.route('/locations/<int:id>/edit', methods=['POST'])
def edit_location(id):
    try:
        loc = query_one("SELECT * FROM locations WHERE id = %s", (id,))
        if not loc:
            flash("Warehouse not found.", "error")
            return redirect(url_for('locations.list_locations'))

        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip() or None
        address = request.form.get('address', '').strip() or None

        if not name:
            flash("Warehouse name is required.", "error")
            return redirect(url_for('locations.list_locations'))

        # Check duplicate name with other location
        dup = query_one("SELECT id FROM locations WHERE LOWER(name) = LOWER(%s) AND id != %s", (name, id))
        if dup:
            flash(f"Another warehouse named '{name}' already exists.", "error")
            return redirect(url_for('locations.list_locations'))

        execute("""
            UPDATE locations
            SET name = %s, code = %s, address = %s
            WHERE id = %s
        """, (name, code, address, id))

        flash(f"Warehouse '{name}' updated successfully!", "success")
        return redirect(url_for('locations.list_locations'))

    except Exception as e:
        flash(f"Error updating warehouse: {e}", "error")
        return redirect(url_for('locations.list_locations'))

@locations_bp.route('/locations/<int:id>/toggle_active', methods=['POST'])
def toggle_active_location(id):
    try:
        loc = query_one("SELECT * FROM locations WHERE id = %s", (id,))
        if not loc:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Warehouse not found'}), 404
            flash("Warehouse not found.", "error")
            return redirect(url_for('locations.list_locations'))

        if loc['is_default'] and loc['is_active']:
            msg = "The default warehouse cannot be deactivated. Please set another warehouse as default first."
            if request.is_json:
                return jsonify({'success': False, 'message': msg}), 400
            flash(msg, "warning")
            return redirect(url_for('locations.list_locations'))

        new_status = not loc['is_active']
        execute("UPDATE locations SET is_active = %s WHERE id = %s", (new_status, id))

        status_str = "activated" if new_status else "deactivated"
        msg = f"Warehouse '{loc['name']}' has been {status_str}."

        if request.is_json:
            return jsonify({'success': True, 'is_active': new_status, 'message': msg})

        flash(msg, "success")
        return redirect(url_for('locations.list_locations'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error toggling warehouse status: {e}", "error")
        return redirect(url_for('locations.list_locations'))

@locations_bp.route('/locations/<int:id>/delete', methods=['POST'])
def delete_location(id):
    try:
        loc = query_one("SELECT * FROM locations WHERE id = %s", (id,))
        if not loc:
            flash("Warehouse not found.", "error")
            return redirect(url_for('locations.list_locations'))

        if loc['is_default']:
            flash("Cannot delete the default warehouse. Please designate another warehouse as default first.", "error")
            return redirect(url_for('locations.list_locations'))

        # Check total inventory quantity on hand
        inv_check = query_one("""
            SELECT COALESCE(SUM(quantity), 0) as total_qty 
            FROM inventory 
            WHERE location_id = %s
        """, (id,))
        total_qty = float(inv_check['total_qty']) if inv_check else 0.0

        if total_qty > 0:
            flash(f"Cannot delete warehouse '{loc['name']}' because it currently contains {total_qty:,.0f} units of stock on hand. Please transfer or adjust the inventory first, or mark the warehouse as Inactive.", "error")
            return redirect(url_for('locations.list_locations'))

        # Check if historical inventory logs, orders, or transactions exist
        try:
            # Delete 0-quantity inventory rows
            execute("DELETE FROM inventory WHERE location_id = %s AND quantity = 0", (id,))
            # Attempt physical delete
            execute("DELETE FROM locations WHERE id = %s", (id,))
            flash(f"Warehouse '{loc['name']}' has been permanently deleted.", "success")
        except Exception as db_err:
            # Foreign key reference exists, so soft-delete / deactivate instead
            execute("UPDATE locations SET is_active = FALSE WHERE id = %s", (id,))
            flash(f"Warehouse '{loc['name']}' contains historical transaction history and has been safely marked as Inactive instead of permanently deleted.", "info")

        return redirect(url_for('locations.list_locations'))

    except Exception as e:
        flash(f"Error deleting warehouse: {e}", "error")
        return redirect(url_for('locations.list_locations'))
