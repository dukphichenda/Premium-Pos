from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from database import query_one
try:
    from migrate_inflow import migrate_all, get_sqlserver_connection
except ImportError:
    migrate_all = None
    def get_sqlserver_connection():
        raise RuntimeError("migrate_inflow module is not available in this environment.")
from config import Config
import logging

logger = logging.getLogger('inflow.migration_route')
migration_bp = Blueprint('migration', __name__)

@migration_bp.route('/settings/migration')
def migration_page():
    # PostgreSQL counts
    pg_stats = {
        'products': query_one("SELECT COUNT(*) as cnt FROM products")['cnt'],
        'categories': query_one("SELECT COUNT(*) as cnt FROM categories")['cnt'],
        'locations': query_one("SELECT COUNT(*) as cnt FROM locations")['cnt'],
        'customers': query_one("SELECT COUNT(*) as cnt FROM customers")['cnt'],
        'vendors': query_one("SELECT COUNT(*) as cnt FROM vendors")['cnt'],
        'sales_orders': query_one("SELECT COUNT(*) as cnt FROM sales_orders")['cnt'],
        'purchase_orders': query_one("SELECT COUNT(*) as cnt FROM purchase_orders")['cnt'],
    }

    # SQL Server check
    sqlserver_connected = False
    sqlserver_stats = {}
    try:
        conn = get_sqlserver_connection()
        cur = conn.cursor()
        sqlserver_connected = True
        cur.execute("SELECT COUNT(*) FROM BASE_Product")
        sqlserver_stats['products'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM BASE_Customer")
        sqlserver_stats['customers'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM SO_SalesOrder")
        sqlserver_stats['sales_orders'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM PO_PurchaseOrder")
        sqlserver_stats['purchase_orders'] = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        logger.warning(f"Could not connect to SQL Server during page load: {e}")

    return render_template('settings/migration.html',
                           pg_stats=pg_stats,
                           sqlserver_connected=sqlserver_connected,
                           sqlserver_stats=sqlserver_stats,
                           config=Config)

@migration_bp.route('/api/migration/test')
def test_connection():
    try:
        conn = get_sqlserver_connection()
        cur = conn.cursor()
        cur.execute("SELECT @@SERVERNAME, DB_NAME()")
        row = cur.fetchone()
        conn.close()
        return jsonify({
            'success': True,
            'server': row[0],
            'database': row[1],
            'message': f"Connected successfully to SQL Server {row[0]} database '{row[1]}'."
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@migration_bp.route('/api/migration/run', methods=['POST'])
def run_migration_api():
    try:
        limit = request.json.get('limit_orders') if request.is_json else None
        res = migrate_all(limit_orders=limit)
        return jsonify({
            'success': True,
            'stats': res,
            'message': f"Successfully migrated data into PostgreSQL in {res['duration_seconds']}s!"
        })
    except Exception as e:
        logger.error(f"Migration API failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
