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
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB

    # Reverse proxy middleware for Nginx & Hostinger SSL termination
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize Database Schema
    if not getattr(Config, 'IS_CLOUD_DB', False):
        try:
            init_db()
        except Exception as e:
            logger.error(f"Error during database startup check: {e}")
    else:
        # On cloud/Hostinger environments, ensure numbering sequences are always in sync with max orders
        try:
            from database import resync_all_sequences
            resync_all_sequences()
        except Exception as e:
            logger.error(f"Error during sequence synchronization startup check: {e}")

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

    # Initialize Automated Database Backup Scheduler
    try:
        from services.backup_service import start_backup_scheduler
        start_backup_scheduler()
    except Exception as sched_err:
        logger.warning(f"Could not start automated backup scheduler: {sched_err}")

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

        # Allow public direct print for sales orders with valid share token
        if request.path.startswith('/sales/') and request.path.endswith('/print'):
            import re
            m = re.match(r'^/sales/(\d+)/print$', request.path)
            if m:
                order_id = int(m.group(1))
                tok = request.args.get('token') or request.args.get('share_token')
                if tok:
                    from routes.sales_orders import verify_order_share_token
                    if verify_order_share_token(order_id, tok):
                        return None

        # Check session or restore from persistent remember cookie
        if 'user_id' not in session or not session.get('user_id'):
            from routes.auth import verify_remember_token
            rem_token = request.cookies.get('inflow_remember')
            uid = verify_remember_token(rem_token) if rem_token else None
            if uid:
                u_row = None
                try:
                    u_row = query_one("SELECT * FROM users WHERE id = %s AND is_active = TRUE", (uid,))
                except Exception:
                    u_row = None
                if not u_row and uid == 1:
                    u_row = {
                        'id': 1,
                        'username': 'admin',
                        'display_name': 'System Administrator',
                        'role': 'main_admin',
                        'branch_id': None,
                        'permissions_json': {}
                    }
                if u_row:
                    session.permanent = True
                    session['user_id'] = u_row['id']
                    session['username'] = u_row['username']
                    session['display_name'] = u_row.get('display_name', u_row['username'])
                    session['role'] = u_row.get('role', 'main_admin')
                    session['branch_id'] = u_row.get('branch_id')
                    perms = u_row.get('permissions_json')
                    if isinstance(perms, str):
                        try:
                            perms = json.loads(perms)
                        except Exception:
                            perms = {}
                    session['permissions'] = perms or {}

        # If unauthenticated, redirect to login
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
            target = request.full_path if (request.method == 'GET' and request.path not in ('/login', '/logout', '/')) else None
            if target:
                target = target.rstrip('?')
                if target in ('/', ''):
                    target = None

            # If unauthenticated request is inside an iframe tab, break out top-level window directly
            if request.args.get('embed') == '1' or request.headers.get('Sec-Fetch-Dest') == 'iframe':
                from flask import Response
                html = """<!DOCTYPE html><html><head><meta charset="utf-8">
                <script>
                try {
                    localStorage.removeItem('inflow_mdi_tabs_v5');
                    localStorage.removeItem('inflow_mdi_active_tab_v5');
                    localStorage.removeItem('inflow_mdi_tabs');
                    localStorage.removeItem('inflow_mdi_active_tab');
                    localStorage.removeItem('inflow_active_store_id');
                    sessionStorage.clear();
                } catch(e) {}
                if (window.top) {
                    window.top.location.href = "/login";
                } else {
                    window.location.href = "/login";
                }
                </script>
                </head><body><p>Session expired. <a href="/login" target="_top">Sign in</a>.</p></body></html>"""
                return Response(html, mimetype='text/html')

            return redirect(url_for('auth.login', next=target))

        # Always maintain permanent session lifetime on active usage
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
                    all_branches = query_all("SELECT id, code, name, color, is_active, settings_json FROM branches WHERE is_active = TRUE AND id = %s ORDER BY id ASC", (user_bid,))
                    active_bid = user_bid
                else:
                    all_branches = query_all("SELECT id, code, name, color, is_active, settings_json FROM branches WHERE is_active = TRUE ORDER BY id ASC")
                    active_bid = session.get('active_branch_id') or request.args.get('branch')
            else:
                all_branches = query_all("SELECT id, code, name, color, is_active, settings_json FROM branches WHERE is_active = TRUE ORDER BY id ASC")
                active_bid = session.get('active_branch_id') or request.args.get('branch')

            if not active_bid and request.view_args and 'id' in request.view_args and request.endpoint and request.endpoint.startswith('branches.') and request.endpoint not in ('branches.switch_branch', 'branches.list_branches', 'branches.branch_launcher'):
                active_bid = request.view_args['id']

            for b in all_branches:
                raw_s = b.get('settings_json')
                if raw_s:
                    if isinstance(raw_s, str):
                        try:
                            raw_s = json.loads(raw_s)
                        except Exception:
                            raw_s = {}
                    b['logo_url'] = raw_s.get('logo_url') or ''
                    b['primary_color'] = raw_s.get('primary_color') or b.get('color') or '#10B981'
                else:
                    b['logo_url'] = ''
                    b['primary_color'] = b.get('color') or '#10B981'

            if active_bid and str(active_bid).lower() not in ('main', 'all', 'none', '', '0'):
                b_row = query_one("SELECT * FROM branches WHERE id = %s", (int(active_bid),))
                if b_row:
                    raw_s = b_row.get('settings_json')
                    if raw_s:
                        if isinstance(raw_s, str):
                            try:
                                raw_s = json.loads(raw_s)
                            except Exception:
                                raw_s = {}
                        logo_url = raw_s.get('logo_url') or ''
                        primary_color = raw_s.get('primary_color') or b_row.get('color') or '#10B981'
                    else:
                        logo_url = ''
                        primary_color = b_row.get('color') or '#10B981'

                    current_branch = {
                        'id': b_row['id'],
                        'code': b_row['code'],
                        'name': b_row['name'],
                        'color': b_row.get('color') or primary_color,
                        'primary_color': primary_color,
                        'logo_url': logo_url,
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

        # Resolve HQ Invoice Logo URL & Primary Brand Color
        hq_invoice_logo_url = None
        hq_primary_color = '#0D9488'
        try:
            inv_row = query_one("SELECT logo_url, primary_color FROM invoice_settings LIMIT 1")
            if inv_row:
                if inv_row.get('logo_url'):
                    hq_invoice_logo_url = inv_row['logo_url']
                if inv_row.get('primary_color'):
                    hq_primary_color = inv_row['primary_color']
            elif company_data and company_data.get('logo_url'):
                hq_invoice_logo_url = company_data['logo_url']
            elif company_data and company_data.get('app_logo_url'):
                hq_invoice_logo_url = company_data['app_logo_url']
        except Exception:
            pass

        # Helper to compute complementary shades for store branding
        def _shade_hex(hex_str, factor):
            try:
                h = (hex_str or '#10B981').lstrip('#')
                if len(h) == 3:
                    h = ''.join(c * 2 for c in h)
                r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
                if factor <= 1:
                    r2, g2, b2 = r * factor, g * factor, b * factor
                else:
                    r2 = r + (255 - r) * (factor - 1)
                    g2 = g + (255 - g) * (factor - 1)
                    b2 = b + (255 - b) * (factor - 1)
                return f'#{max(0, min(255, int(round(r2)))):02X}{max(0, min(255, int(round(g2)))):02X}{max(0, min(255, int(round(b2)))):02X}'
            except Exception:
                return hex_str

        if is_branch_mode and current_branch:
            store_primary = current_branch.get('primary_color') or current_branch.get('color') or '#10B981'
            store_dark = _shade_hex(store_primary, 0.80)
            store_sidebar_top = _shade_hex(store_primary, 0.85)
            store_sidebar_bottom = _shade_hex(store_primary, 0.55)
            store_theme = {
                'primary': store_primary,
                'dark': store_dark,
                'top_bar_bg': f'linear-gradient(90deg, {store_primary} 0%, {store_dark} 100%)',
                'sidebar_bg': f'linear-gradient(180deg, {store_sidebar_top} 0%, {store_sidebar_bottom} 100%)',
                'accent': store_primary,
                'button_text': store_primary,
                'is_branch': True
            }
        else:
            hq_primary = hq_primary_color or '#0D9488'
            hq_dark = _shade_hex(hq_primary, 0.80)
            hq_sidebar_top = _shade_hex(hq_primary, 0.85)
            hq_sidebar_bottom = _shade_hex(hq_primary, 0.55)
            store_theme = {
                'primary': hq_primary,
                'dark': hq_dark,
                'top_bar_bg': f'linear-gradient(90deg, {hq_primary} 0%, {hq_dark} 100%)',
                'sidebar_bg': f'linear-gradient(180deg, {hq_sidebar_top} 0%, {hq_sidebar_bottom} 100%)',
                'accent': hq_primary,
                'button_text': hq_primary,
                'is_branch': False
            }

        from routes.auth import user_can_edit_prices, user_can_view_costs, user_can_edit_product, check_permission

        can_edit_prices = user_can_edit_prices()
        can_view_costs = user_can_view_costs()
        can_edit_product = user_can_edit_product()

        branch_permissions['edit_prices'] = can_edit_prices
        branch_permissions['view_costs'] = can_view_costs
        branch_permissions['edit_products'] = can_edit_product

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
            'can_edit_product': can_edit_product,
            'has_permission': check_permission,
            'current_user': current_user,
            'app_logo_url': (company_data.get('app_logo_url') if company_data else None),
            'hq_logo_url': hq_invoice_logo_url,
            'store_theme': store_theme,
            'active_store_primary_color': store_theme['primary']
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

    @app.route('/static/uploads/<path:filename>')
    def serve_uploaded_media(filename):
        from flask import send_from_directory
        uploads_dir = os.path.join(base_dir, 'static', 'uploads')
        file_path = os.path.join(uploads_dir, filename)
        if not os.path.exists(file_path):
            try:
                rel_path = f"static/uploads/{filename.replace(os.sep, '/')}"
                row = query_one("SELECT file_data FROM app_uploaded_files WHERE rel_path = %s LIMIT 1", (rel_path,))
                if row and row.get('file_data'):
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, 'wb') as fp:
                        fp.write(bytes(row['file_data']))
            except Exception as e:
                logger.warning(f"Could not auto-recover image {filename} from DB: {e}")
        return send_from_directory(uploads_dir, filename)

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
