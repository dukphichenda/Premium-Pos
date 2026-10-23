import os
import re
import io
import csv
import time
import uuid
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, send_file, current_app
from database import query_one, query_all, execute, get_db_cursor, get_next_sequence_val, execute_returning_id, get_next_order_number
from services.csv_exchange import resolve_customer_phone_and_name

branches_bp = Blueprint('branches', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}

# Standard Permissions Matrix for Store Branches
DEFAULT_BRANCH_PERMISSIONS = {
    'dashboard': True,        # Branch KPI Dashboard & Metrics
    'pos': True,              # POS Counter Quick Checkout
    'sales_orders': True,     # Create & Manage Sales Orders
    'invoices': True,         # View & Print Official Invoices
    'inventory': True,        # View Products & Stock Levels
    'transfers': True,        # Request & View Stock Transfers from HQ
    'adjustments': False,     # Stock Adjustments (Restricted by default)
    'purchasing': False,      # Direct Purchase Orders (Restricted by default)
    'expenses': True,         # Record Daily Branch Expenses & Cash
    'customers': True,        # View & Add Customers
    'reports': True,          # Branch Financial & Sales Reports
    'settings': True,         # Branch Theme, Invoice & Import/Export Settings
    'edit_prices': False,     # Custom Price Editing at Checkout
    'view_costs': False       # View Product Cost Prices & Margins
}

# Standard Default Settings Matrix for Branch Customizations
DEFAULT_BRANCH_SETTINGS = {
    'primary_color': '#FF5A5F',
    'secondary_color': '#0F172A',
    'font_family': 'Kantumruy Pro',
    'template_style': 'modern',       # 'modern', 'classic', 'thermal_80mm', 'minimal'
    'invoice_title_kh': 'វិក្កយបត្រ',
    'invoice_title_en': 'INVOICE',
    'shop_name_kh': '',
    'shop_name_en': '',
    'shop_address_kh': '',
    'shop_address_en': '',
    'phone': '',
    'email': '',
    'website': '',
    'vat_tin': '',
    'logo_url': '',
    'enable_khr_total': True,
    'khr_exchange_rate': 4100.00,
    'qr_code_url': '',
    'bank_name': 'ABA Bank (KHQR / Bakong)',
    'account_name': '',
    'account_number': '',
    'payment_terms': 'ទូទាត់ភ្លាមៗ / Due on receipt',
    'footer_notes_kh': 'ទំនិញដែលបានទិញរួចមិនអាចប្តូរវិញបានទេ! សូមអរគុណចំពោះការគាំទ្ររបស់លោកអ្នក!',
    'footer_notes_en': 'Goods sold are not returnable. Thank you for your business!',
    'show_signature': True,
    'seller_signature_url': None,
    'seller_name': None,
    'show_sku': True,
    'show_tax': True,
    'paper_size': 'A5',
    'qr_size': 180,
    'qr_position': 'left',
    'bank_info_size': '8.5',
    'bank_info_position': 'below_qr',
    'qr_offset_x': 0,
    'qr_offset_y': 0,
    'bank_offset_x': 0,
    'bank_offset_y': 0,
    'unit_price_decimals': 3
}

def _get_branch_permissions(branch_or_raw):
    """Parses and returns a normalized permissions dictionary for a branch."""
    if not branch_or_raw:
        return DEFAULT_BRANCH_PERMISSIONS.copy()
    raw = branch_or_raw.get('permissions_json') if isinstance(branch_or_raw, dict) else branch_or_raw
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    elif not isinstance(raw, dict):
        raw = {}
    
    perms = DEFAULT_BRANCH_PERMISSIONS.copy()
    for k in DEFAULT_BRANCH_PERMISSIONS.keys():
        if k in raw:
            perms[k] = bool(raw[k])

    # If current user is a branch staff/admin (not main_admin), intersect with user account permissions
    from flask import session
    role = session.get('role')
    if role and role != 'main_admin':
        user_perms = session.get('permissions')
        if isinstance(user_perms, str):
            try:
                user_perms = json.loads(user_perms)
            except Exception:
                user_perms = {}
        if isinstance(user_perms, dict):
            for k in DEFAULT_BRANCH_PERMISSIONS.keys():
                if k in user_perms:
                    perms[k] = bool(perms.get(k, False)) and bool(user_perms[k])

    return perms

def _get_branch_settings(branch_or_raw):
    """Retrieves normalized settings dictionary for a branch."""
    settings = DEFAULT_BRANCH_SETTINGS.copy()
    if not branch_or_raw:
        return settings
    
    raw = branch_or_raw.get('settings_json') if isinstance(branch_or_raw, dict) else branch_or_raw
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    elif not isinstance(raw, dict):
        raw = {}
    
    for k, v in raw.items():
        if v is not None:
            settings[k] = v

    # Fallbacks from branch profile if not customized
    if isinstance(branch_or_raw, dict):
        if not settings.get('primary_color') and branch_or_raw.get('color'):
            settings['primary_color'] = branch_or_raw['color']
        if not settings.get('shop_name_en') and branch_or_raw.get('name'):
            settings['shop_name_en'] = branch_or_raw['name']
        if not settings.get('phone') and branch_or_raw.get('phone'):
            settings['phone'] = branch_or_raw['phone']
        if not settings.get('shop_address_en') and branch_or_raw.get('address'):
            settings['shop_address_en'] = branch_or_raw['address']

    # Retrieve uploaded KHQR and banking info from Invoice Customization (invoice_settings)
    # ONLY as a fallback if the branch has NOT configured its own!
    try:
        from routes.settings import get_invoice_settings
        inv_set = get_invoice_settings()
        if inv_set:
            if not raw.get('qr_code_url') and inv_set.get('qr_code_url'):
                settings['qr_code_url'] = inv_set['qr_code_url']
            if not raw.get('bank_name') and inv_set.get('bank_name'):
                settings['bank_name'] = inv_set['bank_name']
            if not raw.get('account_name') and inv_set.get('account_name'):
                settings['account_name'] = inv_set['account_name']
            if not raw.get('account_number') and inv_set.get('account_number'):
                settings['account_number'] = inv_set['account_number']
            if not raw.get('khr_exchange_rate') and inv_set.get('khr_exchange_rate'):
                settings['khr_exchange_rate'] = float(inv_set['khr_exchange_rate'])
            if not raw.get('unit_price_decimals') and inv_set.get('unit_price_decimals'):
                settings['unit_price_decimals'] = int(inv_set['unit_price_decimals'])
    except Exception:
        pass

    return settings

def _get_central_location_id(cur=None):
    """Returns the central warehouse ID where inventory is shared and deducted."""
    sql = "SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1"
    if cur:
        cur.execute(sql)
        row = cur.fetchone()
    else:
        row = query_one(sql)
    if not row:
        sql_fallback = "SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1"
        row = cur.fetchone() if cur else query_one(sql_fallback)
    return row['id'] if row else 100

# ====================================================================
# 1. MAIN STORE BRANCH DIRECTORY & MANAGEMENT
# ====================================================================

@branches_bp.before_request
def check_branch_route_access():
    """
    Enforces strict branch isolation across all branch routes:
    - Branch users can only access their assigned branch (id == user_bid) and cannot access HQ branch directory.
    - HQ (main_admin) can access all branches unrestricted.
    """
    user_role = session.get('role', 'branch_admin')
    if user_role == 'main_admin':
        return None  # HQ admin has unrestricted access to all branches

    user_bid = session.get('branch_id')

    # If branch user tries to view the overall branches directory (branches.list_branches)
    if request.endpoint == 'branches.list_branches':
        if user_bid:
            return redirect(url_for('branches.branch_workspace', id=user_bid))
        return redirect(url_for('sales_orders.list_orders'))

    # If an id parameter is in view_args, verify it matches the user's assigned branch
    if request.view_args and 'id' in request.view_args:
        try:
            target_bid = int(request.view_args['id'])
            if user_bid and int(user_bid) != target_bid:
                flash("You do not have permission to access another branch. / អ្នកមិនមានសិទ្ធិចូលមើលសាខាផ្សេងទេ", "warning")
                if request.is_json:
                    return jsonify({'error': 'Access denied: cannot access another branch'}), 403
                return redirect(url_for('branches.branch_workspace', id=user_bid))
        except (ValueError, TypeError):
            pass

    return None

@branches_bp.route('/branches')
def list_branches():
    """List all store branches with aggregated sales & expense performance."""
    status_filter = request.args.get('status', 'all').strip().lower()

    where_clause = ""
    if status_filter == 'active':
        where_clause = "WHERE b.is_active = TRUE"
    elif status_filter == 'inactive':
        where_clause = "WHERE b.is_active = FALSE"

    branches = query_all(f"""
        SELECT 
            b.*,
            l.name as location_name,
            COALESCE(sales.total_orders, 0) as total_orders,
            COALESCE(sales.total_revenue, 0) as total_revenue,
            COALESCE(exp.total_expenses, 0) as total_expenses,
            (COALESCE(sales.total_revenue, 0) - COALESCE(exp.total_expenses, 0)) as net_balance
        FROM branches b
        LEFT JOIN locations l ON b.location_id = l.id
        LEFT JOIN (
            SELECT 
                branch_id, 
                COUNT(id) as total_orders, 
                SUM(total_amount) as total_revenue
            FROM sales_orders
            WHERE status NOT IN ('CANCELLED')
            GROUP BY branch_id
        ) sales ON b.id = sales.branch_id
        LEFT JOIN (
            SELECT 
                branch_id, 
                SUM(total_price) as total_expenses
            FROM expenses
            GROUP BY branch_id
        ) exp ON b.id = exp.branch_id
        {where_clause}
        ORDER BY b.id ASC
    """)

    for b in branches:
        b['permissions'] = _get_branch_permissions(b)

    # Locations for branch link dropdown
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE ORDER BY name ASC")
    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")

    return render_template('branches/list.html', 
                           branches=branches, 
                           status_filter=status_filter,
                           locations=locations,
                           central_wh=central_wh)

