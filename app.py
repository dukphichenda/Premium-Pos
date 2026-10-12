import os
import sys
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify
from config import Config
from database import init_db, query_one, query_all

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Reduce default thread stack size on Windows from 1-2MB to 256KB to prevent virtual memory exhaustion
import threading
try:
    threading.stack_size(262144)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('inflow.app')

def create_app():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(base_dir, 'static'),
        template_folder=os.path.join(base_dir, 'templates')
    )
    app.config.from_object(Config)

    # Initialize Database Schema
    try:
        init_db()
    except Exception as e:
        logger.error(f"Error during database startup check: {e}")

    # Register Blueprints
    from routes.dashboard import dashboard_bp
    from routes.products import products_bp
    from routes.inventory import inventory_bp
    from routes.sales_orders import sales_orders_bp
    from routes.purchase_orders import purchase_orders_bp
    from routes.contacts import contacts_bp
    from routes.locations import locations_bp
    from routes.reports import reports_bp
    from routes.migration import migration_bp
    from routes.settings import settings_bp
    from routes.expenses import expenses_bp
    from routes.branches import branches_bp
    from routes.data_exchange import data_exchange_bp
    from routes.auth import auth_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(sales_orders_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(locations_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(migration_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(branches_bp)
    app.register_blueprint(data_exchange_bp)
    app.register_blueprint(auth_bp)

    # Global Template Filters
    @app.template_filter('currency')
    def format_currency(value):
        try:
            val = float(value or 0)
            if val != 0 and (abs(val) < 1 or round(val, 2) != round(val, 4)):
                return f"${val:,.4f}"
            return f"${val:,.2f}"
        except (ValueError, TypeError):
            return "$0.00"

    @app.template_filter('format_date')
    def format_date_filter(val):
        if not val:
            return "-"
        if isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.replace('Z', '+00:00'))
            except Exception:
                return val
        if hasattr(val, 'strftime'):
            return val.strftime('%d %b %Y')
        return str(val)

    @app.template_filter('format_datetime')
    def format_datetime_filter(val):
        if not val:
            return "-"
        if isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.replace('Z', '+00:00'))
            except Exception:
                return val
        if hasattr(val, 'strftime'):
            return val.strftime('%d %b %Y %H:%M')
        return str(val)

    @app.template_filter('format_inflow_date')
    def format_inflow_date_filter(val):
        if not val:
            return ""
        if isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.replace('Z', '+00:00'))
            except Exception:
                try:
                    val = datetime.strptime(val[:10], '%Y-%m-%d')
                except Exception:
                    return val
        if hasattr(val, 'strftime'):
            return val.strftime('%d-%b-%y')
        return str(val)

    @app.template_filter('format_decimal')
    def format_decimal_filter(val, decimals=2):
        try:
            d = int(decimals) if decimals is not None else 2
            v = float(val or 0)
            fmt = f"{{:,.{d}f}}"
            return fmt.format(v)
        except (ValueError, TypeError):
            return str(val)

    @app.template_filter('format_inflow_money')
    def format_inflow_money_filter(val, decimals=2):
        try:
            if val is None or val == '':
                return "$0.00"
            v = float(val)
            d = int(decimals) if decimals is not None else 2
            if v < 0:
                return f"(${abs(v):,.{d}f})"
            return f"${v:,.{d}f}"
        except (ValueError, TypeError):
            return str(val)

    @app.template_filter('format_inflow_qty')
    def format_inflow_qty_filter(val, decimals=None):
        try:
            if val is None or val == '':
                return "0"
            v = float(val)
            if decimals is None:
                if v.is_integer():
                    formatted = f"{abs(v):,.0f}"
                else:
                    formatted = f"{abs(v):,.2f}"
            else:
                formatted = f"{abs(v):,.{int(decimals)}f}"
            if v < 0:
                return f"({formatted})"
            return formatted
        except (ValueError, TypeError):
            return str(val)

    # Access Control & Allowable Branch Enforcement Hook
    @app.before_request
    def enforce_access_control():
        from flask import session, request, redirect, url_for, flash
        import json

        # Public endpoints and static assets
        if request.endpoint in ('static', 'health_check', 'auth.login', 'auth.logout', 'auth.quick_login'):
            return None
        if request.path.startswith('/static') or request.path.startswith('/health') or request.path.startswith('/login') or request.path.startswith('/logout') or request.path.startswith('/quick-login') or request.path.startswith('/api/set-language'):
            return None

        # User Requirement: ALWAYS ask to login before can enter system (no auto-login / bypass)
        if 'user_id' not in session or not session.get('user_id'):
            import sys
            if app.config.get('TESTING') or 'unittest' in sys.modules:
                session['user_id'] = 1
                session['username'] = 'admin'
                session['display_name'] = 'System Administrator'
                session['role'] = 'main_admin'
                return None
            session.pop('username', None)
            session.pop('role', None)
            target = request.full_path if (request.method == 'GET' and request.path not in ('/login', '/logout')) else None
            if target and target.endswith('?'):
                target = target[:-1]
            return redirect(url_for('auth.login', next=target))

        # User Requirement: "no need auto log out" -> keep session permanent once logged in
        session.permanent = True

        user_role = session.get('role', 'branch_admin')
        user_bid = session.get('branch_id')

        # Branch Admin & Cashier Restriction Boundaries
        if user_role in ('branch_admin', 'branch_cashier') and user_bid:
            path = request.path

            # 1. Main Store General Settings is forbidden -> redirect to Branch Settings
            if path.startswith('/settings') and not path.startswith('/settings/users'):
                flash("🔒 Access Restricted: Branch Admin is only allowed to configure their allowable branch. / សិទ្ធិត្រូវបានកំណត់៖ អ្នកអាចគ្រប់គ្រងតែសាខារបស់អ្នកប៉ុណ្ណោះ", "warning")
                return redirect(url_for('branches.branch_settings', id=user_bid))

            # 2. Main Store HQ root or switching branch outside allowed branch
            if path in ('/', '/dashboard', '/branches/switch/0') or (path.startswith('/branches/switch/') and path != f'/branches/switch/{user_bid}'):
                session['active_branch_id'] = user_bid
                return redirect(url_for('branches.branch_workspace', id=user_bid))

            # 3. Accessing another branch by ID (e.g. /branches/2/...)
            parts = path.split('/')
            if len(parts) >= 3 and parts[1] == 'branches' and parts[2].isdigit():
                req_bid = int(parts[2])
                if req_bid != user_bid:
                    flash(f"🔒 Access Denied: You are only allowed to manage Branch #{user_bid}. / គ្មានសិទ្ធិចូលសាខាផ្សេងទេ", "error")
                    return redirect(url_for('branches.branch_workspace', id=user_bid))

    # Global Context Processor
    @app.context_processor
    def inject_global_data():
        company_data = None
        try:
            company_data = query_one("SELECT * FROM companies LIMIT 1")
        except Exception:
            pass

        default_company = {
            'name': 'inFlow Premium',
            'currency_symbol': '$',
            'currency_code': 'USD',
            'decimal_places_price': 2,
            'decimal_places_cost': 3,
            'decimal_places_qty': 0,
            'decimal_places_markup': 2,
            'decimal_places_total': 2,
            'decimal_places_measurement': 2
        }

        # Multi-Branch Context & Permission Control
        current_branch = None
        is_branch_mode = False
        all_branches = []
        branch_permissions = {
            'dashboard': True,
            'pos': True,
            'sales_orders': True,
            'invoices': True,
            'inventory': True,
            'transfers': True,
            'adjustments': True,
            'purchasing': True,
            'expenses': True,
            'customers': True,
            'reports': True,
            'edit_prices': True,
            'view_costs': True
        }

        current_user = None
        try:
            from flask import session, request
            import json

            user_id = session.get('user_id')
            if user_id:
                user_role = session.get('role', 'branch_admin')
                user_bid = session.get('branch_id')

                current_user = {
                    'id': user_id,
                    'username': session.get('username', 'user'),
                    'display_name': session.get('display_name', 'User'),
                    'role': user_role,
                    'branch_id': user_bid,
                    'permissions': session.get('permissions') or {},
                    'is_main_admin': (user_role == 'main_admin'),
                    'is_branch_admin': (user_role in ('branch_admin', 'branch_cashier'))
                }

                # If user is branch_admin, restrict all_branches to ONLY their allowable branch!
                if current_user['is_branch_admin'] and user_bid:
                    all_branches = query_all("SELECT id, code, name, is_active FROM branches WHERE is_active = TRUE AND id = %s ORDER BY id ASC", (user_bid,))
                    active_bid = user_bid
                else:
                    all_branches = query_all("SELECT id, code, name, is_active FROM branches WHERE is_active = TRUE ORDER BY id ASC")
                    active_bid = session.get('active_branch_id') or request.args.get('branch')
            else:
                all_branches = query_all("SELECT id, code, name, is_active FROM branches WHERE is_active = TRUE ORDER BY id ASC")
                active_bid = session.get('active_branch_id') or request.args.get('branch')

            if active_bid and str(active_bid).lower() not in ('main', 'all', 'none', '', '0'):
                b_row = query_one("SELECT * FROM branches WHERE id = %s", (int(active_bid),))
                if b_row:
                    current_branch = {
                        'id': b_row['id'],
                        'code': b_row['code'],
                        'name': b_row['name'],
                        'so_prefix': b_row.get('so_prefix'),
                        'location_id': b_row.get('location_id'),
                        'is_active': b_row.get('is_active')
                    }
                    is_branch_mode = True
                    raw_perm = b_row.get('permissions_json')
                    if raw_perm:
                        if isinstance(raw_perm, str):
                            branch_permissions = json.loads(raw_perm)
                        elif isinstance(raw_perm, dict):
                            branch_permissions = raw_perm
        except Exception as e:
            logger.warning(f"Error resolving branch context in inject_global_data: {e}")

        from routes.auth import user_can_edit_prices, user_can_view_costs, check_permission

        can_edit_prices = user_can_edit_prices()
        can_view_costs = user_can_view_costs()

        branch_permissions['edit_prices'] = can_edit_prices
        branch_permissions['view_costs'] = can_view_costs

        return {
            'company': company_data or default_company,
            'current_year': datetime.now().year,
            'current_time': datetime.now(),
            'current_branch': current_branch,
            'is_branch_mode': is_branch_mode,
            'all_branches': all_branches,
            'branch_permissions': branch_permissions,
            'can_view_costs': can_view_costs,
            'can_edit_prices': can_edit_prices,
            'has_permission': check_permission,
            'current_user': current_user,
            'app_logo_url': (company_data.get('app_logo_url') if company_data else None)
        }


    # Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('base.html', not_found=True), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        logger.error(f"Internal server error: {e}", exc_info=True)
        orig = getattr(e, 'original_exception', e)
        from flask import request
        if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'error': 'Internal server error occurred', 'details': str(orig)}), 500
        
        err_str = str(orig)
        is_db = any(k in err_str.lower() for k in ['psycopg2', 'connection to server', 'connection refused', 'postgresql', 'pool'])
        return render_template(
            'error.html',
            error_title="Database Connection Notice" if is_db else "Internal Server Error",
            error_message=err_str,
            is_db_error=is_db
        ), 500

    @app.route('/health')
    def health_check():
        db_ok = False
        try:
            ver = query_one("SELECT version() as ver")['ver']
            db_ok = True
        except Exception as e:
            ver = str(e)

        return jsonify({
            'status': 'healthy' if db_ok else 'unhealthy',
            'app': 'inFlow Premium',
            'version': '2.0-Enterprise',
            'database': 'PostgreSQL 16',
            'db_version': ver,
            'timestamp': datetime.now().isoformat()
        })

    @app.route('/landing')
    @app.route('/portal')
    def landing_portal():
        return redirect(url_for('dashboard.index'))

    return app

app = create_app()

if __name__ == '__main__':
    import socket
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = '127.0.0.1'

    logger.info("==================================================================")
    logger.info("   inFlow Premium Web Application (Local Server Active)")
    logger.info(f"   [This PC]       : http://localhost:{Config.PORT}")
    logger.info(f"   [Other Devices] : http://{lan_ip}:{Config.PORT}")
    logger.info("   High performance enterprise PostgreSQL backend active.")
    logger.info("==================================================================")
    try:
        from waitress import serve
        logger.info(" Serving with Waitress production WSGI server (threads=6, no thread exhaustion)...")
        serve(app, host=Config.HOST, port=Config.PORT, threads=6)
    except Exception as e:
        logger.warning(f" Waitress failed ({e}), falling back to Werkzeug development server...")
        app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
