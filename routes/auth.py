import json
import logging
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import query_one, query_all, execute, execute_returning_id

logger = logging.getLogger('inflow.auth')

auth_bp = Blueprint('auth', __name__)

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    try:
        user = query_one("""
            SELECT u.*, b.name as branch_name, b.code as branch_code, b.color as branch_color
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            WHERE u.id = %s AND u.is_active = TRUE
        """, (user_id,))
        return user
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please sign in to access this page. / សូមចូលប្រើប្រាស់គណនី", "warning")
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def main_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'main_admin':
            flash("🔒 Access Denied: Only Main Store HQ Admin can access this resource. / សិទ្ធិត្រូវបានកំណត់៖ មានតែ Main Store Admin ទើបអាចចូលបាន។", "error")
            user_bid = session.get('branch_id')
            if user_bid:
                return redirect(url_for('branches.branch_workspace', id=user_bid))
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def check_permission(perm_name, default=False):
    """
    Evaluates whether the current user in session has permission 'perm_name'.
    - 'main_admin': always True (full HQ control)
    - Others: checks users.permissions_json AND branches.permissions_json.
    """
    role = session.get('role')
    if role == 'main_admin':
        return True
    
    user_perms = session.get('permissions')
    if isinstance(user_perms, str):
        try:
            user_perms = json.loads(user_perms)
        except Exception:
            user_perms = {}
    elif not isinstance(user_perms, dict):
        user_perms = {}

    # If the user's explicit permission is False, deny immediately!
    if perm_name in user_perms and not bool(user_perms[perm_name]):
        return False

    # Check active branch permission if applicable
    bid = session.get('active_branch_id') or session.get('branch_id')
    if bid and str(bid).isdigit():
        try:
            b_row = query_one("SELECT permissions_json FROM branches WHERE id = %s", (int(bid),))
            if b_row and b_row.get('permissions_json'):
                bp = b_row['permissions_json']
                if isinstance(bp, str):
                    bp = json.loads(bp)
                if isinstance(bp, dict) and perm_name in bp and not bool(bp[perm_name]):
                    return False
        except Exception:
            pass

    return bool(user_perms.get(perm_name, default))

def user_can_edit_prices():
    """Returns True if the current user is allowed to edit selling prices, else False."""
    return check_permission('edit_prices', default=False)

def user_can_view_costs():
    """Returns True if the current user is allowed to view cost prices, else False."""
    return check_permission('view_costs', default=False)

def user_can_adjust_stock():
    """Returns True if the current user is allowed to adjust stock, else False."""
    return check_permission('adjustments', default=True)

# -------------------------------------------------------------
# LOGIN & LOGOUT
# -------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        next_url = request.form.get('next') or request.args.get('next')

        if not username or not password:
            flash("Please provide both username and password. / សូមបញ្ចូលឈ្មោះគណនី និងលេខសំងាត់", "error")
            return render_template('auth/login.html', next=next_url, username=username)

        user = query_one("""
            SELECT u.*, b.code as branch_code, b.name as branch_name
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            WHERE LOWER(u.username) = %s
        """, (username,))

        if not user:
            flash("Invalid username or password. / ឈ្មោះគណនី ឬលេខសំងាត់មិនត្រឹមត្រូវទេ", "error")
            return render_template('auth/login.html', next=next_url, username=username)

        if not user.get('is_active', True):
            flash("This user account has been disabled. Please contact Main Store HQ. / គណនីនេះត្រូវបានផ្អាក សូមទាក់ទងរដ្ឋបាលកណ្តាល", "error")
            return render_template('auth/login.html', next=next_url, username=username)

        # Verify password (with fallback to plaintext comparison for legacy/dev seeds if needed)
        pwd_match = False
        try:
            pwd_match = check_password_hash(user['password_hash'], password)
        except Exception:
            pwd_match = (user['password_hash'] == password)

        if not pwd_match:
            flash("Invalid username or password. / ឈ្មោះគណនី ឬលេខសំងាត់មិនត្រឹមត្រូវទេ", "error")
            return render_template('auth/login.html', next=next_url, username=username)

        # Update last login timestamp
        try:
            execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
        except Exception:
            pass

        # Populate permanent session (never auto logout)
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['display_name'] = user['display_name']
        session['role'] = user['role']
        session['branch_id'] = user['branch_id']
        
        # Load user permissions
        perms = user.get('permissions_json')
        if isinstance(perms, str):
            try:
                perms = json.loads(perms)
            except Exception:
                perms = {}
        session['permissions'] = perms or {}

        flash(f"Welcome back, {user['display_name']}! / សូមស្វាគមន៍ការចូលប្រើប្រាស់!", "success")

        # Routing based on Role
        if user['role'] == 'branch_admin' or user['role'] == 'branch_cashier':
            user_bid = user['branch_id'] or 1
            session['active_branch_id'] = user_bid
            if next_url and f'/branches/{user_bid}' in next_url:
                return redirect(next_url)
            return redirect(url_for('branches.branch_workspace', id=user_bid))
        else:
            # Main Store Admin
            if next_url and not next_url.startswith('/login'):
                return redirect(next_url)
            return redirect(url_for('dashboard.index'))

    # GET method: Render login form
    next_url = request.args.get('next', '')
    branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")
    return render_template('auth/login.html', next=next_url, branches=branches)