@branches_bp.route('/branches/<int:id>')
def view_branch(id):
    """View details, daily stats, recent orders, and permissions for a specific branch."""
    branch = query_one("""
        SELECT b.*, l.name as location_name
        FROM branches b
        LEFT JOIN locations l ON b.location_id = l.id
        WHERE b.id = %s
    """, (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    branch['permissions'] = perms

    # Recent sales orders for this branch
    orders = query_all("""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.branch_id = %s
        ORDER BY so.order_date DESC, so.id DESC
        LIMIT 25
    """, (id,))

    # Recent expenses for this branch
    expenses = query_all("""
        SELECT * FROM expenses
        WHERE branch_id = %s
        ORDER BY expense_date DESC, id DESC
        LIMIT 25
    """, (id,))

    # Today's stats
    today_stats = query_one("""
        SELECT 
            COUNT(id) as today_orders,
            COALESCE(SUM(total_amount), 0) as today_sales,
            COALESCE(SUM(paid_amount), 0) as today_cash
        FROM sales_orders
        WHERE branch_id = %s AND order_date = CURRENT_DATE AND status NOT IN ('CANCELLED')
    """, (id,)) or {'today_orders': 0, 'today_sales': 0, 'today_cash': 0}

    # Month's stats
    current_month = datetime.now().strftime('%Y-%m')
    month_stats = query_one("""
        SELECT 
            COALESCE(SUM(total_amount), 0) as month_sales,
            COALESCE(SUM(paid_amount), 0) as month_collected
        FROM sales_orders
        WHERE branch_id = %s AND TO_CHAR(order_date, 'YYYY-MM') = %s AND status NOT IN ('CANCELLED')
    """, (id, current_month)) or {'month_sales': 0, 'month_collected': 0}

    month_exp = query_one("""
        SELECT COALESCE(SUM(total_price), 0) as month_expenses
        FROM expenses
        WHERE branch_id = %s AND month_key = %s
    """, (id, current_month)) or {'month_expenses': 0}

    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE ORDER BY name ASC")

    return render_template('branches/detail.html',
                           branch=branch,
                           perms=perms,
                           orders=orders,
                           expenses=expenses,
                           today_stats=today_stats,
                           month_stats=month_stats,
                           month_exp=month_exp,
                           current_month=current_month,
                           central_wh=central_wh,
                           locations=locations)

@branches_bp.route('/branches/create', methods=['POST'])
def create_branch():
    """Create a new branch with assigned warehouse location and default permissions."""
    try:
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        address = request.form.get('address', '').strip() or None
        manager_name = request.form.get('manager_name', '').strip() or None
        so_prefix = request.form.get('so_prefix', '').strip().upper() or f"SO-{code}-"
        loc_id = int(request.form.get('location_id')) if request.form.get('location_id') else None

        if not code or not name:
            flash("Branch Code and Name are required.", "error")
            return redirect(url_for('branches.list_branches'))

        existing = query_one("SELECT id FROM branches WHERE UPPER(code) = %s", (code,))
        if existing:
            flash(f"Branch with code '{code}' already exists.", "error")
            return redirect(url_for('branches.list_branches'))

        default_perms = DEFAULT_BRANCH_PERMISSIONS.copy()

        execute("""
            INSERT INTO branches (code, name, phone, address, manager_name, so_prefix, location_id, permissions_json, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE);
        """, (code, name, phone, address, manager_name, so_prefix, loc_id, json.dumps(default_perms)))

        flash(f"Branch '{name}' created successfully with full function options!", "success")
        return redirect(url_for('branches.list_branches'))
    except Exception as e:
        flash(f"Error creating branch: {e}", "error")
        return redirect(url_for('branches.list_branches'))

@branches_bp.route('/branches/<int:id>/edit', methods=['POST'])
def edit_branch(id):
    """Update branch profile details."""
    try:
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        address = request.form.get('address', '').strip() or None
        manager_name = request.form.get('manager_name', '').strip() or None
        so_prefix = request.form.get('so_prefix', '').strip().upper() or f"SO-{code}-"
        loc_id = int(request.form.get('location_id')) if request.form.get('location_id') else None

        if not code or not name:
            flash("Branch Code and Name are required.", "error")
            return redirect(request.referrer or url_for('branches.list_branches'))

        dup = query_one("SELECT id FROM branches WHERE UPPER(code) = %s AND id != %s", (code, id))
        if dup:
            flash(f"Another branch already has code '{code}'.", "error")
            return redirect(request.referrer or url_for('branches.list_branches'))

        execute("""
            UPDATE branches
            SET code = %s, name = %s, phone = %s, address = %s, 
                manager_name = %s, so_prefix = %s, location_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (code, name, phone, address, manager_name, so_prefix, loc_id, id))

        flash(f"Branch '{name}' profile updated successfully!", "success")
        return redirect(request.referrer or url_for('branches.view_branch', id=id))
    except Exception as e:
        flash(f"Error updating branch: {e}", "error")
        return redirect(request.referrer or url_for('branches.view_branch', id=id))

@branches_bp.route('/branches/<int:id>/permissions', methods=['POST'])
def update_branch_permissions(id):
    """
    Main Store controls what the branch shop is allowed to use and see.
    Toggles functions like Dashboard, POS, Sales, Stock, Expenses, Reports, Costs.
    """
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Branch not found'}), 404
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    try:
        if request.is_json:
            data = request.get_json() or {}
            new_perms = _get_branch_permissions(data)
        else:
            new_perms = {}
            for key in DEFAULT_BRANCH_PERMISSIONS.keys():
                new_perms[key] = (request.form.get(f'perm_{key}') in ('on', 'true', '1', True))

        execute("""
            UPDATE branches
            SET permissions_json = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (json.dumps(new_perms), id))

        flash(f"Branch permissions for '{branch['name']}' updated successfully by Main Store!", "success")
        if request.is_json:
            return jsonify({'success': True, 'permissions': new_perms, 'message': 'Permissions saved successfully.'})
        return redirect(request.referrer or url_for('branches.view_branch', id=id))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error updating permissions: {e}", "error")
        return redirect(request.referrer or url_for('branches.view_branch', id=id))

@branches_bp.route('/branches/<int:id>/delete', methods=['POST'])
def delete_branch(id):
    """Delete branch."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    try:
        execute("DELETE FROM branches WHERE id = %s", (id,))
        flash(f"Branch '{branch['name']}' ({branch['code']}) has been deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting branch: {e}", "error")

    return redirect(url_for('branches.list_branches'))

@branches_bp.route('/branches/<int:id>/toggle_status', methods=['POST'])
def toggle_branch_status(id):
    """Toggle branch active / inactive status."""
    branch = query_one("SELECT id, name, is_active FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    new_status = not branch['is_active']
    execute("UPDATE branches SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, id))
    state_str = "activated" if new_status else "deactivated"
    flash(f"Branch '{branch['name']}' has been {state_str}.", "success")
    return redirect(request.referrer or url_for('branches.list_branches'))

# ====================================================================
# 2. STORE CONTEXT SWITCHER (Main Store <-> Branch Shops)
# ====================================================================

@branches_bp.route('/branches/switch/<int:id>')
def switch_branch(id):
    """
    Switches active store context:
    - id = 0: Switches to Main Store (HQ / Enterprise view)
    - id > 0: Switches to Branch Shop Workspace
    """
    user_role = session.get('role')
    user_bid = session.get('branch_id')
    if user_role in ('branch_admin', 'branch_cashier') and user_bid and id != user_bid:
        flash(f"🔒 Access Restricted: You are logged in as Branch Admin and can only access Branch #{user_bid}. / គ្មានសិទ្ធិចូលសាខាផ្សេងទេ", "error")
        return redirect(url_for('branches.branch_workspace', id=user_bid))

    if id == 0:
        session.pop('active_branch_id', None)
        flash("🏢 Switched to Main Store (HQ - Headquarters). Full enterprise view active.", "info")
        return redirect(url_for('dashboard.index'))

    branch = query_one("SELECT * FROM branches WHERE id = %s AND is_active = TRUE", (id,))
    if not branch:
        flash("Branch not found or inactive.", "error")
        return redirect(url_for('branches.list_branches'))

    session['active_branch_id'] = id
    flash(f"🏪 Switched to {branch['name']} ({branch['code']}). Branch Workspace mode active.", "success")
    return redirect(url_for('branches.branch_workspace', id=id))

@branches_bp.route('/branches/launch')
def branch_launcher():
    """
    Branch System Launcher Portal.
    Lists all active branches with one-click 'Launch System' buttons.
    """
    branches = query_all("""
        SELECT b.*, l.name as location_name,
               COALESCE(sales.total_orders, 0) as total_orders,
               COALESCE(sales.total_revenue, 0) as total_revenue
        FROM branches b
        LEFT JOIN locations l ON b.location_id = l.id
        LEFT JOIN (
            SELECT branch_id, COUNT(id) as total_orders, SUM(total_amount) as total_revenue
            FROM sales_orders WHERE status NOT IN ('CANCELLED')
            GROUP BY branch_id
        ) sales ON b.id = sales.branch_id
        WHERE b.is_active = TRUE
        ORDER BY b.id ASC
    """)
    for b in branches:
        b['permissions'] = _get_branch_permissions(b)
    
    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    return render_template('branches/launcher.html', branches=branches, central_wh=central_wh)

@branches_bp.route('/branches/<int:id>/launch')
def launch_branch_system(id):
    """
    Direct one-click launcher for a specific branch.
    Sets active branch session context and navigates into the branch system.
    """
    branch = query_one("SELECT * FROM branches WHERE id = %s AND is_active = TRUE", (id,))
    if not branch:
        flash("Branch not found or currently inactive.", "error")
        return redirect(url_for('branches.list_branches'))
    
    session['active_branch_id'] = id
    flash(f"🚀 Launched {branch['name']} ({branch['code']}) System!", "success")
    return redirect(url_for('branches.branch_workspace', id=id))

# ====================================================================
# 3. CLONED BRANCH FUNCTIONS & WORKSPACE
# ====================================================================

@branches_bp.route('/branches/<int:id>/workspace')
@branches_bp.route('/branches/<int:id>/dashboard')
def branch_workspace(id):
    """
    Complete Cloned Branch Workspace & Dashboard.
    Provides full feature parity with Main Store, governed by Main Store permission controls.
    """
    branch = query_one("""
        SELECT b.*, l.name as location_name 
        FROM branches b 
        LEFT JOIN locations l ON b.location_id = l.id 
        WHERE b.id = %s
    """, (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    branch['permissions'] = perms
    b_settings = _get_branch_settings(branch)
    branch['settings'] = b_settings
    branch['primary_color'] = b_settings.get('primary_color') or branch.get('color') or '#10B981'
    branch['logo_url'] = b_settings.get('logo_url') or ''

    # Branch Today Stats
    today_stats = query_one("""
        SELECT 
            COUNT(id) as today_orders,
            COALESCE(SUM(total_amount), 0) as today_sales,
            COALESCE(SUM(paid_amount), 0) as today_cash
        FROM sales_orders
        WHERE branch_id = %s AND order_date = CURRENT_DATE AND status NOT IN ('CANCELLED')
    """, (id,)) or {'today_orders': 0, 'today_sales': 0, 'today_cash': 0}

    # Month Stats
    current_month = datetime.now().strftime('%Y-%m')
    month_stats = query_one("""
        SELECT 
            COALESCE(SUM(total_amount), 0) as month_sales,
            COALESCE(SUM(paid_amount), 0) as month_collected
        FROM sales_orders
        WHERE branch_id = %s AND TO_CHAR(order_date, 'YYYY-MM') = %s AND status NOT IN ('CANCELLED')
    """, (id, current_month)) or {'month_sales': 0, 'month_collected': 0}

    month_exp = query_one("""
        SELECT COALESCE(SUM(total_price), 0) as month_expenses
        FROM expenses
        WHERE branch_id = %s AND month_key = %s
    """, (id, current_month)) or {'month_expenses': 0}

    # Recent Orders for this branch
    recent_orders = query_all("""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.branch_id = %s
        ORDER BY so.order_date DESC, so.id DESC
        LIMIT 8
    """, (id,))

    # Top Products sold at this branch
    top_products = query_all("""
        SELECT 
            p.id, p.name, p.sku, p.uom,
            SUM(sol.quantity) as total_qty_sold,
            SUM(sol.subtotal) as total_revenue
        FROM sales_order_lines sol
        JOIN sales_orders so ON sol.sales_order_id = so.id
        JOIN products p ON sol.product_id = p.id
        WHERE so.branch_id = %s AND so.status NOT IN ('CANCELLED')
        GROUP BY p.id, p.name, p.sku, p.uom
        ORDER BY total_qty_sold DESC
        LIMIT 6
    """, (id,))

    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    central_id = central_wh['id'] if central_wh else 100

    # Receivables for this branch
    receivables_stats = query_one("""
        SELECT 
            COUNT(id) as unpaid_orders_count,
            COALESCE(SUM(balance_due), 0) as total_receivables
        FROM sales_orders
        WHERE branch_id = %s AND balance_due > 0 AND status NOT IN ('CANCELLED')
    """, (id,)) or {'unpaid_orders_count': 0, 'total_receivables': 0}

    # Low stock items at Central Fulfillment
    low_stock_items = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.uom, p.default_price, p.reorder_point,
            COALESCE(inv.total_qty, 0) as current_qty,
            c.name as category_name
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty 
            FROM inventory 
            WHERE location_id = %s
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = TRUE AND p.is_sellable = TRUE
          AND p.reorder_point > 0 
          AND COALESCE(inv.total_qty, 0) <= p.reorder_point
        ORDER BY (COALESCE(inv.total_qty, 0) - p.reorder_point) ASC
        LIMIT 6
    """, (central_id,))

    return render_template('branches/dashboard.html',
                           branch=branch,
                           perms=perms,
                           today_stats=today_stats,
                           month_stats=month_stats,
                           month_exp=month_exp,
                           receivables_stats=receivables_stats,
                           recent_orders=recent_orders,
                           top_products=top_products,
                           low_stock_items=low_stock_items,
                           current_month=current_month,
                           central_wh=central_wh)

@branches_bp.route('/api/branches/<int:id>/charts')
def branch_chart_data(id):
    """Provides daily revenue trends and category distribution for branch dashboard."""
    # 1. Daily Sales Trend (Last 14 Days)
    daily_sales = query_all("""
        SELECT 
            TO_CHAR(d.day, 'Mon DD') as label,
            d.day as order_day,
            COALESCE(SUM(so.total_amount), 0) as revenue,
            COUNT(so.id) as order_count
        FROM generate_series(CURRENT_DATE - INTERVAL '13 days', CURRENT_DATE, '1 day'::interval) d(day)
        LEFT JOIN sales_orders so ON so.order_date = d.day::date AND so.branch_id = %s AND so.status NOT IN ('CANCELLED')
        GROUP BY d.day, TO_CHAR(d.day, 'Mon DD')
        ORDER BY d.day ASC
    """, (id,))

    # 2. Sales by Category for this branch
    category_sales = query_all("""
        SELECT 
            COALESCE(c.name, 'Uncategorized') as category_name,
            COALESCE(SUM(sol.subtotal), 0) as total_revenue
        FROM sales_order_lines sol
        JOIN sales_orders so ON sol.sales_order_id = so.id
        JOIN products p ON sol.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE so.branch_id = %s AND so.status NOT IN ('CANCELLED')
        GROUP BY c.name
        ORDER BY total_revenue DESC
        LIMIT 6
    """, (id,))

    if not category_sales:
        category_sales = query_all("""
            SELECT 
                COALESCE(c.name, 'Uncategorized') as category_name,
                COUNT(p.id) * 10 as total_revenue
            FROM categories c
            LEFT JOIN products p ON c.id = p.category_id
            WHERE p.is_active = TRUE
            GROUP BY c.name
            LIMIT 5
        """)

    # 3. Payment Method Breakdown for this branch
    payment_stats = query_all("""
        SELECT 
            COALESCE(payment_status, 'UNPAID') as status_label,
            COUNT(*) as order_count,
            COALESCE(SUM(total_amount), 0) as total_amount
        FROM sales_orders
        WHERE branch_id = %s AND status NOT IN ('CANCELLED')
        GROUP BY payment_status
    """, (id,))

    # 4. Monthly Sales Breakdown (Last 12 Months) - Isolated strictly to this branch (Open Sale & Paid Sale ONLY, No Profit)
    monthly_sales = query_all("""
        SELECT 
            TO_CHAR(m.month_date, 'Mon YYYY') as month_label,
            COALESCE(SUM(CASE WHEN so.status = 'PAID' OR so.payment_status = 'PAID' THEN so.total_amount ELSE 0 END), 0) as paid_sales,
            COALESCE(SUM(CASE WHEN so.status = 'OPEN' OR so.balance_due > 0 THEN so.balance_due ELSE 0 END), 0) as open_sales,
            COALESCE(SUM(so.total_amount), 0) as revenue,
            COUNT(so.id) as order_count
        FROM generate_series(
            date_trunc('month', CURRENT_DATE - INTERVAL '11 months'),
            date_trunc('month', CURRENT_DATE),
            '1 month'::interval
        ) m(month_date)
        LEFT JOIN sales_orders so 
            ON date_trunc('month', so.order_date) = m.month_date
           AND so.branch_id = %s
           AND so.status NOT IN ('CANCELLED')
        GROUP BY m.month_date
        ORDER BY m.month_date ASC
    """, (id,))

    return jsonify({
        'daily_labels': [r['label'] for r in daily_sales],
        'daily_revenue': [float(r['revenue']) for r in daily_sales],
        'daily_orders': [int(r['order_count']) for r in daily_sales],
        'monthly_labels': [r['month_label'] for r in monthly_sales],
        'monthly_paid': [round(float(r['paid_sales']), 2) for r in monthly_sales],
        'monthly_open': [round(float(r['open_sales']), 2) for r in monthly_sales],
        'monthly_revenue': [round(float(r['revenue']), 2) for r in monthly_sales],
        'monthly_orders': [int(r['order_count']) for r in monthly_sales],
        'category_labels': [r['category_name'] for r in category_sales],
        'category_values': [float(r['total_revenue']) for r in category_sales],
        'payment_labels': [r['status_label'] for r in payment_stats],
        'payment_counts': [int(r['order_count']) for r in payment_stats]
    })

@branches_bp.route('/branches/<int:id>/orders')
def branch_orders(id):
    """Branch sales order page removed; redirects directly to Paid Invoices."""
    return redirect(url_for('sales_orders.list_orders', status='PAID', branch=id))

@branches_bp.route('/branches/<int:id>/orders/new')
def branch_new_order(id):
    """
    Direct route to create a new independent inFlow Sales Order for this branch.
    Pre-configures branch context and central fulfillment warehouse.
    """
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not (perms.get('sales_orders') or perms.get('invoices')):
        flash("Sales orders are disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    session['active_branch_id'] = id
    cust_id = request.args.get('customer_id')
    return redirect(url_for('sales_orders.new_order', branch=id, customer_id=cust_id) if cust_id else url_for('sales_orders.new_order', branch=id))

@branches_bp.route('/branches/<int:id>/pos')
def branch_pos(id):
    """POS / Quick Billing counter for this branch with warehouse selection (STM Warehouse default)."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('pos'):
        flash("POS counter is disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    # Warehouses: STM Warehouse ordered first as requested
    warehouses = query_all("""
        SELECT id, name, is_default, is_central 
        FROM locations 
        WHERE is_active = TRUE AND LEFT(name, 1) != '<' 
        ORDER BY (CASE WHEN UPPER(name) LIKE %s THEN 0 ELSE 1 END), id ASC
    """, ('%STM%',))

    # Selected Warehouse (Default: STM Warehouse)
    req_wh_id = request.args.get('warehouse_id')
    selected_warehouse = None
    if req_wh_id:
        try:
            wh_int = int(req_wh_id)
            selected_warehouse = next((w for w in warehouses if w['id'] == wh_int), None)
        except Exception:
            pass

    if not selected_warehouse:
        # Default: STM Warehouse (ID: 101)
        selected_warehouse = next((w for w in warehouses if 'STM' in w['name'].upper()), None)
    if not selected_warehouse and branch.get('location_id'):
        selected_warehouse = next((w for w in warehouses if w['id'] == branch['location_id']), None)
    if not selected_warehouse and warehouses:
        selected_warehouse = warehouses[0]

    selected_wh_id = selected_warehouse['id'] if selected_warehouse else 101

    # Active categories that contain sellable products
    categories = query_all("""
        SELECT c.id, c.name, COUNT(p.id) as product_count
        FROM categories c
        JOIN products p ON c.id = p.category_id AND p.is_active = TRUE AND p.is_sellable = TRUE
        WHERE c.is_active = TRUE
        GROUP BY c.id, c.name
        ORDER BY product_count DESC, c.name ASC
    """)

    # Products with stock quantity at the selected warehouse
    products = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.image_url,
            COALESCE(NULLIF(p.default_price, 0), pp_def.unit_price, 0) as default_price,
            p.sales_uom, p.sales_uom_ratio_std,
            CASE 
                WHEN p.sales_uom_ratio_std > 0 AND p.pcs_per_pack > 0 
                THEN ROUND((p.sales_uom_ratio_std / p.pcs_per_pack)::numeric, 2)
                ELSE COALESCE(p.packs_per_case, 1)
            END as packs_per_case,
            COALESCE(NULLIF(p.pcs_per_pack, 0), 50) as pcs_per_pack,
            p.category_id,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(i.quantity, 0) as stock_qty,
            COALESCE(s.order_count, 0) as order_count,
            COALESCE(s.total_sold_qty, 0) as total_sold_qty
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i ON p.id = i.product_id AND i.location_id = %s
        LEFT JOIN product_prices pp_def ON p.id = pp_def.product_id AND pp_def.pricing_scheme_id = 100
        LEFT JOIN (
            SELECT 
                sol.product_id, 
                SUM(sol.quantity) as total_sold_qty, 
                COUNT(DISTINCT sol.sales_order_id) as order_count
            FROM sales_order_lines sol
            GROUP BY sol.product_id
        ) s ON p.id = s.product_id
        WHERE p.is_active = TRUE AND p.is_sellable = TRUE
        ORDER BY p.name ASC
    """, (selected_wh_id,))

    pricing_schemes = query_all("SELECT id, name, is_active FROM pricing_schemes WHERE is_active = TRUE ORDER BY id ASC")
    all_prices = query_all("SELECT product_id, pricing_scheme_id, unit_price FROM product_prices")
    product_prices_map = {}
    for pr in all_prices:
        pid = pr['product_id']
        if pid not in product_prices_map:
            product_prices_map[pid] = {}
        product_prices_map[pid][pr['pricing_scheme_id']] = float(pr['unit_price'] or 0)

    customers = query_all("""
        SELECT id, name, phone, balance, default_pricing_scheme_id 
        FROM customers 
        WHERE is_active = TRUE AND branch_id = %s 
        ORDER BY name ASC
    """, (id,))

    branch_settings = _get_branch_settings(branch)

    # Branch Color Scheme matching user's branch settings or branch color
    branch_color = (branch.get('color') or (branch_settings.get('primary_color') if branch_settings else None) or '#10B981').strip()
    h = branch_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        branch_color_rgb = f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"
    except Exception:
        branch_color_rgb = "16, 185, 129"

    # Branch Favorite Products
    favorite_product_ids = branch_settings.get('favorite_product_ids') or []
    if not isinstance(favorite_product_ids, list):
        favorite_product_ids = []
    favorite_product_ids = [int(x) for x in favorite_product_ids if str(x).isdigit()]

    from database import preview_order_number
    pos_preview_number = preview_order_number('POS', branch_id=id) or f"SO-{(branch.get('code') or 'STM').strip().upper()}-P-00001"
    cashier_name = session.get('username') or session.get('display_name') or branch.get('manager_name') or 'Cashier'

    return render_template('branches/pos.html',
                           branch=branch,
                           branch_settings=branch_settings,
                           branch_color=branch_color,
                           branch_color_rgb=branch_color_rgb,
                           favorite_product_ids=favorite_product_ids,
                           cashier_name=cashier_name,
                           pos_preview_number=pos_preview_number,
                           perms=perms,
                           warehouses=warehouses,
                           selected_warehouse=selected_warehouse,
                           categories=categories,
                           products=products,
                           customers=customers,
                           pricing_schemes=pricing_schemes,
                           product_prices_map=product_prices_map)

@branches_bp.route('/branches/<int:id>/pos/toggle_favorite', methods=['POST'])
def branch_pos_toggle_favorite(id):
    """Persists favorite product state for this branch."""
    try:
        data = request.get_json(force=True) or {}
        product_id = int(data.get('product_id') or 0)
        if not product_id:
            return jsonify({'success': False, 'message': 'Missing product_id'}), 400

        branch = query_one("SELECT id, settings_json FROM branches WHERE id = %s", (id,))
        if not branch:
            return jsonify({'success': False, 'message': 'Branch not found'}), 404

        settings = branch.get('settings_json') or {}
        if not isinstance(settings, dict):
            settings = {}
        favs = set(settings.get('favorite_product_ids') or [])
        if 'is_favorite' in data:
            is_fav = bool(data['is_favorite'])
        else:
            is_fav = product_id not in favs

        if is_fav:
            favs.add(product_id)
        else:
            favs.discard(product_id)

        settings['favorite_product_ids'] = sorted(list(favs))
        execute("UPDATE branches SET settings_json = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (json.dumps(settings), id))
        return jsonify({'success': True, 'is_favorite': is_fav, 'favorite_product_ids': settings['favorite_product_ids']})
    except Exception as e:
        logger.error(f"Error toggling favorite product: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@branches_bp.route('/branches/<int:id>/pos/checkout', methods=['POST'])
def branch_checkout(id):
    """
    Submits a branch sale.
    Atomically deducts stock from the chosen warehouse (default: STM Warehouse) in real-time.
    Supports UOM (Pack, Case, Pcs), pricing schemes, and Sales Order payment methods.
    """
    try:
        data = request.get_json() or {}
        branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
        if not branch:
            return jsonify({'success': False, 'message': 'Branch not found.'}), 404

        items = data.get('items', [])
        if not items:
            return jsonify({'success': False, 'message': 'No items selected.'}), 400

        customer_id = data.get('customer_id') or None
        if customer_id:
            cust_chk = query_one("SELECT branch_id FROM customers WHERE id = %s", (int(customer_id),))
            if cust_chk and cust_chk.get('branch_id') != id:
                return jsonify({'success': False, 'message': 'Selected customer does not belong to this branch. Customer of HQ and Branch are kept independently.'}), 400
        discount_amount = max(0.0, float(data.get('discount_amount') or 0.0))
        force_checkout = bool(data.get('force_checkout') or data.get('accept_out_of_stock'))

        payment_method = str(data.get('payment_method') or 'Cash').strip()
        paid_amount = float(data.get('paid_amount') if data.get('paid_amount') is not None else data.get('total_amount', 0.0))

        with get_db_cursor(commit=True) as cur:
            # Determine target warehouse location (STM Warehouse by default)
            wh_req_id = data.get('warehouse_id')
            wh_row = None
            if wh_req_id:
                try:
                    cur.execute("SELECT id, name FROM locations WHERE id = %s", (int(wh_req_id),))
                    wh_row = cur.fetchone()
                except Exception:
                    pass
            if not wh_row:
                cur.execute("SELECT id, name FROM locations WHERE UPPER(name) LIKE %s LIMIT 1", ('%STM%',))
                wh_row = cur.fetchone()
            if not wh_row:
                central_loc_id = _get_central_location_id(cur)
                cur.execute("SELECT id, name FROM locations WHERE id = %s", (central_loc_id,))
                wh_row = cur.fetchone()

            target_loc_id = wh_row['id'] if wh_row else 101
            target_loc_name = wh_row['name'] if wh_row else 'STM Warehouse'

            order_number = get_next_order_number('POS', branch_id=id, cur=cur)

            # 1. Lock and validate inventory at target warehouse & calculate line subtotals
            calc_subtotal = 0.0
            insufficient_items = []
            for it in items:
                pid = int(it['product_id'])
                qty = float(it['quantity'])
                uom = str(it.get('uom') or 'Pack').strip()
                total_pcs = float(it.get('total_pcs') or qty)
                price = float(it.get('unit_price', 0))
                scheme_id = int(it.get('pricing_scheme_id') or 100)

                it['verified_price'] = price
                it['verified_subtotal'] = qty * price
                it['deduct_qty'] = total_pcs
                calc_subtotal += (qty * price)

                cur.execute("""
                    SELECT quantity 
                    FROM inventory 
                    WHERE product_id = %s AND location_id = %s 
                    FOR UPDATE
                """, (pid, target_loc_id))
                inv_row = cur.fetchone()
                current_qty = float(inv_row['quantity']) if inv_row else 0.0

                if current_qty < total_pcs:
                    cur.execute("SELECT name, sku FROM products WHERE id = %s", (pid,))
                    p_info = cur.fetchone()
                    p_name = p_info['name'] if p_info else f"Product #{pid}"
                    insufficient_items.append({
                        'product_id': pid,
                        'name': p_name,
                        'sku': p_info['sku'] if p_info else '',
                        'available': current_qty,
                        'requested': total_pcs,
                        'qty': qty,
                        'uom': uom,
                        'shortage': total_pcs - current_qty
                    })

            # Check if any items have insufficient stock and user has not confirmed force checkout
            if insufficient_items and not force_checkout:
                item_names = [f"'{x['name']}' (ស្តុក: {x['available']:g} pcs, ត្រូវការ: {x['requested']:g} pcs)" for x in insufficient_items]
                msg = f"ទំនិញមិនមានស្តុកគ្រប់គ្រាន់នៅ {target_loc_name} ទេ៖\n" + "\n".join(item_names) + "\n\nសូមពិនិត្យស្តុកឡើងវិញ ឬចុច 'Accept & Process' ដើម្បីបន្តការលក់។"
                return jsonify({
                    'success': False,
                    'needs_stock_confirmation': True,
                    'warehouse_name': target_loc_name,
                    'insufficient_items': insufficient_items,
                    'message': msg
                }), 200

            # 2. Insert Sales Order stamped with branch_id and target warehouse
            subtotal = calc_subtotal
            total_amount = max(0.0, subtotal - discount_amount)
            balance_due = max(0.0, total_amount - paid_amount)
            pay_status = 'PAID' if balance_due <= 0 else ('PARTIAL' if paid_amount > 0 else 'UNPAID')

            cashier_login_name = session.get('username') or session.get('display_name') or branch.get('manager_name') or 'Cashier'
            note_suffix = " (Stock Override / Out of Stock Accepted)" if insufficient_items else ""
            cur.execute("""
                INSERT INTO sales_orders (
                    order_number, customer_id, branch_id, location_id, order_date,
                    status, payment_status, subtotal, discount_amount,
                    total_amount, paid_amount, balance_due, notes, completed_by, sales_rep
                ) VALUES (
                    %s, %s, %s, %s, CURRENT_DATE,
                    'INVOICED', %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                ) RETURNING id;
            """, (
                order_number, customer_id, id, target_loc_id,
                pay_status, subtotal, discount_amount,
                total_amount, paid_amount, balance_due,
                f"POS Sale via {payment_method} from {branch['name']} ({target_loc_name}){note_suffix}",
                cashier_login_name, cashier_login_name
            ))
            so_id = cur.fetchone()['id']

            # 3. Insert lines, deduct target warehouse stock, and write audit log
            for idx, it in enumerate(items, 1):
                pid = int(it['product_id'])
                qty = float(it['quantity'])
                price = float(it.get('verified_price', it.get('unit_price', 0)))
                line_sub = float(it.get('verified_subtotal', qty * price))
                uom = str(it.get('uom') or 'Pack').strip()
                deduct_pcs = float(it.get('deduct_qty') or it.get('total_pcs') or qty)
                line_scheme_id = int(it.get('pricing_scheme_id') or 100)

                cur.execute("SELECT name FROM products WHERE id = %s", (pid,))
                p_r = cur.fetchone()
                p_name = p_r['name'] if p_r else f"Product #{pid}"

                cur.execute("""
                    INSERT INTO sales_order_lines (
                        sales_order_id, line_num, product_id, description,
                        quantity, unit_price, discount_percent, subtotal,
                        uom, quantity_display, pricing_scheme_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, 0.0, %s, %s, %s, %s);
                """, (so_id, idx, pid, p_name, deduct_pcs, price, line_sub, uom, qty, line_scheme_id))

                # Deduct target warehouse inventory
                cur.execute("""
                    SELECT quantity FROM inventory 
                    WHERE product_id = %s AND location_id = %s 
                    FOR UPDATE;
                """, (pid, target_loc_id))
                exist_inv = cur.fetchone()
                if exist_inv:
                    cur.execute("""
                        UPDATE inventory
                        SET quantity = quantity - %s, updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s AND location_id = %s
                        RETURNING quantity;
                    """, (deduct_pcs, pid, target_loc_id))
                    updated_stock = float(cur.fetchone()['quantity'])
                else:
                    cur.execute("""
                        INSERT INTO inventory (product_id, location_id, quantity, updated_at)
                        VALUES (%s, %s, -%s, CURRENT_TIMESTAMP)
                        RETURNING quantity;
                    """, (pid, target_loc_id, deduct_pcs))
                    updated_stock = float(cur.fetchone()['quantity'])

                # Insert into Stock Audit Ledger with branch and warehouse attribution
                is_override = any(x['product_id'] == pid for x in insufficient_items)
                log_reason = f"POS Sale ({qty:g} {uom} = {deduct_pcs:g} pcs) at {branch['name']}"
                if is_override:
                    log_reason += " [Stock Override Accepted]"

                cur.execute("""
                    INSERT INTO inventory_logs (
                        product_id, movement_type, reference_type, reference_id,
                        from_location_id, quantity, qty_before, qty_after, branch_id, reason
                    ) VALUES (
                        %s, 'SALE_SHIP', 'SO', %s,
                        %s, %s, %s, %s, %s, %s
                    );
                """, (
                    pid, order_number, target_loc_id,
                    deduct_pcs, updated_stock + deduct_pcs, updated_stock,
                    id, log_reason
                ))

            # 4. Record Payment if paid
            if paid_amount > 0:
                cur.execute("""
                    INSERT INTO order_payments (
                        order_type, order_id, branch_id, amount, payment_method, notes
                    ) VALUES ('SO', %s, %s, %s, %s, %s);
                """, (so_id, id, paid_amount, payment_method, f"POS Payment ({payment_method}) at {branch['name']}"))

        return jsonify({
            'success': True,
            'message': f"Sale completed successfully! Stock deducted from {target_loc_name}.",
            'sales_order_id': so_id,
            'order_number': order_number,
            'cashier_name': cashier_login_name,
            'payment_status': pay_status,
            'payment_method': payment_method,
            'subtotal': subtotal,
            'discount_amount': discount_amount,
            'total_amount': total_amount,
            'paid_amount': paid_amount,
            'balance_due': balance_due
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f"Checkout error: {str(e)}"}), 500

@branches_bp.route('/branches/<int:id>/inventory')
def branch_inventory(id):
    """Branch Inventory & Stock levels view with Central Stock availability."""
    branch = query_one("""
        SELECT b.*, l.name as location_name 
        FROM branches b 
        LEFT JOIN locations l ON b.location_id = l.id 
        WHERE b.id = %s
    """, (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('inventory'):
        flash("Inventory view is disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    central_id = central_wh['id'] if central_wh else 100
    branch_loc_id = branch.get('location_id') or central_id

    search = request.args.get('search', '').strip()
    category_id = request.args.get('category_id', '').strip()

    where_clauses = ["p.is_active = TRUE", "p.is_sellable = TRUE"]
    params = [central_id, branch_loc_id]

    if search:
        where_clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)")
        sp = f"%{search}%"
        params.extend([sp, sp, sp])
    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(int(category_id))

    where_sql = " AND ".join(where_clauses)
    products = query_all(f"""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.sales_uom, p.uom,
            p.default_price, p.standard_cost, p.average_cost,
            c.name as category_name,
            COALESCE(i_cent.quantity, 0) as central_stock,
            COALESCE(i_br.quantity, 0) as branch_stock
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i_cent ON p.id = i_cent.product_id AND i_cent.location_id = %s
        LEFT JOIN inventory i_br ON p.id = i_br.product_id AND i_br.location_id = %s
        WHERE {where_sql}
        ORDER BY p.name ASC
    """, tuple(params))

    categories = query_all("SELECT id, name FROM categories WHERE is_active = TRUE ORDER BY name ASC")

    return render_template('branches/inventory.html',
                           branch=branch,
                           perms=perms,
                           products=products,
                           categories=categories,
                           search=search,
                           category_id=category_id,
                           central_wh=central_wh)

@branches_bp.route('/branches/<int:id>/transfers')
def branch_transfers(id):
    """Stock transfers between Central Main Store and this Branch."""
    branch = query_one("""
        SELECT b.*, l.name as location_name 
        FROM branches b 
        LEFT JOIN locations l ON b.location_id = l.id 
        WHERE b.id = %s
    """, (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('transfers'):
        flash("Stock transfers are disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    branch_loc_id = branch.get('location_id') or 101

    transfers = query_all("""
        SELECT st.*, 
               fl.name as from_location_name,
               tl.name as to_location_name
        FROM stock_transfers st
        LEFT JOIN locations fl ON st.from_location_id = fl.id
        LEFT JOIN locations tl ON st.to_location_id = tl.id
        WHERE st.branch_id = %s OR st.to_location_id = %s OR st.from_location_id = %s
        ORDER BY st.transfer_date DESC, st.id DESC
        LIMIT 50
    """, (id, branch_loc_id, branch_loc_id))

    # Active products list for quick replenishment modal
    products = query_all("SELECT id, sku, name, uom FROM products WHERE is_active = TRUE ORDER BY name ASC LIMIT 100")

    return render_template('branches/transfers.html',
                           branch=branch,
                           perms=perms,
                           transfers=transfers,
                           products=products,
                           central_wh=central_wh)

@branches_bp.route('/branches/<int:id>/transfers/request', methods=['POST'])
def request_branch_transfer(id):
    """Submit a replenishment transfer request from Central Warehouse to this Branch."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    from_loc_id = central_wh['id'] if central_wh else 100
    to_loc_id = branch.get('location_id') or 101

    notes = request.form.get('notes', '').strip() or f"Stock replenishment for {branch['name']}"

    try:
        seq = get_next_sequence_val('trf_number_seq')
        trf_num = f"TRF-{seq:05d}"
        execute("""
            INSERT INTO stock_transfers (transfer_number, from_location_id, to_location_id, transfer_date, status, notes, branch_id)
            VALUES (%s, %s, %s, CURRENT_DATE, 'PENDING', %s, %s)
        """, (trf_num, from_loc_id, to_loc_id, notes, id))
        flash(f"Transfer request {trf_num} created successfully! Main Store notified.", "success")
    except Exception as e:
        flash(f"Error requesting transfer: {e}", "error")

    return redirect(url_for('branches.branch_transfers', id=id))

@branches_bp.route('/branches/<int:id>/expenses')
def branch_expenses(id):
    """Branch daily expense recording and monthly summary spreadsheet."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('expenses'):
        flash("Expenses management is disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    month_key = request.args.get('month', datetime.now().strftime('%Y-%m')).strip()
    return redirect(url_for('expenses.monthly_expenses', month=month_key, branch=id))

@branches_bp.route('/branches/<int:id>/expenses/create', methods=['POST'])
def create_branch_expense(id):
    """Record a daily expense stamped with branch_id."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    try:
        item = request.form.get('item', '').strip()
        cat = request.form.get('category', 'Branch General').strip()
        price = float(request.form.get('unit_price', 0))
        qty = float(request.form.get('quantity', 1))
        tot = price * qty
        paid_by = request.form.get('paid_by', branch.get('manager_name') or 'Branch Cashier').strip()
        notes = request.form.get('notes', '').strip()
        exp_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d')).strip()
        m_key = exp_date[:7]

        execute("""
            INSERT INTO expenses (expense_date, item, category, unit_price, quantity, total_price, paid_by, notes, month_key, branch_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (exp_date, item, cat, price, qty, tot, paid_by, notes, m_key, id))

        flash(f"Expense '${tot:,.2f}' recorded for {branch['name']}!", "success")
    except Exception as e:
        flash(f"Error saving expense: {e}", "error")

    return redirect(request.referrer or url_for('expenses.monthly_expenses', month=m_key, branch=id))

@branches_bp.route('/branches/<int:id>/customers')
def branch_customers(id):
    """
    Branch customer view: Redirects to the unified master-detail customer interface,
    strictly scoped and filtered to this branch.
    """
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('customers'):
        flash("Customer management is disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    search = request.args.get('search', '').strip()
    selected_id = request.args.get('selected_id') or request.args.get('id')
    with_balance = '1' if request.args.get('tab') == 'debt' else request.args.get('with_balance', '')
    
    kwargs = {'branch': id}
    if search:
        kwargs['search'] = search
    if selected_id:
        kwargs['selected_id'] = selected_id
    if with_balance:
        kwargs['with_balance'] = with_balance
    if request.args.get('action') == 'add':
        kwargs['action'] = 'add'
        
    return redirect(url_for('contacts.list_customers', **kwargs))

@branches_bp.route('/branches/<int:id>/customers/create', methods=['POST'])
def branch_create_customer(id):
    """
    Register a new customer from the Branch.
    Automatically assigns branch_id to this branch.
    Supports both standard Form redirects and AJAX JSON responses (for modals & POS quick-add).
    """
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Branch not found'}), 404
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('customers'):
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Customer creation is not permitted for this branch'}), 403
        flash("Customer creation is disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    try:
        data = request.get_json(silent=True) or request.form
        name = data.get('name', '').strip()
        contact_name = data.get('contact_name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        address1 = data.get('address1', '').strip()
        shipping_address = data.get('shipping_address', '').strip() or address1
        billing_address = data.get('billing_address', '').strip() or address1
        city = data.get('city', '').strip() or 'Phnom Penh'
        discount_percent = float(data.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(data.get('default_pricing_scheme_id') or 0) or None
        payment_terms = data.get('payment_terms', 'Due on Receipt').strip()

        if not name:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Customer Name is required'}), 400
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.list_customers', branch=id))

        new_id = execute_returning_id("""
            INSERT INTO customers (
                name, contact_name, phone, email, address1, city,
                shipping_address, billing_address,
                discount_percent, default_pricing_scheme_id, payment_terms,
                branch_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id;
        """, (name, contact_name, phone, email, address1, city, shipping_address, billing_address,
              discount_percent, pricing_scheme_id, payment_terms, id))

        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': f"Customer '{name}' registered successfully!",
                'customer': {
                    'id': new_id,
                    'name': name,
                    'phone': phone,
                    'contact_name': contact_name,
                    'address': address1 or shipping_address,
                    'discount_percent': discount_percent,
                    'pricing_scheme_id': pricing_scheme_id
                }
            })

        flash(f"Customer '{name}' (អតិថិជនថ្មី) successfully added for branch {branch['name']}!", "success")
        return redirect(url_for('contacts.list_customers', branch=id, selected_id=new_id))

    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error creating customer: {e}", "error")
        return redirect(url_for('contacts.list_customers', branch=id))

@branches_bp.route('/branches/<int:id>/customers/<int:cust_id>/edit', methods=['POST'])
def branch_edit_customer(id, cust_id):
    """Update customer details from the branch interface."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('customers'):
        flash("Customer management is disabled for this branch.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    try:
        data = request.get_json(silent=True) or request.form
        name = data.get('name', '').strip()
        contact_name = data.get('contact_name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        address1 = data.get('address1', '').strip()
        shipping_address = data.get('shipping_address', '').strip() or address1
        billing_address = data.get('billing_address', '').strip() or address1
        city = data.get('city', '').strip() or 'Phnom Penh'
        discount_percent = float(data.get('discount_percent', 0) or 0)
        pricing_scheme_id = int(data.get('default_pricing_scheme_id') or 0) or None
        payment_terms = data.get('payment_terms', 'Due on Receipt').strip()

        if not name:
            flash("Customer Name is required.", "error")
            return redirect(url_for('contacts.list_customers', branch=id, selected_id=cust_id))

        execute("""
            UPDATE customers
            SET name = %s,
                contact_name = %s,
                phone = %s,
                email = %s,
                address1 = %s,
                city = %s,
                shipping_address = %s,
                billing_address = %s,
                discount_percent = %s,
                default_pricing_scheme_id = %s,
                payment_terms = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND branch_id = %s
        """, (name, contact_name, phone, email, address1, city, shipping_address, billing_address,
              discount_percent, pricing_scheme_id, payment_terms, cust_id, id))

        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f"Customer '{name}' updated successfully!"})

        flash(f"Customer '{name}' updated successfully!", "success")
        return redirect(url_for('contacts.list_customers', branch=id, selected_id=cust_id))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error updating customer: {e}", "error")
        return redirect(url_for('contacts.list_customers', branch=id, selected_id=cust_id))

@branches_bp.route('/branches/<int:id>/customers/api/search')
def branch_customers_search_api(id):
    """JSON API to search customers for POS and Sales Order live autocomplete."""
    q = request.args.get('q', '').strip()
    where_sql = "WHERE is_active = TRUE AND branch_id = %s"
    params = [id]
    if q:
        where_sql += " AND (name ILIKE %s OR phone ILIKE %s OR contact_name ILIKE %s)"
        sp = f"%{q}%"
        params.extend([sp, sp, sp])

    custs = query_all(f"""
        SELECT id, name, phone, contact_name, balance, discount_percent, default_pricing_scheme_id, branch_id
        FROM customers
        {where_sql}
        ORDER BY name ASC
        LIMIT 25
    """, tuple(params))
    return jsonify({'results': custs})

@branches_bp.route('/branches/<int:id>/reports')
def branch_reports(id):
    """Isolated financial and sales reporting for this branch."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    if not perms.get('reports'):
        flash("Financial reports are disabled for this branch by the Main Store.", "error")
        return redirect(url_for('branches.branch_workspace', id=id))

    month_key = request.args.get('month', datetime.now().strftime('%Y-%m')).strip()

    # Isolated branch sales
    sales_data = query_all("""
        SELECT 
            so.id, so.order_number, so.order_date, so.total_amount, so.paid_amount, so.balance_due,
            so.status, so.payment_status, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.branch_id = %s AND TO_CHAR(so.order_date, 'YYYY-MM') = %s
        ORDER BY so.order_date DESC, so.id DESC
    """, (id, month_key))

    # Isolated branch expenses
    expense_data = query_all("""
        SELECT * FROM expenses
        WHERE branch_id = %s AND month_key = %s
        ORDER BY expense_date DESC, id DESC
    """, (id, month_key))

    # Aggregates
    totals = query_one("""
        SELECT 
            COALESCE(SUM(so.total_amount), 0) as total_sales,
            COALESCE(SUM(so.paid_amount), 0) as total_collected,
            COALESCE(SUM(so.balance_due), 0) as total_unpaid
        FROM sales_orders so
        WHERE so.branch_id = %s AND TO_CHAR(so.order_date, 'YYYY-MM') = %s AND so.status NOT IN ('CANCELLED')
    """, (id, month_key)) or {'total_sales': 0, 'total_collected': 0, 'total_unpaid': 0}

    exp_total = query_one("""
        SELECT COALESCE(SUM(total_price), 0) as total_expenses
        FROM expenses
        WHERE branch_id = %s AND month_key = %s
    """, (id, month_key)) or {'total_expenses': 0}

    net_income = float(totals['total_sales']) - float(exp_total['total_expenses'])

    return render_template('branches/reports.html',
                           branch=branch,
                           perms=perms,
                           month_key=month_key,
                           sales_data=sales_data,
                           expense_data=expense_data,
                           totals=totals,
                           exp_total=exp_total,
                           net_income=net_income)

# ====================================================================
# 4. BRANCH SETTINGS, INVOICE CUSTOMIZATION & INFLOW CSV DATA EXCHANGE
# ====================================================================

@branches_bp.route('/branches/<int:id>/settings')
def branch_settings(id):
    """Branch Settings page: Customize brand color, invoice layout & inFlow CSV data import/export."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    perms = _get_branch_permissions(branch)
    settings = _get_branch_settings(branch)
    company = query_one("SELECT * FROM companies LIMIT 1")
    active_tab = request.args.get('tab', 'theme')

    warehouses = query_all("""
        SELECT id, name, is_default, is_central 
        FROM locations 
        WHERE is_active = TRUE AND LEFT(name, 1) != '<' 
        ORDER BY id ASC
    """)
    central_wh = query_one("SELECT id, name FROM locations WHERE is_central = TRUE LIMIT 1") or query_one("SELECT id, name FROM locations WHERE is_default = TRUE LIMIT 1")
    branch_users = query_all("""
        SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.branch_id,
               u.is_active, u.last_login, u.created_at, u.permissions_json
        FROM users u
        WHERE u.branch_id = %s
        ORDER BY u.id ASC
    """, (id,))

    return render_template('branches/settings.html',
                           branch=branch,
                           perms=perms,
                           settings=settings,
                           inv_settings=settings,
                           company=company,
                           active_tab=active_tab,
                           warehouses=warehouses,
                           central_wh=central_wh,
                           branch_users=branch_users)

@branches_bp.route('/branches/<int:id>/settings/save', methods=['POST'])
def branch_save_settings(id):
    """Saves branch brand color, general profile & custom invoice layout parameters."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Branch not found'}), 404
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    try:
        data = request.form if request.form else (request.get_json(silent=True) or {})

        name = data.get('name', branch['name']).strip()
        phone = data.get('phone', branch.get('phone') or '').strip()
        address = data.get('address', branch.get('address') or '').strip()
        manager_name = data.get('manager_name', branch.get('manager_name') or '').strip()
        so_prefix = data.get('so_prefix', branch.get('so_prefix') or '').strip().upper()
        color = data.get('primary_color', data.get('color', branch.get('color') or '#FF5A5F')).strip()
        loc_id = int(data.get('location_id')) if data.get('location_id') else branch.get('location_id')

        # Load existing stored settings of this branch directly so defaults don't overwrite branch's explicit choices
        raw_b = branch.get('settings_json') if isinstance(branch, dict) else None
        if isinstance(raw_b, str):
            try:
                cur_settings = json.loads(raw_b)
            except Exception:
                cur_settings = {}
        elif isinstance(raw_b, dict):
            cur_settings = dict(raw_b)
        else:
            cur_settings = {}

        # Handle Logo file upload / removal
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'invoice')
        os.makedirs(upload_dir, exist_ok=True)

        if data.get('remove_logo') == '1':
            cur_settings['logo_url'] = ''
        elif 'logo_file' in request.files:
            file = request.files['logo_file']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fname = f"branch_{id}_logo_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                cur_settings['logo_url'] = f"/static/uploads/invoice/{fname}"
        elif data.get('logo_url'):
            cur_settings['logo_url'] = data.get('logo_url').strip()

        # Handle QR file upload / removal
        if data.get('remove_qr') == '1':
            cur_settings['qr_code_url'] = ''
        elif 'qr_code_file' in request.files:
            file = request.files['qr_code_file']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fname = f"branch_{id}_qr_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                cur_settings['qr_code_url'] = f"/static/uploads/invoice/{fname}"
        elif data.get('qr_code_url'):
            cur_settings['qr_code_url'] = data.get('qr_code_url').strip()

        # Update customizable invoice & theme keys
        cur_settings['primary_color'] = color
        if 'secondary_color' in data:
            cur_settings['secondary_color'] = data.get('secondary_color').strip()
        if 'template_style' in data:
            cur_settings['template_style'] = data.get('template_style').strip()
        if 'font_family' in data:
            cur_settings['font_family'] = data.get('font_family').strip()
        if 'invoice_title_kh' in data:
            cur_settings['invoice_title_kh'] = data.get('invoice_title_kh').strip()
        if 'invoice_title_en' in data:
            cur_settings['invoice_title_en'] = data.get('invoice_title_en').strip()
        if 'shop_name_kh' in data:
            cur_settings['shop_name_kh'] = data.get('shop_name_kh').strip()
        if 'shop_name_en' in data:
            cur_settings['shop_name_en'] = data.get('shop_name_en').strip()
        if 'shop_address_kh' in data:
            cur_settings['shop_address_kh'] = data.get('shop_address_kh').strip()
        if 'shop_address_en' in data:
            cur_settings['shop_address_en'] = data.get('shop_address_en').strip()
        if 'phone' in data:
            cur_settings['phone'] = data.get('phone').strip()
        elif 'shop_phone' in data:
            cur_settings['phone'] = data.get('shop_phone').strip()
        if 'email' in data:
            cur_settings['email'] = data.get('email').strip()
        if 'website' in data:
            cur_settings['website'] = data.get('website').strip()
        if 'vat_tin' in data:
            cur_settings['vat_tin'] = data.get('vat_tin').strip()
        if 'bank_name' in data:
            cur_settings['bank_name'] = data.get('bank_name').strip()
        if 'account_name' in data:
            cur_settings['account_name'] = data.get('account_name').strip()
        if 'account_number' in data:
            cur_settings['account_number'] = data.get('account_number').strip()
        if 'payment_terms' in data:
            cur_settings['payment_terms'] = data.get('payment_terms').strip()
        if 'footer_notes_kh' in data:
            cur_settings['footer_notes_kh'] = data.get('footer_notes_kh').strip()
        if 'footer_notes_en' in data:
            cur_settings['footer_notes_en'] = data.get('footer_notes_en').strip()
        if 'paper_size' in data:
            cur_settings['paper_size'] = data.get('paper_size').strip()

        # Layout positioning & sizing
        if 'qr_size' in data:
            try:
                cur_settings['qr_size'] = int(data.get('qr_size'))
            except (ValueError, TypeError):
                pass
        if 'qr_position' in data:
            cur_settings['qr_position'] = data.get('qr_position').strip()
        if 'bank_info_size' in data:
            cur_settings['bank_info_size'] = str(data.get('bank_info_size')).strip()
        if 'bank_info_position' in data:
            cur_settings['bank_info_position'] = data.get('bank_info_position').strip()
        if 'qr_offset_x' in data:
            try:
                cur_settings['qr_offset_x'] = int(data.get('qr_offset_x'))
            except (ValueError, TypeError):
                pass
        if 'qr_offset_y' in data:
            try:
                cur_settings['qr_offset_y'] = int(data.get('qr_offset_y'))
            except (ValueError, TypeError):
                pass
        if 'bank_offset_x' in data:
            try:
                cur_settings['bank_offset_x'] = int(data.get('bank_offset_x'))
            except (ValueError, TypeError):
                pass
        if 'bank_offset_y' in data:
            try:
                cur_settings['bank_offset_y'] = int(data.get('bank_offset_y'))
            except (ValueError, TypeError):
                pass
        if 'unit_price_decimals' in data:
            try:
                cur_settings['unit_price_decimals'] = int(data.get('unit_price_decimals', 3) or 3)
            except (ValueError, TypeError):
                pass

        # Checkbox booleans (if form was submitted, presence indicates checked)
        if request.form:
            cur_settings['show_signature'] = bool(data.get('show_signature'))
            cur_settings['show_sku'] = bool(data.get('show_sku'))
            cur_settings['show_tax'] = bool(data.get('show_tax'))
            cur_settings['enable_khr_total'] = bool(data.get('enable_khr_total'))
        else:
            if 'show_signature' in data:
                cur_settings['show_signature'] = data['show_signature'] in ('1', 'true', 'on', True)
            if 'show_sku' in data:
                cur_settings['show_sku'] = data['show_sku'] in ('1', 'true', 'on', True)
            if 'show_tax' in data:
                cur_settings['show_tax'] = data['show_tax'] in ('1', 'true', 'on', True)
            if 'enable_khr_total' in data:
                cur_settings['enable_khr_total'] = data['enable_khr_total'] in ('1', 'true', 'on', True)

        if data.get('khr_exchange_rate'):
            try:
                cur_settings['khr_exchange_rate'] = float(data.get('khr_exchange_rate'))
            except (ValueError, TypeError):
                pass

        execute("""
            UPDATE branches
            SET name = %s, phone = %s, address = %s, manager_name = %s,
                so_prefix = %s, location_id = %s, color = %s,
                settings_json = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (name, phone, address, manager_name, so_prefix, loc_id, color, json.dumps(cur_settings), id))

        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Branch brand color & invoice settings saved successfully!'})

        tab = request.form.get('active_tab') or request.args.get('tab', 'invoice')
        flash(f"Settings for '{name}' updated successfully! Brand color: {color}", "success")
        return redirect(url_for('branches.branch_settings', id=id, tab=tab))

    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error saving settings: {e}", "error")
        return redirect(url_for('branches.branch_settings', id=id))

@branches_bp.route('/api/branches/<int:id>/settings/invoice/layout', methods=['POST'])
def branch_save_invoice_layout_api(id):
    """Auto-saves draggable/resizable invoice layout settings for this branch via AJAX."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        return jsonify({'success': False, 'message': 'Branch not found'}), 404

    try:
        data = request.get_json() or {}
        raw_b = branch.get('settings_json') if isinstance(branch, dict) else None
        if isinstance(raw_b, str):
            try:
                cur_settings = json.loads(raw_b)
            except Exception:
                cur_settings = {}
        elif isinstance(raw_b, dict):
            cur_settings = dict(raw_b)
        else:
            cur_settings = {}

        cur_settings['qr_size'] = int(data.get('qr_size', 180) or 180)
        cur_settings['qr_position'] = str(data.get('qr_position', 'left') or 'left').strip()
        cur_settings['bank_info_size'] = str(data.get('bank_info_size', '8.5') or '8.5').strip()
        cur_settings['bank_info_position'] = str(data.get('bank_info_position', 'below_qr') or 'below_qr').strip()
        cur_settings['qr_offset_x'] = int(data.get('qr_offset_x', 0) or 0)
        cur_settings['qr_offset_y'] = int(data.get('qr_offset_y', 0) or 0)
        cur_settings['bank_offset_x'] = int(data.get('bank_offset_x', 0) or 0)
        cur_settings['bank_offset_y'] = int(data.get('bank_offset_y', 0) or 0)

        execute("""
            UPDATE branches
            SET settings_json = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (json.dumps(cur_settings), id))

        return jsonify({'success': True, 'message': 'Branch invoice layout saved successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@branches_bp.route('/branches/<int:id>/settings/preview-invoice')
def branch_preview_invoice(id):
    """Renders a live invoice preview applying the branch's custom style, colors and details."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    settings = _get_branch_settings(branch)
    company = query_one("SELECT * FROM companies LIMIT 1")

    # Use the branch's most recent order or a realistic sample order
    order = query_one("""
        SELECT so.*, c.name as customer_name, c.phone as customer_phone,
               c.address1 as customer_address, l.name as location_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN locations l ON so.location_id = l.id
        WHERE so.branch_id = %s
        ORDER BY so.id DESC LIMIT 1
    """, (id,))

    if not order:
        order = {
            'id': 9999,
            'order_number': f"{branch.get('so_prefix', 'SO-TK-')}00088",
            'order_date': datetime.now().date(),
            'due_date': datetime.now().date(),
            'customer_name': 'Angkor Cafe & Bakery (អតិថិជនគំរូ)',
            'customer_contact': 'Mr. Sokha',
            'customer_phone': '012 888 999',
            'customer_email': 'info@angkor-cafe.com',
            'customer_address': '#168 St. 271, Toul Kork, Phnom Penh',
            'customer_tax_number': 'K001-99887766',
            'location_name': branch.get('name', 'STM Warehouse'),
            'status': 'INVOICED',
            'payment_status': 'PAID',
            'subtotal': 54.00,
            'discount_amount': 4.00,
            'total_amount': 50.00,
            'paid_amount': 50.00,
            'balance_due': 0.00,
            'notes': 'Thank you for your repeat packaging order!'
        }
        lines = [
            {'line_num': 1, 'product_name': 'Paper Bowl 500ML Kraft (ចានក្រដាស)', 'product_sku': 'PB-500K', 'product_barcode': '885012345001', 'product_uom': 'pack', 'quantity': 2, 'quantity_display': 2, 'unit_price': 15.00, 'subtotal': 30.00, 'line_description': 'Food grade leakproof with transparent PET lid'},
            {'line_num': 2, 'product_name': 'Aluminium Box 750ML Bento (ប្រអប់អាលុយមីញ៉ូម)', 'product_sku': 'AL-750B', 'product_barcode': '885012345002', 'product_uom': 'pack', 'quantity': 1, 'quantity_display': 1, 'unit_price': 16.00, 'subtotal': 16.00, 'line_description': 'Ovenable takeout container with paper lid'},
            {'line_num': 3, 'product_name': 'PLA Eco Straw 8mm (ទុយោធម្មជាតិ)', 'product_sku': 'STR-PLA8', 'product_barcode': '885012345003', 'product_uom': 'pack', 'quantity': 1, 'quantity_display': 1, 'unit_price': 8.00, 'subtotal': 8.00, 'line_description': '100% biodegradable individually wrapped'}
        ]
    else:
        lines = query_all("""
            SELECT sol.*, COALESCE(p.name, 'Item') as product_name, p.sku as product_sku,
                   p.barcode as product_barcode, COALESCE(sol.uom, p.uom, 'ea') as product_uom,
                   COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as line_description
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE sol.sales_order_id = %s
            ORDER BY sol.line_num ASC
        """, (order['id'],))

    rate = float(settings.get('khr_exchange_rate') or 4100.0)

    return render_template('sales/invoice_print.html',
                           order=order,
                           lines=lines,
                           company=company,
                           inv_settings=settings,
                           doc_type='invoice',
                           khr_rate=rate,
                           total_khr=float(order['total_amount']) * rate,
                           paid_khr=float(order['paid_amount']) * rate,
                           balance_khr=float(order['balance_due']) * rate,
                           subtotal_khr=float(order['subtotal']) * rate)

# --------------------------------------------------------------------
# EXPORT DATA TO CSV (inFlow Format Compatible)
# --------------------------------------------------------------------

@branches_bp.route('/branches/<int:id>/export/<export_type>')
def branch_export_csv(id, export_type):
    """Exports branch data to CSV compatible with inFlow Inventory."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    target_wh_id = branch.get('location_id') or 101
    output = io.StringIO()
    writer = csv.writer(output)
    date_str = datetime.now().strftime('%Y%m%d')

    if export_type in ('inventory', 'products'):
        # inFlow Standard Product & Stock Export
        writer.writerow(['Item Code', 'Item Name', 'Category', 'Barcode', 'Sales Price', 'Standard Cost', 'Quantity on Hand', 'UOM', 'Warehouse Location', 'Description'])
        rows = query_all("""
            SELECT p.sku, p.name, c.name as category_name, p.barcode,
                   p.default_price, p.standard_cost, COALESCE(i.quantity, 0) as stock_qty,
                   p.sales_uom, l.name as location_name, p.description
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN inventory i ON p.id = i.product_id AND i.location_id = %s
            LEFT JOIN locations l ON l.id = %s
            WHERE p.is_active = TRUE AND p.is_sellable = TRUE
            ORDER BY p.name ASC
        """, (target_wh_id, target_wh_id))
        for r in rows:
            writer.writerow([
                r['sku'] or '',
                r['name'] or '',
                r['category_name'] or 'Packaging',
                r['barcode'] or '',
                f"{float(r['default_price'] or 0):.2f}",
                f"{float(r['standard_cost'] or 0):.2f}",
                f"{float(r['stock_qty'] or 0):g}",
                r['sales_uom'] or 'pcs',
                r['location_name'] or 'STM Warehouse',
                r['description'] or ''
            ])
        filename = f"inFlow_{branch['code']}_Inventory_Stock_{date_str}.csv"

    elif export_type in ('sales', 'sales_orders', 'orders'):
        # inFlow Standard Sales Orders Export
        writer.writerow(['Order Number', 'Order Date', 'Customer Name', 'Customer Phone', 'Status', 'Payment Status', 'Subtotal', 'Discount', 'Total Amount', 'Paid Amount', 'Balance Due', 'Warehouse Location'])
        rows = query_all("""
            SELECT so.order_number, so.order_date, c.name as customer_name, c.contact_name as customer_contact,
                   COALESCE(NULLIF(TRIM(so.customer_phone), ''), NULLIF(TRIM(c.phone), ''), '') as customer_phone,
                   so.status, so.payment_status, so.subtotal, so.discount_amount, so.total_amount,
                   so.paid_amount, so.balance_due, l.name as location_name
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN locations l ON so.location_id = l.id
            WHERE so.branch_id = %s
            ORDER BY so.order_date DESC, so.id DESC
        """, (id,))
        for o in rows:
            c_phone = o['customer_phone'] or ''
            if not c_phone:
                _, _, c_phone = resolve_customer_phone_and_name(o['customer_name'], o.get('customer_contact', ''), '')
            writer.writerow([
                o['order_number'],
                str(o['order_date']),
                o['customer_name'] or 'Walk-in Customer',
                c_phone or '',
                o['status'],
                o['payment_status'] or 'PAID',
                f"{float(o['subtotal'] or 0):.2f}",
                f"{float(o['discount_amount'] or 0):.2f}",
                f"{float(o['total_amount'] or 0):.2f}",
                f"{float(o['paid_amount'] or 0):.2f}",
                f"{float(o['balance_due'] or 0):.2f}",
                o['location_name'] or 'STM Warehouse'
            ])
        filename = f"inFlow_{branch['code']}_SalesOrders_{date_str}.csv"

    elif export_type in ('customers', 'clients'):
        # inFlow Standard Customer Directory Export
        writer.writerow(['Customer Name', 'Contact Name', 'Phone', 'Email', 'Address', 'City', 'Balance', 'Payment Terms'])
        rows = query_all("""
            SELECT name, contact_name, phone, email, address1, city, balance, payment_terms, remarks
            FROM customers
            WHERE is_active = TRUE AND branch_id = %s
            ORDER BY name ASC
        """, (id,))
        for c in rows:
            c_name, c_contact, c_phone = resolve_customer_phone_and_name(
                c['name'], c['contact_name'], c['phone'], c['address1'], c.get('remarks', '')
            )
            writer.writerow([
                c_name or '',
                c_contact or '',
                c_phone or '',
                c['email'] or '',
                c['address1'] or '',
                c['city'] or 'Phnom Penh',
                f"{float(c['balance'] or 0):.2f}",
                c['payment_terms'] or 'Due on Receipt'
            ])
        filename = f"inFlow_{branch['code']}_Customers_{date_str}.csv"

    else:
        flash(f"Unknown export type '{export_type}'.", "error")
        return redirect(url_for('branches.branch_settings', id=id))

    csv_bytes = output.getvalue().encode('utf-8-sig')
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype='text/csv; charset=utf-8',
        as_attachment=True,
        download_name=filename
    )

# --------------------------------------------------------------------
# IMPORT DATA FROM CSV (inFlow Format Compatible)
# --------------------------------------------------------------------

@branches_bp.route('/branches/<int:id>/import/<import_type>', methods=['POST'])
def branch_import_csv(id, import_type):
    """Imports products/stock or customers from an inFlow format CSV file."""
    branch = query_one("SELECT * FROM branches WHERE id = %s", (id,))
    if not branch:
        flash("Branch not found.", "error")
        return redirect(url_for('branches.list_branches'))

    target_wh_id = branch.get('location_id') or 101

    file = request.files.get('file')
    if not file or not file.filename:
        flash("Please choose a valid CSV file to upload.", "error")
        return redirect(url_for('branches.branch_settings', id=id))

    mode = request.form.get('import_mode', 'set') # 'set' (replace) or 'add' (increment)

    try:
        raw_bytes = file.read()
        # Decode CSV handling utf-8-sig, utf-8, and fallback cp1252
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                text = raw_bytes.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = raw_bytes.decode('utf-8', errors='ignore')

        # Detect delimiter
        first_line = text.split('\n')[0] if text else ''
        delim = '\t' if '\t' in first_line and ',' not in first_line else (';' if ';' in first_line and ',' not in first_line else ',')

        reader = csv.reader(io.StringIO(text), delimiter=delim)
        header_row = next(reader, None)
        if not header_row:
            flash("Uploaded CSV file is empty.", "error")
            return redirect(url_for('branches.branch_settings', id=id))

        # Normalize column mappings
        header_map = {}
        for idx, col in enumerate(header_row):
            clean = col.strip().lower().replace('_', ' ').replace('-', ' ')
            if clean in ('item code', 'sku', 'code', 'product code', 'barcode item code'):
                header_map['sku'] = idx
            elif clean in ('item name', 'name', 'product name', 'title', 'item description'):
                header_map['name'] = idx
            elif clean in ('category', 'category name', 'type'):
                header_map['category'] = idx
            elif clean in ('barcode', 'upc', 'ean'):
                header_map['barcode'] = idx
            elif clean in ('sales price', 'price', 'default price', 'unit price'):
                header_map['price'] = idx
            elif clean in ('standard cost', 'cost', 'cost price'):
                header_map['cost'] = idx
            elif clean in ('quantity on hand', 'stock', 'quantity', 'qty', 'count', 'on hand'):
                header_map['quantity'] = idx
            elif clean in ('uom', 'unit', 'unit of measure'):
                header_map['uom'] = idx
            elif clean in ('description', 'remarks', 'notes'):
                header_map['description'] = idx
            # Customer fields
            elif clean in ('customer name', 'customer', 'company'):
                header_map['cust_name'] = idx
            elif clean in ('contact name', 'contact person', 'contact'):
                header_map['cust_contact'] = idx
            elif clean in ('phone', 'mobile', 'tel'):
                header_map['cust_phone'] = idx
            elif clean in ('email', 'e mail'):
                header_map['cust_email'] = idx
            elif clean in ('address', 'street', 'location'):
                header_map['cust_address'] = idx
            elif clean in ('city', 'province'):
                header_map['cust_city'] = idx

        processed = 0
        updated = 0
        created = 0

        with get_db_cursor(commit=True) as cur:
            if import_type in ('inventory', 'products'):
                for row in reader:
                    if not row or not any(row):
                        continue

                    sku = row[header_map['sku']].strip() if 'sku' in header_map and len(row) > header_map['sku'] else ''
                    name = row[header_map['name']].strip() if 'name' in header_map and len(row) > header_map['name'] else ''
                    if not name and not sku:
                        continue

                    cat_name = row[header_map['category']].strip() if 'category' in header_map and len(row) > header_map['category'] else 'General'
                    barcode = row[header_map['barcode']].strip() if 'barcode' in header_map and len(row) > header_map['barcode'] else None
                    uom = row[header_map['uom']].strip() if 'uom' in header_map and len(row) > header_map['uom'] else 'pcs'
                    desc = row[header_map['description']].strip() if 'description' in header_map and len(row) > header_map['description'] else None

                    price_val = 0.0
                    if 'price' in header_map and len(row) > header_map['price']:
                        try:
                            clean_pr = re.sub(r'[^\d.]', '', row[header_map['price']])
                            price_val = float(clean_pr) if clean_pr else 0.0
                        except Exception:
                            price_val = 0.0

                    qty_val = None
                    if 'quantity' in header_map and len(row) > header_map['quantity']:
                        try:
                            clean_q = re.sub(r'[^\d.]', '', row[header_map['quantity']])
                            qty_val = float(clean_q) if clean_q else 0.0
                        except Exception:
                            qty_val = None

                    # Category Lookup / Insert
                    cat_id = None
                    if cat_name:
                        cur.execute("SELECT id FROM categories WHERE UPPER(name) = UPPER(%s)", (cat_name,))
                        cat_row = cur.fetchone()
                        if cat_row:
                            cat_id = cat_row['id']
                        else:
                            cur.execute("INSERT INTO categories (name, is_active) VALUES (%s, TRUE) RETURNING id", (cat_name,))
                            cat_id = cur.fetchone()['id']

                    # Product Lookup
                    p_row = None
                    if sku:
                        cur.execute("SELECT id FROM products WHERE UPPER(sku) = UPPER(%s)", (sku,))
                        p_row = cur.fetchone()
                    if not p_row and name:
                        cur.execute("SELECT id FROM products WHERE UPPER(name) = UPPER(%s)", (name,))
                        p_row = cur.fetchone()

                    if p_row:
                        pid = p_row['id']
                        cur.execute("""
                            UPDATE products
                            SET name = COALESCE(NULLIF(%s, ''), name),
                                category_id = COALESCE(%s, category_id),
                                barcode = COALESCE(NULLIF(%s, ''), barcode),
                                default_price = CASE WHEN %s > 0 THEN %s ELSE default_price END,
                                sales_uom = COALESCE(NULLIF(%s, ''), sales_uom),
                                description = COALESCE(NULLIF(%s, ''), description),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (name, cat_id, barcode, price_val, price_val, uom, desc, pid))
                        updated += 1
                    else:
                        p_sku = sku or f"SKU-{int(datetime.now().timestamp())}-{created+1}"
                        p_name = name or p_sku
                        cur.execute("""
                            INSERT INTO products (sku, name, category_id, barcode, default_price, sales_uom, description, is_active, is_sellable)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, TRUE)
                            RETURNING id
                        """, (p_sku, p_name, cat_id, barcode, price_val, uom, desc))
                        pid = cur.fetchone()['id']
                        created += 1

                    # Update Inventory Stock for target branch warehouse
                    if qty_val is not None:
                        cur.execute("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s FOR UPDATE", (pid, target_wh_id))
                        inv_row = cur.fetchone()
                        old_qty = float(inv_row['quantity']) if inv_row else 0.0
                        new_qty = qty_val if mode == 'set' else (old_qty + qty_val)

                        if inv_row:
                            cur.execute("UPDATE inventory SET quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE product_id = %s AND location_id = %s", (new_qty, pid, target_wh_id))
                        else:
                            cur.execute("INSERT INTO inventory (product_id, location_id, quantity) VALUES (%s, %s, %s)", (pid, target_wh_id, new_qty))

                        # Log stock adjustment in inventory_logs
                        cur.execute("""
                            INSERT INTO inventory_logs (
                                product_id, movement_type, reference_type, reference_id,
                                to_location_id, quantity, qty_before, qty_after, branch_id, reason
                            ) VALUES (%s, 'CSV_IMPORT', 'IMPORT', %s, %s, %s, %s, %s, %s, %s)
                        """, (pid, file.filename[:50], target_wh_id, abs(new_qty - old_qty), old_qty, new_qty, id, f"CSV Import into Branch {branch['name']}"))

                    processed += 1

                flash(f"✅ inFlow CSV Import Complete! Processed {processed} products ({updated} updated, {created} created). Stock synchronized for Warehouse ID {target_wh_id}.", "success")

            elif import_type in ('customers', 'clients'):
                for row in reader:
                    if not row or not any(row):
                        continue
                    cust_name = row[header_map['cust_name']].strip() if 'cust_name' in header_map and len(row) > header_map['cust_name'] else ''
                    if not cust_name:
                        continue
                    contact = row[header_map['cust_contact']].strip() if 'cust_contact' in header_map and len(row) > header_map['cust_contact'] else ''
                    phone = row[header_map['cust_phone']].strip() if 'cust_phone' in header_map and len(row) > header_map['cust_phone'] else ''
                    email = row[header_map['cust_email']].strip() if 'cust_email' in header_map and len(row) > header_map['cust_email'] else ''
                    address = row[header_map['cust_address']].strip() if 'cust_address' in header_map and len(row) > header_map['cust_address'] else ''
                    city = row[header_map['cust_city']].strip() if 'cust_city' in header_map and len(row) > header_map['cust_city'] else 'Phnom Penh'

                    cur.execute("SELECT id FROM customers WHERE UPPER(name) = UPPER(%s) AND branch_id = %s", (cust_name, id))
                    exist_cust = cur.fetchone()
                    if exist_cust:
                        cur.execute("""
                            UPDATE customers
                            SET contact_name = COALESCE(NULLIF(%s, ''), contact_name),
                                phone = COALESCE(NULLIF(%s, ''), phone),
                                email = COALESCE(NULLIF(%s, ''), email),
                                address1 = COALESCE(NULLIF(%s, ''), address1),
                                city = COALESCE(NULLIF(%s, ''), city),
                                branch_id = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (contact, phone, email, address, city, id, exist_cust['id']))
                        updated += 1
                    else:
                        cur.execute("""
                            INSERT INTO customers (name, contact_name, phone, email, address1, city, branch_id, is_active)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                        """, (cust_name, contact, phone, email, address, city, id))
                        created += 1
                    processed += 1

                flash(f"✅ Customer CSV Import Complete! Processed {processed} customer records ({updated} updated, {created} added).", "success")

            else:
                flash(f"Unsupported import type '{import_type}'.", "error")

    except Exception as e:
        flash(f"CSV import error: {str(e)}", "error")

    return redirect(url_for('branches.branch_settings', id=id))

# --------------------------------------------------------------------
# DOWNLOAD CSV TEMPLATES (inFlow Format Compatible)
# --------------------------------------------------------------------

@branches_bp.route('/branches/<int:id>/template/<template_type>')
def branch_csv_template(id, template_type):
    """Downloads ready-to-fill inFlow sample CSV templates for products or customers."""
    output = io.StringIO()
    writer = csv.writer(output)

    if template_type in ('inventory', 'products'):
        writer.writerow(['Item Code', 'Item Name', 'Category', 'Barcode', 'Sales Price', 'Standard Cost', 'Quantity on Hand', 'UOM', 'Description'])
        writer.writerow(['PB-500K', 'Paper Bowl 500ML (Kraft)', 'Bowl', '885012345001', '15.00', '10.50', '250', 'pack', 'Food grade leakproof kraft bowl'])
        writer.writerow(['AL-750B', 'Aluminium Box 750ML Bento', 'Aluminium Box', '885012345002', '18.00', '12.00', '180', 'pack', 'Bento style ovenable takeout container'])
        writer.writerow(['CUP-90P', 'Plastic Cup 90mm PP Clear', 'Cup', '885012345003', '8.50', '5.20', '500', 'pack', 'Clear 16oz drinking cups'])
        filename = "inFlow_Branch_Products_Template.csv"
    else:
        writer.writerow(['Customer Name', 'Contact Name', 'Phone', 'Email', 'Address', 'City', 'Payment Terms'])
        writer.writerow(['Angkor Cafe & Bakery', 'Mr. Sokha', '012 345 678', 'sokha@angkor-cafe.com', '#168 St. 271, Toul Kork', 'Phnom Penh', 'Due on Receipt'])
        writer.writerow(['Phnom Penh Street Food', 'Ms. Davy', '098 765 432', 'davy@ppstreetfood.com', '#45 St. 51, BKK1', 'Phnom Penh', 'Due on Receipt'])
        filename = "inFlow_Branch_Customers_Template.csv"

    csv_bytes = output.getvalue().encode('utf-8-sig')
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype='text/csv; charset=utf-8',
        as_attachment=True,
        download_name=filename
    )