@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('display_name', None)
    session.pop('role', None)
    session.pop('branch_id', None)
    session.pop('permissions', None)
    session.pop('active_branch_id', None)
    flash("You have been signed out safely. / អ្នកបានចាកចេញពីប្រព័ន្ធដោយសុវត្ថិភាព", "success")
    return redirect(url_for('auth.login'))

@auth_bp.route('/quick-login/<role_or_user>')
def quick_login(role_or_user):
    """
    Convenience quick-login endpoint for fast demonstration and testing.
    """
    if role_or_user == 'admin' or role_or_user == 'main':
        user = query_one("SELECT * FROM users WHERE username = 'admin' LIMIT 1")
    elif role_or_user == 'toulkork' or role_or_user == 'branch1':
        user = query_one("SELECT * FROM users WHERE username = 'toulkork' LIMIT 1")
    elif role_or_user.startswith('branch_'):
        try:
            bid = int(role_or_user.split('_')[1])
            user = query_one("SELECT * FROM users WHERE branch_id = %s LIMIT 1", (bid,))
        except Exception:
            user = None
    else:
        user = query_one("SELECT * FROM users WHERE username = %s LIMIT 1", (role_or_user,))

    if not user:
        flash("Target user account not found. / រកមិនឃើញគណនីនេះទេ", "error")
        return redirect(url_for('auth.login'))

    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['display_name'] = user['display_name']
    session['role'] = user['role']
    session['branch_id'] = user['branch_id']
    
    perms = user.get('permissions_json')
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except Exception:
            perms = {}
    session['permissions'] = perms or {}

    flash(f"Switched session to {user['display_name']} ({user['role']})", "success")

    if user['role'] == 'branch_admin' or user['role'] == 'branch_cashier':
        bid = user['branch_id'] or 1
        session['active_branch_id'] = bid
        return redirect(url_for('branches.branch_workspace', id=bid))
    else:
        return redirect(url_for('dashboard.index'))

# -------------------------------------------------------------
# USER MANAGEMENT (MAIN STORE SETTINGS & BRANCH SETTINGS)
# -------------------------------------------------------------

@auth_bp.route('/api/users')
def list_users_api():
    current_role = session.get('role')
    user_branch_id = session.get('branch_id')

    if current_role == 'main_admin':
        users = query_all("""
            SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.branch_id,
                   u.is_active, u.last_login, u.created_at, u.permissions_json,
                   b.name as branch_name, b.code as branch_code, b.color as branch_color
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            ORDER BY u.id ASC
        """)
    else:
        # Branch admin only sees their branch users
        users = query_all("""
            SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.branch_id,
                   u.is_active, u.last_login, u.created_at, u.permissions_json,
                   b.name as branch_name, b.code as branch_code, b.color as branch_color
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            WHERE u.branch_id = %s
            ORDER BY u.id ASC
        """, (user_branch_id,))
    return jsonify({'success': True, 'users': users})

@auth_bp.route('/api/users/<int:user_id>')
def get_user_api(user_id):
    current_role = session.get('role')
    user_branch_id = session.get('branch_id')

    user = query_one("""
        SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.branch_id,
               u.is_active, u.last_login, u.created_at, u.permissions_json,
               b.name as branch_name, b.code as branch_code
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.id
        WHERE u.id = %s
    """, (user_id,))
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    # Security check: branch_admin cannot view users of other branches or main admin
    if current_role != 'main_admin' and user['branch_id'] != user_branch_id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    return jsonify({'success': True, 'user': user})

@auth_bp.route('/settings/users/save', methods=['POST'])
def save_user():
    """
    Create or update system user from Main Store Settings or Branch Settings.
    """
    current_role = session.get('role', 'main_admin')
    user_branch_id = session.get('branch_id')

    user_id = request.form.get('user_id')
    username = request.form.get('username', '').strip().lower()
    display_name = request.form.get('display_name', '').strip()
    password = request.form.get('password', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    requested_role = request.form.get('role', 'branch_admin').strip()
    branch_id_val = request.form.get('branch_id')
    is_active = request.form.get('is_active') == 'true' or request.form.get('is_active') == '1' or request.form.get('is_active') == 'on'

    source_page = request.form.get('source_page', 'main_settings')

    # Security rule: If current user is Branch Admin, enforce branch isolation
    if current_role != 'main_admin':
        # Cannot assign main_admin role
        requested_role = 'branch_admin' if requested_role == 'branch_admin' else 'branch_cashier'
        # Must lock to their own branch
        target_branch_id = user_branch_id
    else:
        if requested_role == 'main_admin':
            target_branch_id = None
        else:
            try:
                target_branch_id = int(branch_id_val) if branch_id_val else None
            except (ValueError, TypeError):
                target_branch_id = None

    if not username or not display_name:
        flash("Username and Display Name are required. / សូមបញ្ចូលឈ្មោះគណនី និងឈ្មោះបង្ហាញ", "error")
        if source_page == 'branch_settings' and target_branch_id:
            return redirect(url_for('branches.branch_settings', id=target_branch_id, tab='users'))
        return redirect(url_for('settings.general_settings', tab='tabUsers'))

    # Build permissions JSON
    perms = {
        'dashboard': request.form.get('perm_dashboard') in ('1', 'true', 'on'),
        'pos': request.form.get('perm_pos') in ('1', 'true', 'on'),
        'sales_orders': request.form.get('perm_sales_orders') in ('1', 'true', 'on'),
        'invoices': request.form.get('perm_invoices') in ('1', 'true', 'on'),
        'inventory': request.form.get('perm_inventory') in ('1', 'true', 'on'),
        'transfers': request.form.get('perm_transfers') in ('1', 'true', 'on'),
        'adjustments': request.form.get('perm_adjustments') in ('1', 'true', 'on'),
        'purchasing': request.form.get('perm_purchasing') in ('1', 'true', 'on'),
        'expenses': request.form.get('perm_expenses') in ('1', 'true', 'on'),
        'customers': request.form.get('perm_customers') in ('1', 'true', 'on'),
        'reports': request.form.get('perm_reports') in ('1', 'true', 'on'),
        'edit_prices': request.form.get('perm_edit_prices') in ('1', 'true', 'on'),
        'view_costs': request.form.get('perm_view_costs') in ('1', 'true', 'on'),
        'manage_settings': request.form.get('perm_manage_settings') in ('1', 'true', 'on')
    }

    # If role is main_admin, all perms default to True
    if requested_role == 'main_admin':
        perms = {k: True for k in perms}

    perms_json_str = json.dumps(perms)

    if user_id and str(user_id).isdigit():
        uid = int(user_id)
        existing = query_one("SELECT * FROM users WHERE id = %s", (uid,))
        if not existing:
            flash("User not found / រកមិនឃើញគណនីនេះទេ", "error")
            return redirect(url_for('settings.general_settings', tab='tabUsers'))

        # Branch admin cannot edit users of other branches or main admins
        if current_role != 'main_admin' and existing.get('branch_id') != user_branch_id:
            flash("Permission denied / គ្មានសិទ្ធិកែប្រែគណនីនេះទេ", "error")
            return redirect(url_for('branches.branch_settings', id=user_branch_id, tab='users'))

        # Check username uniqueness if changed
        if existing['username'].lower() != username.lower():
            dup = query_one("SELECT id FROM users WHERE LOWER(username) = %s AND id != %s", (username.lower(), uid))
            if dup:
                flash(f"Username '{username}' is already taken. / ឈ្មោះគណនី '{username}' មានគេប្រើរួចហើយ", "error")
                if source_page == 'branch_settings':
                    return redirect(url_for('branches.branch_settings', id=target_branch_id or user_branch_id, tab='users'))
                return redirect(url_for('settings.general_settings', tab='tabUsers'))

        if password:
            hashed_pwd = generate_password_hash(password)
            execute("""
                UPDATE users SET
                    username = %s,
                    password_hash = %s,
                    display_name = %s,
                    email = %s,
                    phone = %s,
                    role = %s,
                    branch_id = %s,
                    permissions_json = %s,
                    is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (username, hashed_pwd, display_name, email, phone, requested_role, target_branch_id, perms_json_str, is_active, uid))
        else:
            execute("""
                UPDATE users SET
                    username = %s,
                    display_name = %s,
                    email = %s,
                    phone = %s,
                    role = %s,
                    branch_id = %s,
                    permissions_json = %s,
                    is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (username, display_name, email, phone, requested_role, target_branch_id, perms_json_str, is_active, uid))
        
        flash(f"User '{display_name}' ({username}) updated successfully! / បានកែប្រែគណនីដោយជោគជ័យ!", "success")
    else:
        # Create new user
        if not password:
            password = '123' # Default initial password if left blank

        dup = query_one("SELECT id FROM users WHERE LOWER(username) = %s", (username.lower(),))
        if dup:
            flash(f"Username '{username}' already exists. Please pick another. / ឈ្មោះគណនី '{username}' មានរួចហើយ", "error")
            if source_page == 'branch_settings':
                return redirect(url_for('branches.branch_settings', id=target_branch_id or user_branch_id, tab='users'))
            return redirect(url_for('settings.general_settings', tab='tabUsers'))

        hashed_pwd = generate_password_hash(password)
        execute("""
            INSERT INTO users (
                username, password_hash, display_name, email, phone,
                role, branch_id, permissions_json, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (username, hashed_pwd, display_name, email, phone, requested_role, target_branch_id, perms_json_str, is_active))

        flash(f"New user '{display_name}' created successfully! / បានបង្កើតគណនីថ្មីដោយជោគជ័យ!", "success")

    if source_page == 'branch_settings' and target_branch_id:
        return redirect(url_for('branches.branch_settings', id=target_branch_id, tab='users'))
    return redirect(url_for('settings.general_settings', tab='tabUsers'))

@auth_bp.route('/settings/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    current_role = session.get('role', 'main_admin')
    user_branch_id = session.get('branch_id')
    current_user_id = session.get('user_id')

    source_page = request.form.get('source_page', 'main_settings')
    redirect_branch_id = request.form.get('branch_id', user_branch_id)

    if current_user_id == user_id:
        flash("You cannot delete your own logged-in account. / មិនអាចលុបគណនីកំពុងប្រើប្រាស់បានទេ", "error")
        if source_page == 'branch_settings':
            return redirect(url_for('branches.branch_settings', id=redirect_branch_id, tab='users'))
        return redirect(url_for('settings.general_settings', tab='tabUsers'))

    target_user = query_one("SELECT * FROM users WHERE id = %s", (user_id,))
    if not target_user:
        flash("User not found / រកមិនឃើញគណនីនេះទេ", "error")
        if source_page == 'branch_settings':
            return redirect(url_for('branches.branch_settings', id=redirect_branch_id, tab='users'))
        return redirect(url_for('settings.general_settings', tab='tabUsers'))

    if current_role != 'main_admin' and target_user.get('branch_id') != user_branch_id:
        flash("Permission denied / គ្មានសិទ្ធិលុបគណនីនេះទេ", "error")
        return redirect(url_for('branches.branch_settings', id=user_branch_id, tab='users'))

    execute("DELETE FROM users WHERE id = %s", (user_id,))
    flash(f"User '{target_user['display_name']}' has been deleted. / បានលុបគណនីដោយជោគជ័យ", "success")

    if source_page == 'branch_settings' and redirect_branch_id:
        return redirect(url_for('branches.branch_settings', id=redirect_branch_id, tab='users'))
    return redirect(url_for('settings.general_settings', tab='tabUsers'))
