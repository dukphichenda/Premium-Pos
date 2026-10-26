from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val, get_next_order_number, preview_order_number, resync_all_sequences, sync_inventory_reserved_quantities
from datetime import datetime, date, timedelta
import re, os, time, json, mimetypes, logging, uuid, hmac, hashlib
from werkzeug.utils import secure_filename
from routes.auth import user_can_edit_prices, user_can_view_costs

logger = logging.getLogger(__name__)

sales_orders_bp = Blueprint('sales_orders', __name__)

def generate_order_share_token(order_id):
    from config import Config
    secret = (getattr(Config, 'SECRET_KEY', None) or 'inflow_premium_super_secret_key_2026_boost').encode('utf-8')
    return hmac.new(secret, f"inflow_so_print_{order_id}".encode('utf-8'), hashlib.sha256).hexdigest()[:16]

def verify_order_share_token(order_id, token):
    if not token or not order_id:
        return False
    try:
        expected = generate_order_share_token(order_id)
        return hmac.compare_digest(str(token).strip(), expected)
    except Exception:
        return False

def build_order_telegram_share(order, base_host, image_url=None):
    import urllib.parse
    order_id = order['id']
    token = generate_order_share_token(order_id)
    preview_url = f"{base_host}/sales/{order_id}/print?type=invoice&token={token}"
    
    order_num = order.get('order_number') or f"SO-{order_id}"
    cust_name = order.get('customer_name') or 'Customer'
    total = float(order.get('total_amount') or 0.0)
    
    caption_lines = [
        f"📄 Invoice: {order_num}",
        f"👤 Customer: {cust_name}",
        f"💵 Total: ${total:,.2f}",
        "",
        f"🔗 Invoice Print Preview / មើលនិងបោះពុម្ពវិក្កយបត្រ:",
        preview_url
    ]
    if image_url:
        caption_lines.extend(["", f"🖼️ Invoice Image / រូបភាព:", image_url])
        
    caption = "\n".join(caption_lines)
    telegram_url = f"https://t.me/share/url?url={urllib.parse.quote(preview_url)}&text={urllib.parse.quote(caption)}"
    
    return {
        'order_id': order_id,
        'order_number': order_num,
        'customer_name': cust_name,
        'total_amount': total,
        'token': token,
        'preview_url': preview_url,
        'direct_print_url': preview_url,
        'image_url': image_url,
        'caption': caption,
        'telegram_url': telegram_url
    }

def _ensure_so_tables_exist():
    try:
        execute("""
            CREATE TABLE IF NOT EXISTS sales_order_attachments (
                id SERIAL PRIMARY KEY,
                sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
                file_name VARCHAR(255) NOT NULL,
                file_path TEXT NOT NULL,
                file_size BIGINT DEFAULT 0,
                file_type VARCHAR(100),
                caption TEXT,
                uploaded_by VARCHAR(150),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_so_attachments_order_id ON sales_order_attachments(sales_order_id);

            CREATE TABLE IF NOT EXISTS sales_order_versions (
                id SERIAL PRIMARY KEY,
                sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL DEFAULT 1,
                order_number VARCHAR(100),
                status VARCHAR(50),
                payment_status VARCHAR(50),
                customer_name VARCHAR(255),
                total_amount NUMERIC(16, 4) DEFAULT 0,
                paid_amount NUMERIC(16, 4) DEFAULT 0,
                balance_due NUMERIC(16, 4) DEFAULT 0,
                items_count INTEGER DEFAULT 0,
                user_name VARCHAR(150),
                change_summary TEXT,
                snapshot_data JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_so_versions_order_id ON sales_order_versions(sales_order_id);

            ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS submission_token VARCHAR(64);
            CREATE INDEX IF NOT EXISTS idx_sales_orders_sub_token ON sales_orders(submission_token);
        """)
    except Exception as e:
        logger.warning(f"Error ensuring SO auxiliary tables: {e}")

def _record_order_version(order_id, user_name=None, change_summary=None):
    _ensure_so_tables_exist()
    try:
        order = query_one("""
            SELECT so.*, c.name as customer_name
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.id = %s
        """, (order_id,))
        if not order:
            return

        lines = query_all("""
            SELECT sol.line_num, sol.description, sol.quantity, sol.unit_price, sol.subtotal,
                   p.name as product_name, p.sku as product_sku, sol.uom
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE sol.sales_order_id = %s
            ORDER BY sol.line_num ASC
        """, (order_id,))

        max_v = query_one("SELECT COALESCE(MAX(version_number), 0) as mv FROM sales_order_versions WHERE sales_order_id = %s", (order_id,))
        next_v = (max_v['mv'] if max_v else 0) + 1

        uname = user_name or session.get('username') or session.get('display_name') or 'Admin'
        summary = change_summary or (f"Order Created (v1)" if next_v == 1 else f"Order Updated (Total: ${float(order.get('total_amount') or 0):,.2f})")

        snapshot = {
            'order_number': order.get('order_number'),
            'order_date': str(order.get('order_date')),
            'customer_name': order.get('customer_name'),
            'status': order.get('status'),
            'payment_status': order.get('payment_status'),
            'total_amount': float(order.get('total_amount') or 0),
            'paid_amount': float(order.get('paid_amount') or 0),
            'balance_due': float(order.get('balance_due') or 0),
            'notes': order.get('notes'),
            'carrier': order.get('carrier'),
            'delivery_notes': order.get('delivery_notes'),
            'lines': [
                {
                    'line_num': l.get('line_num'),
                    'sku': l.get('product_sku') or '',
                    'name': l.get('product_name') or l.get('description') or '',
                    'qty': float(l.get('quantity') or 0),
                    'uom': l.get('uom') or 'pcs.',
                    'price': float(l.get('unit_price') or 0),
                    'subtotal': float(l.get('subtotal') or 0)
                }
                for l in lines
            ]
        }

        execute("""
            INSERT INTO sales_order_versions (
                sales_order_id, version_number, order_number, status, payment_status,
                customer_name, total_amount, paid_amount, balance_due, items_count,
                user_name, change_summary, snapshot_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            order_id, next_v, order.get('order_number'), order.get('status'), order.get('payment_status'),
            order.get('customer_name'), float(order.get('total_amount') or 0),
            float(order.get('paid_amount') or 0), float(order.get('balance_due') or 0),
            len(lines), uname, summary, json.dumps(snapshot)
        ))
    except Exception as e:
        logger.warning(f"Error recording order version: {e}")

def _is_main_admin():
    return session.get('role') == 'main_admin'

def _get_user_branch_id():
    if _is_main_admin():
        return None
    bid = session.get('branch_id')
    if bid and str(bid).isdigit():
        return int(bid)
    return None

def _check_order_branch_access(order):
    """
    Enforces multi-branch isolation on sales orders:
    - Main store HQ admin (role == 'main_admin') has unrestricted visibility and rights across all orders.
    - Branch users (branch_admin, branch_cashier) are strictly locked to orders of their own branch.
    """
    if _is_main_admin():
        return True
    user_bid = _get_user_branch_id()
    if not user_bid:
        return False
    return order.get('branch_id') == user_bid

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

def _get_product_components_map():
    """
    Returns a mapping of {product_id: [component_dict, ...]} for all kit/bundle products
    including each component's live stock_on_hand, stock_reserved, and stock_available.
    Checks both product_boms and product_combine_options.
    """
    comp_map = {}
    
    # 1. From product_boms
    boms = query_all("""
        SELECT 
            pb.product_id,
            pb.component_product_id as component_id,
            COALESCE(pb.quantity, 1.0) as quantity,
            COALESCE(p.sku, '') as sku,
            COALESCE(p.name, '') as name,
            COALESCE(p.uom, 'pcs.') as uom,
            COALESCE(inv.stock_on_hand, 0) as stock_on_hand,
            COALESCE(inv.stock_reserved, 0) as stock_reserved,
            (COALESCE(inv.stock_on_hand, 0) - COALESCE(inv.stock_reserved, 0)) as stock_available
        FROM product_boms pb
        JOIN products p ON pb.component_product_id = p.id
        LEFT JOIN (
            SELECT product_id, 
                   SUM(quantity) as stock_on_hand, 
                   SUM(reserved_quantity) as stock_reserved 
            FROM inventory 
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        ORDER BY pb.product_id, pb.id ASC
    """)
    for row in (boms or []):
        pid = row['product_id']
        if pid not in comp_map:
            comp_map[pid] = []
        comp_map[pid].append({
            'component_id': row['component_id'],
            'sku': row['sku'] or '',
            'name': row['name'] or '',
            'uom': row['uom'] or 'pcs.',
            'quantity': float(row['quantity'] or 1.0),
            'stock_on_hand': float(row['stock_on_hand'] or 0.0),
            'stock_reserved': float(row['stock_reserved'] or 0.0),
            'stock_available': float(row['stock_available'] or 0.0),
        })

    # 2. From product_combine_options
    combos = query_all("""
        SELECT 
            pco.product_id,
            pco.component_product_id as component_id,
            COALESCE(pco.component_quantity, 1.0) as quantity,
            COALESCE(pco.option_name, p.name, '') as name,
            COALESCE(p.sku, '') as sku,
            COALESCE(p.uom, 'pcs.') as uom,
            COALESCE(inv.stock_on_hand, 0) as stock_on_hand,
            COALESCE(inv.stock_reserved, 0) as stock_reserved,
            (COALESCE(inv.stock_on_hand, 0) - COALESCE(inv.stock_reserved, 0)) as stock_available
        FROM product_combine_options pco
        JOIN products p ON pco.component_product_id = p.id
        LEFT JOIN (
            SELECT product_id, 
                   SUM(quantity) as stock_on_hand, 
                   SUM(reserved_quantity) as stock_reserved 
            FROM inventory 
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        ORDER BY pco.product_id, pco.sort_order ASC, pco.id ASC
    """)
    for row in (combos or []):
        pid = row['product_id']
        if pid not in comp_map:
            comp_map[pid] = []
        if not any(c['component_id'] == row['component_id'] for c in comp_map[pid]):
            comp_map[pid].append({
                'component_id': row['component_id'],
                'sku': row['sku'] or '',
                'name': row['name'] or '',
                'uom': row['uom'] or 'pcs.',
                'quantity': float(row['quantity'] or 1.0),
                'stock_on_hand': float(row['stock_on_hand'] or 0.0),
                'stock_reserved': float(row['stock_reserved'] or 0.0),
                'stock_available': float(row['stock_available'] or 0.0),
            })

    return comp_map

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
    is_main = _is_main_admin()
    user_bid = _get_user_branch_id()
    raw_branch = request.args.get('branch')

    if not is_main:
        # Branch users are strictly locked to their assigned branch: cannot view HQ or other branches!
        branch_filter = str(user_bid) if user_bid else '-1'
    else:
        # HQ (main_admin) can see main (default), specific branch, or all
        if raw_branch is not None:
            branch_filter = raw_branch.strip().lower()
        else:
            branch_filter = 'main'  # HQ default overview: Main Store (HQ)

    # Standalone table view deprecated per user instructions;
    # redirect directly to Sales Order workspace with modern sidebar.
    status_filter = request.args.get('status') or request.args.get('status_filter') or 'Open'
    date_filter = request.args.get('date_filter') or 'All'
    search = request.args.get('search') or ''

    if not is_main:
        if status_filter.upper() == 'PAID':
            latest = query_one("""
                SELECT id FROM sales_orders 
                WHERE branch_id = %s 
                  AND (UPPER(status) IN ('PAID', 'INVOICED') OR UPPER(payment_status) = 'PAID')
                ORDER BY id DESC LIMIT 1
            """, (user_bid,)) if user_bid else None
            if not latest and user_bid:
                latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (user_bid,))
        elif status_filter.upper() == 'OPEN':
            latest = query_one("""
                SELECT id FROM sales_orders 
                WHERE branch_id = %s 
                  AND UPPER(status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')
                ORDER BY id DESC LIMIT 1
            """, (user_bid,)) if user_bid else None
            if not latest and user_bid:
                latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (user_bid,))
        else:
            latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (user_bid,)) if user_bid else None
    else:
        if branch_filter == 'main':
            if status_filter.upper() == 'PAID':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE branch_id IS NULL 
                      AND (UPPER(status) IN ('PAID', 'INVOICED') OR UPPER(payment_status) = 'PAID')
                    ORDER BY id DESC LIMIT 1
                """)
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 1")
            elif status_filter.upper() == 'OPEN':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE branch_id IS NULL 
                      AND UPPER(status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')
                    ORDER BY id DESC LIMIT 1
                """)
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 1")
            else:
                latest = query_one("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 1")
        elif branch_filter.isdigit():
            b_id = int(branch_filter)
            if status_filter.upper() == 'PAID':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE branch_id = %s 
                      AND (UPPER(status) IN ('PAID', 'INVOICED') OR UPPER(payment_status) = 'PAID')
                    ORDER BY id DESC LIMIT 1
                """, (b_id,))
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (b_id,))
            elif status_filter.upper() == 'OPEN':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE branch_id = %s 
                      AND UPPER(status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')
                    ORDER BY id DESC LIMIT 1
                """, (b_id,))
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (b_id,))
            else:
                latest = query_one("SELECT id FROM sales_orders WHERE branch_id = %s ORDER BY id DESC LIMIT 1", (b_id,))
        else:
            if status_filter.upper() == 'PAID':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE (UPPER(status) IN ('PAID', 'INVOICED') OR UPPER(payment_status) = 'PAID')
                    ORDER BY id DESC LIMIT 1
                """)
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
            elif status_filter.upper() == 'OPEN':
                latest = query_one("""
                    SELECT id FROM sales_orders 
                    WHERE UPPER(status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')
                    ORDER BY id DESC LIMIT 1
                """)
                if not latest:
                    latest = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
            else:
                latest = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")

    if latest:
        return redirect(url_for('sales_orders.detail_order', id=latest['id'], branch=branch_filter, status_filter=status_filter, date_filter=date_filter, search=search))
    return redirect(url_for('sales_orders.new_order', branch=branch_filter, status_filter=status_filter, date_filter=date_filter, search=search))

    if not is_main:
        if user_bid:
            where_clauses.append("so.branch_id = %s")
            params.append(user_bid)
        else:
            where_clauses.append("1=0")
    else:
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

    if is_main:
        branches = query_all("SELECT id, code, name, color, settings_json FROM branches WHERE is_active = TRUE ORDER BY id ASC")
    else:
        branches = query_all("SELECT id, code, name, color, settings_json FROM branches WHERE id = %s", (user_bid,))

    for b in branches:
        raw_s = b.get('settings_json')
        s_dict = json.loads(raw_s) if isinstance(raw_s, str) else (raw_s or {})
        b['logo_url'] = s_dict.get('logo_url') or ''

    current_branch = query_one("SELECT id, code, name FROM branches WHERE id = %s", (user_bid,)) if user_bid else None

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
                           branch_filter=branch_filter,
                           is_branch_user=(not is_main),
                           current_branch=current_branch)

def _parse_order_date(raw_date, default_date=None):
    from datetime import datetime as dt_parser, date, timedelta
    if not raw_date:
        return default_date or date.today()
    if isinstance(raw_date, date):
        return raw_date
    if isinstance(raw_date, dt_parser):
        return raw_date.date()

    val = str(raw_date).strip()
    if not val:
        return default_date or date.today()

    val_lower = val.lower()
    today = date.today()
    if val_lower in ('today', 't'):
        return today
    if val_lower in ('yesterday', 'y'):
        return today - timedelta(days=1)
    if val_lower in ('tomorrow',):
        return today + timedelta(days=1)

    formats = (
        '%d-%b-%y', '%d-%b-%Y', '%d-%B-%y', '%d-%B-%Y',
        '%d %b %y', '%d %b %Y', '%d %B %y', '%d %B %Y',
        '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d',
        '%d/%m/%Y', '%d/%m/%y',
        '%d-%m-%Y', '%d-%m-%y',
        '%d.%m.%Y', '%d.%m.%y',
        '%m/%d/%Y', '%m/%d/%y',
        '%m-%d-%Y', '%m-%d-%y'
    )
    for fmt in formats:
        try:
            return dt_parser.strptime(val, fmt).date()
        except (ValueError, TypeError):
            pass

    current_year = today.year
    for short_fmt, append_str in (
        ('%d-%b-%Y', f'-{current_year}'),
        ('%d %b %Y', f' {current_year}'),
        ('%d/%m/%Y', f'/{current_year}'),
        ('%d-%m-%Y', f'-{current_year}'),
        ('%d.%m.%Y', f'.{current_year}'),
    ):
        try:
            return dt_parser.strptime(val + append_str, short_fmt).date()
        except (ValueError, TypeError):
            pass

    try:
        from dateutil import parser as du_parser
        return du_parser.parse(val).date()
    except Exception:
        pass

    return default_date or today

@sales_orders_bp.route('/sales/create', methods=['GET', 'POST'])
def create_order():
    is_main = _is_main_admin()
    user_bid = _get_user_branch_id()
    branch_id = user_bid if not is_main else None

    if request.method == 'GET':
        if not is_main:
            if user_bid:
                customers = query_all("SELECT id, name, phone, discount_percent FROM customers WHERE is_active = TRUE AND branch_id = %s ORDER BY name LIMIT 500", (user_bid,))
            else:
                customers = query_all("SELECT id, name, phone, discount_percent FROM customers WHERE is_active = TRUE AND branch_id IS NULL ORDER BY name LIMIT 500")
        else:
            customers = query_all("SELECT id, name, phone, discount_percent FROM customers WHERE is_active = TRUE AND branch_id IS NULL ORDER BY name LIMIT 500")
        locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
        return render_template('sales/create.html', customers=customers, locations=locations)

    try:
        customer_id = int(request.form.get('customer_id')) if request.form.get('customer_id') else None
        if customer_id:
            cust_check = query_one("SELECT branch_id FROM customers WHERE id = %s", (customer_id,))
            if cust_check and cust_check.get('branch_id') != branch_id:
                flash("Access denied: Selected customer belongs to another branch or HQ. Customers of HQ and Branch are kept independently.", "error")
                return redirect(url_for('sales_orders.create_order'))
        location_id = int(request.form.get('location_id'))
        raw_order_date = request.form.get('order_date')
        order_date = _parse_order_date(raw_order_date)
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

        # Generate unique order number auto-generated from last SO
        order_number = get_next_order_number('SO', branch_id=branch_id)

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

            subtotal += line_sub

            # Get product cost
            cost_row = query_one("SELECT average_cost, standard_cost FROM products WHERE id = %s", (pid,))
            cost_price = float(cost_row['average_cost'] or cost_row['standard_cost'] or 0) if cost_row else 0.0

            lines_data.append((idx + 1, pid, desc, qty, price, disc, line_sub, cost_price, addon_pid, addon_qty, combine_opt_id))

        tax_amount = (subtotal - discount_amount) * (tax_rate / 100.0) if tax_rate > 0 else 0.0
        total_amount = max(0.0, subtotal - discount_amount + tax_amount + shipping_fee)
        balance_due = total_amount

        cust_info = query_one("""
            SELECT COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as customer_address,
                   contact_name as customer_contact, phone as customer_phone
            FROM customers WHERE id = %s
        """, (customer_id,)) if customer_id else None
        cust_addr_val = cust_info.get('customer_address') if cust_info else None
        cust_contact_val = cust_info.get('customer_contact') if cust_info else None
        cust_phone_val = cust_info.get('customer_phone') if cust_info else None

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sales_orders (
                    order_number, customer_id, location_id, order_date,
                    status, payment_status, subtotal, tax_rate, tax_amount,
                    discount_amount, shipping_fee, total_amount, paid_amount, balance_due,
                    sales_rep, notes, branch_id, customer_address, customer_contact, customer_phone
                ) VALUES (%s, %s, %s, %s, 'OPEN', 'UNPAID', %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                order_number, customer_id, location_id, order_date,
                subtotal, tax_rate, tax_amount,
                discount_amount, shipping_fee, total_amount, balance_due,
                sales_rep, notes, branch_id,
                cust_addr_val, cust_contact_val, cust_phone_val
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

            # Synchronize live inventory reservations
            sync_inventory_reserved_quantities(cur=cur)

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

def _get_drawer_and_metadata(date_filter='All', status_filter='Open, In Progress, Paid', customer_search='', customer_filter=None, scheme_id=100, branch_id=None, search_query=None, current_order_id=None):
    is_main = _is_main_admin()
    user_bid = _get_user_branch_id()

    drawer_where = ["1=1"]
    drawer_params = []

    # Branch isolation: branch users strictly locked to their branch; main admin sees all orders unless explicitly filtered
    if not is_main:
        if user_bid:
            drawer_where.append("so.branch_id = %s")
            drawer_params.append(user_bid)
        else:
            drawer_where.append("1=0")
    else:
        if branch_id:
            b_str = str(branch_id).strip().lower()
            if b_str == 'main':
                drawer_where.append("so.branch_id IS NULL")
            elif b_str == 'all':
                pass
            elif b_str not in ('none', ''):
                try:
                    bid = int(b_str)
                    drawer_where.append("so.branch_id = %s")
                    drawer_params.append(bid)
                except (ValueError, TypeError):
                    drawer_where.append("so.branch_id IS NULL")
        else:
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

    # Date filter presets (matching inFlow Desktop Recording and Screenshot 1)
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
    elif date_filter == 'Last 90 Days':
        drawer_where.append("so.order_date >= CURRENT_DATE - INTERVAL '90 days' AND so.order_date <= CURRENT_DATE")
    elif date_filter == 'Last 365 Days':
        drawer_where.append("so.order_date >= CURRENT_DATE - INTERVAL '365 days' AND so.order_date <= CURRENT_DATE")
    elif date_filter == 'Tomorrow':
        drawer_where.append("so.order_date = CURRENT_DATE + INTERVAL '1 day'")
    elif date_filter == 'Next Week':
        drawer_where.append("date_trunc('week', so.order_date::timestamp) = date_trunc('week', CURRENT_DATE::timestamp + INTERVAL '1 week')")
    elif date_filter == 'Next Month':
        drawer_where.append("date_trunc('month', so.order_date::timestamp) = date_trunc('month', CURRENT_DATE::timestamp + INTERVAL '1 month')")
    elif date_filter == 'Next Quarter':
        drawer_where.append("date_trunc('quarter', so.order_date::timestamp) = date_trunc('quarter', CURRENT_DATE::timestamp + INTERVAL '3 months')")
    elif date_filter == 'Next Year':
        drawer_where.append("date_trunc('year', so.order_date::timestamp) = date_trunc('year', CURRENT_DATE::timestamp + INTERVAL '1 year')")
    elif date_filter == 'Custom':
        custom_from = (request.args.get('date_from') or '').strip()
        custom_to = (request.args.get('date_to') or '').strip()
        if custom_from:
            drawer_where.append("so.order_date >= %s")
            drawer_params.append(custom_from)
        if custom_to:
            drawer_where.append("so.order_date <= %s")
            drawer_params.append(custom_to)

    # Delivery man filter
    delivery_man_filter = (request.args.get('delivery_man') or '').strip()
    if delivery_man_filter and delivery_man_filter.lower() != 'all':
        if delivery_man_filter.lower() == 'unassigned':
            drawer_where.append("(so.delivery_man IS NULL OR TRIM(so.delivery_man) = '')")
        else:
            drawer_where.append("so.delivery_man = %s")
            drawer_params.append(delivery_man_filter)

    # General search query (order #, customer name, delivery man, or total amount)
    curr_user = (session.get('username') or '').strip().lower()
    if search_query is None:
        if 'search' in request.args or 'q' in request.args:
            search_query = (request.args.get('search') or request.args.get('q') or '').strip()
        else:
            search_query = (session.get('so_search_query') or '').strip()

    # Never auto-search the current user's login username (e.g. 'chenda' or 'admin')
    if search_query and curr_user and search_query.lower() == curr_user:
        search_query = ''
        session.pop('so_search_query', None)

    if search_query:
        sp = f"%{search_query}%"
        drawer_where.append("(so.order_number ILIKE %s OR c.name ILIKE %s OR so.delivery_man ILIKE %s OR CAST(so.total_amount AS TEXT) ILIKE %s)")
        drawer_params.extend([sp, sp, sp, sp])

    # Status filter (supports multi-select comma separated statuses, e.g. Open, Unfulfilled, Fulfilled, Paid, All)
    # Respect status_filter so sale status (e.g. Open sale) stays as selected
    if status_filter and status_filter.strip() and status_filter.strip().lower() != 'all':
        tokens = [t.strip().lower() for t in status_filter.split(',') if t.strip()]
        status_clauses = []
        for token in tokens:
            if token == 'quote':
                status_clauses.append("UPPER(so.status) = 'QUOTE'")
            elif token in ('open', 'unfulfilled'):
                status_clauses.append("UPPER(so.status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')")
            elif token in ('in progress', 'in_progress'):
                status_clauses.append("UPPER(so.status) IN ('IN_PROGRESS', 'PICKED', 'PACKED')")
            elif token in ('fully shipped', 'shipped', 'fulfilled'):
                status_clauses.append("(UPPER(so.status) IN ('SHIPPED', 'INVOICED') OR UPPER(so.payment_status) = 'PAID')")
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
            if current_order_id:
                drawer_where.append("((" + " OR ".join(status_clauses) + ") OR so.id = %s)")
                drawer_params.append(int(current_order_id))
            else:
                drawer_where.append("(" + " OR ".join(status_clauses) + ")")

    # Exclude phantom empty orders with no customer and 0 total
    drawer_where.append("NOT (so.customer_id IS NULL AND so.total_amount = 0)")

    if status_filter and status_filter.strip().lower() in ('all', 'all orders'):
        drawer_limit = 1000
    elif status_filter and status_filter.strip().lower() in ('open', 'unfulfilled'):
        drawer_limit = 500
    elif search_query:
        drawer_limit = 300
    else:
        drawer_limit = 500

    drawer_sql = f"""
        SELECT 
            so.id, 
            so.order_number, 
            so.order_date, 
            CASE 
                WHEN UPPER(so.status) = 'CANCELLED' THEN 'Cancelled'
                WHEN UPPER(so.status) = 'QUOTE' THEN 'Quote'
                WHEN UPPER(so.status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS') THEN 'Open'
                WHEN UPPER(so.status) IN ('SHIPPED', 'INVOICED', 'PAID') OR UPPER(so.payment_status) = 'PAID' THEN 'Paid'
                ELSE 'Open'
            END as fulfillment_badge,
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
        LIMIT {drawer_limit}
    """
    sidebar_orders = query_all(drawer_sql, tuple(drawer_params))

    # Ensure current_order_id is never excluded from sidebar_orders while viewing it
    if current_order_id and not any(o['id'] == int(current_order_id) for o in sidebar_orders):
        single_sql = f"""
            SELECT 
                so.id, 
                so.order_number, 
                so.order_date, 
                CASE 
                    WHEN UPPER(so.status) = 'CANCELLED' THEN 'Cancelled'
                    WHEN UPPER(so.status) = 'QUOTE' THEN 'Quote'
                    WHEN UPPER(so.status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS') THEN 'Open'
                    WHEN UPPER(so.status) IN ('SHIPPED', 'INVOICED', 'PAID') OR UPPER(so.payment_status) = 'PAID' THEN 'Paid'
                    ELSE 'Open'
                END as fulfillment_badge,
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
            WHERE so.id = %s
        """
        single_order = query_one(single_sql, (int(current_order_id),))
        if single_order:
            sidebar_orders.insert(0, single_order)
            sidebar_orders.sort(key=lambda x: x['id'], reverse=True)

    # Pre-aggregate items sold preview for instant hover preview ("when mouse over order it will preview total items sell")
    preview_map = {}
    if sidebar_orders:
        s_ids = [o['id'] for o in sidebar_orders]
        try:
            lines_summary = query_all("""
                SELECT 
                    sol.sales_order_id,
                    COUNT(sol.id) as line_count,
                    COALESCE(SUM(COALESCE(sol.quantity_display, sol.quantity, 0)), 0) as total_qty,
                    json_agg(
                        json_build_object(
                            'name', p.name,
                            'sku', COALESCE(p.sku, ''),
                            'qty', COALESCE(sol.quantity_display, sol.quantity, 1),
                            'uom', COALESCE(sol.uom, p.uom, 'pcs.'),
                            'price', COALESCE(sol.unit_price, 0),
                            'subtotal', COALESCE(sol.subtotal, 0)
                        ) ORDER BY sol.line_num ASC
                    ) as items
                FROM sales_order_lines sol
                JOIN products p ON sol.product_id = p.id
                WHERE sol.sales_order_id = ANY(%s)
                GROUP BY sol.sales_order_id
            """, (s_ids,))
            summary_map = {row['sales_order_id']: row for row in lines_summary}
            for o in sidebar_orders:
                oid = o['id']
                sdata = summary_map.get(oid)
                if sdata:
                    t_items = int(sdata.get('line_count') or 0)
                    t_qty = float(sdata.get('total_qty') or 0)
                    items_list = sdata.get('items') or []
                else:
                    t_items = 0
                    t_qty = 0.0
                    items_list = []
                o['total_items'] = t_items
                o['total_qty'] = t_qty
                o['items_preview'] = items_list
                preview_map[oid] = {
                    'id': oid,
                    'order_number': o.get('order_number') or '',
                    'order_date': str(o.get('order_date') or ''),
                    'customer_name': o.get('customer_name') or 'No Customer',
                    'status': o.get('status') or 'Open',
                    'fulfillment_badge': o.get('fulfillment_badge') or 'Open',
                    'delivery_man': o.get('delivery_man') or '',
                    'total_amount': float(o.get('total_amount') or 0),
                    'total_items': t_items,
                    'total_qty': t_qty,
                    'items': items_list
                }
        except Exception as e:
            logger.warning(f"Error querying lines summary for sidebar preview: {e}")

    # Branch scope where condition for status counts
    branch_count_where = ["NOT (so.customer_id IS NULL AND so.total_amount = 0)"]
    branch_count_params = []
    if not is_main:
        if user_bid:
            branch_count_where.append("so.branch_id = %s")
            branch_count_params.append(user_bid)
        else:
            branch_count_where.append("1=0")
    else:
        if branch_id and str(branch_id).lower() != 'all':
            if str(branch_id).lower() == 'main':
                branch_count_where.append("so.branch_id IS NULL")
            elif str(branch_id).isdigit():
                branch_count_where.append("so.branch_id = %s")
                branch_count_params.append(int(branch_id))

    raw_counts = query_one(f"""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE UPPER(so.status) IN ('OPEN', 'PICKED', 'PACKED', 'IN_PROGRESS')) as open,
            COUNT(*) FILTER (WHERE UPPER(so.status) IN ('SHIPPED', 'INVOICED', 'PAID') OR UPPER(so.payment_status) = 'PAID') as paid,
            COUNT(*) FILTER (WHERE UPPER(so.status) = 'CANCELLED') as cancelled,
            COUNT(*) FILTER (WHERE UPPER(so.status) = 'QUOTE') as quote
        FROM sales_orders so
        WHERE {' AND '.join(branch_count_where)}
    """, tuple(branch_count_params))
    status_counts = dict(raw_counts) if raw_counts else {'total': 0, 'open': 0, 'paid': 0, 'cancelled': 0, 'quote': 0}

    cust_where = ["is_active = TRUE"]
    cust_params = []
    effective_bid = None
    if not is_main:
        effective_bid = user_bid
    elif branch_id and str(branch_id).lower() not in ('all', ''):
        if str(branch_id).lower() == 'main':
            effective_bid = 'main'
        elif str(branch_id).isdigit():
            effective_bid = int(branch_id)
    elif session.get('active_branch_id'):
        effective_bid = int(session.get('active_branch_id'))

    if effective_bid is not None:
        if effective_bid == 'main':
            cust_where.append("branch_id IS NULL")
        else:
            cust_where.append("branch_id = %s")
            cust_params.append(effective_bid)
    elif is_main and branch_id == 'all':
        # Viewing all branches
        pass
    else:
        # Default to Main Store (HQ)
        cust_where.append("branch_id IS NULL")

    all_customers = query_all(f"""
        SELECT 
            id, name, contact_name, phone, branch_id,
            COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as customer_address,
            COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as address1,
            balance 
        FROM customers 
        WHERE {' AND '.join(cust_where)}
        ORDER BY name ASC
    """, tuple(cust_params))
    all_locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
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
            COALESCE(p.combine_type, 'single') as combine_type,
            COALESCE(p.image_url, '') as image_url,
            COALESCE(p.uom, 'pcs.') as uom,
            COALESCE(p.sales_uom, '') as sales_uom,
            COALESCE(p.sales_uom_ratio_std, 1.0) as sales_uom_ratio_std,
            COALESCE(p.purchasing_uom, '') as purchasing_uom,
            COALESCE(p.purchasing_uom_ratio_std, 1.0) as purchasing_uom_ratio_std,
            COALESCE(c.name, 'GENERAL') as category_name,
            COALESCE(pp.unit_price, p.default_price, 0) as price,
            p.price_decimals,
            COALESCE(p.costing_sheet_cost, p.standard_cost, p.average_cost, p.last_purchase_cost, 0) as cost,
            COALESCE(inv.stock_on_hand, 0) as stock_on_hand,
            COALESCE(inv.stock_reserved, 0) as stock_reserved,
            COALESCE(po_ord.stock_on_order, 0) as stock_on_order
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN product_prices pp ON p.id = pp.product_id AND pp.pricing_scheme_id = %s
        LEFT JOIN (
            SELECT product_id,
                   SUM(quantity) as stock_on_hand,
                   SUM(reserved_quantity) as stock_reserved
            FROM inventory
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        LEFT JOIN (
            SELECT pol.product_id,
                   SUM(pol.quantity - COALESCE(pol.received_qty, 0)) as stock_on_order
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            WHERE po.status NOT IN ('RECEIVED', 'CANCELLED', 'CLOSED')
              AND COALESCE(pol.received_qty, 0) < pol.quantity
            GROUP BY pol.product_id
        ) po_ord ON p.id = po_ord.product_id
        WHERE p.is_active = TRUE
        ORDER BY p.sku ASC
    """, (scheme_id,))

    components_map = _get_product_components_map()
    for p in all_products:
        pid = p['id']
        comps = components_map.get(pid, [])
        p['components'] = comps
        if comps:
            p['is_kit'] = True
            min_buildable = 999999999
            for c in comps:
                c_qty = float(c.get('quantity') or 1.0)
                c_avail = max(0.0, float(c.get('stock_available') or 0.0))
                b = int(c_avail // c_qty) if c_qty > 0 else 0
                if b < min_buildable:
                    min_buildable = b
            p['max_kits_buildable'] = max(0, min_buildable) if min_buildable != 999999999 else 0
        else:
            p['is_kit'] = False
            p['max_kits_buildable'] = 0

    company = query_one("SELECT * FROM companies LIMIT 1")
    if is_main:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")
    else:
        all_branches = query_all("SELECT id, code, name FROM branches WHERE id = %s", (user_bid,))
    all_delivery_men = query_all("SELECT id, name, phone FROM delivery_men WHERE is_active = TRUE ORDER BY name ASC")
    all_users = query_all("SELECT id, username, display_name FROM users WHERE is_active = TRUE ORDER BY username ASC")

    return {
        'sidebar_orders': sidebar_orders,
        'status_counts': status_counts,
        'active_delivery_man': delivery_man_filter,
        'search_query': search_query,
        'all_customers': all_customers,
        'all_locations': all_locations,
        'pricing_schemes': pricing_schemes,
        'all_products': all_products,
        'components_map': components_map,
        'product_prices_map': product_prices_map,
        'company': company,
        'all_branches': all_branches,
        'all_delivery_men': all_delivery_men,
        'all_users': all_users,
        'preview_map': preview_map,
        'active_branch_filter': branch_id or ('all' if is_main else 'main')
    }

def _find_upper_or_adjacent_order(current_id, date_filter='All', status_filter='Open, In Progress, Paid', customer_search='', branch_id=None, requested_upper_id=None, search_query=''):
    """
    Finds the upper (order immediately above current_id in the drawer list) or adjacent order
    so that when deleting or completing an SO, the view stays on the detail page and moves to the upper order.
    """
    # 1. If explicit upper_id was passed from frontend DOM
    if requested_upper_id:
        try:
            req_id = int(requested_upper_id)
            if req_id != current_id:
                chk = query_one("SELECT id FROM sales_orders WHERE id = %s", (req_id,))
                if chk:
                    return chk['id']
        except (ValueError, TypeError):
            pass

    # 2. Query drawer list with exact current filter settings
    try:
        drawer_data = _get_drawer_and_metadata(
            date_filter=date_filter,
            status_filter=status_filter,
            customer_search=customer_search,
            customer_filter=None,
            scheme_id=100,
            branch_id=branch_id,
            search_query=search_query
        )
        sidebar_orders = drawer_data.get('sidebar_orders', [])
        order_ids = [o['id'] for o in sidebar_orders]

        if current_id in order_ids:
            idx = order_ids.index(current_id)
            # Move up to upper order if one exists above
            if idx > 0:
                return order_ids[idx - 1]
            # If current is top-most order, move down to next order below
            if len(order_ids) > 1:
                return order_ids[1]
        elif order_ids:
            # Current id wasn't in list (e.g., status filter already excluded it, such as completing an Open order)
            # Find the nearest order immediately above current_id instead of defaulting to top order
            current_order = query_one("SELECT id, order_date, order_number FROM sales_orders WHERE id = %s", (current_id,))
            if current_order:
                cur_date = current_order.get('order_date')
                # sidebar_orders is sorted by (order_date DESC, id DESC)
                # Find the nearest order above current_order:
                # order_date > cur_date OR (order_date == cur_date and id > current_id)
                nearest_above = None
                nearest_below = None
                for ord_item in sidebar_orders:
                    oid = ord_item['id']
                    odate = ord_item.get('order_date')
                    is_above = False
                    if odate and cur_date:
                        if odate > cur_date:
                            is_above = True
                        elif odate == cur_date and oid > current_id:
                            is_above = True
                    elif oid > current_id:
                        is_above = True

                    if is_above:
                        # In DESC sorted list, the last matching item is nearest above
                        nearest_above = oid
                    elif not is_above and nearest_below is None:
                        # The first non-matching item is nearest below
                        nearest_below = oid

                if nearest_above:
                    return nearest_above
                if nearest_below:
                    return nearest_below

            for oid in order_ids:
                if oid != current_id:
                    return oid
    except Exception as e:
        logger.warning(f"Error finding upper order via drawer metadata: {e}")

    # 3. Database-level fallback: Find upper order (id > current_id in same branch scope)
    try:
        is_main = _is_main_admin()
        user_bid = _get_user_branch_id()
        where_clauses = ["id != %s"]
        params = [current_id]

        if not is_main:
            if user_bid:
                where_clauses.append("branch_id = %s")
                params.append(user_bid)
            else:
                where_clauses.append("branch_id IS NULL")
        else:
            if branch_id is None or str(branch_id).lower() == 'main':
                where_clauses.append("branch_id IS NULL")
            elif str(branch_id).lower() == 'all':
                pass
            else:
                try:
                    where_clauses.append("branch_id = %s")
                    params.append(int(branch_id))
                except (ValueError, TypeError):
                    where_clauses.append("branch_id IS NULL")

        where_sql = " AND ".join(where_clauses)

        # Upper order in DESC list is the next higher ID (id > current_id ORDER BY id ASC)
        upper = query_one(f"SELECT id FROM sales_orders WHERE {where_sql} AND id > %s ORDER BY id ASC LIMIT 1", tuple(params + [current_id]))
        if upper:
            return upper['id']

        # Next order below in DESC list is the next lower ID (id < current_id ORDER BY id DESC)
        lower = query_one(f"SELECT id FROM sales_orders WHERE {where_sql} AND id < %s ORDER BY id DESC LIMIT 1", tuple(params + [current_id]))
        if lower:
            return lower['id']

        # Any remaining order
        any_ord = query_one(f"SELECT id FROM sales_orders WHERE {where_sql} ORDER BY id DESC LIMIT 1", tuple(params))
        if any_ord:
            return any_ord['id']
    except Exception as e:
        logger.warning(f"Database fallback error finding upper order: {e}")

    return None

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

@sales_orders_bp.route('/api/sales/preview-order-number')
def api_preview_order_number():
    raw_b = request.args.get('branch_id')
    bid = None
    if raw_b and str(raw_b).strip().isdigit():
        bid = int(raw_b)
    order_num = preview_order_number('SO', branch_id=bid)
    return jsonify({'order_number': order_num})

@sales_orders_bp.route('/sales/new')
def new_order():
    is_main = _is_main_admin()
    user_bid = _get_user_branch_id()

    # Resolve active branch context
    branch_param = request.args.get('branch') or session.get('active_branch_id')
    if not is_main:
        branch_id = user_bid
        if not branch_param and user_bid:
            branch_param = str(user_bid)
    else:
        branch_id = None
        if branch_param:
            if str(branch_param).lower() not in ('main', 'all', 'none', '', 'hq', '0') and str(branch_param).isdigit():
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
    source_order = None
    submission_token = uuid.uuid4().hex

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
            # When copying SO, do not include system previous bill date or copy metadata in remark
            cleaned_lines = [
                line for line in raw_notes.splitlines()
                if not re.match(r'^\s*previous\s+bill\s+date\s*:', line, re.IGNORECASE)
                and not re.match(r'^\s*copied\s+from\s+so-\d+', line, re.IGNORECASE)
            ]
            order['notes'] = "\n".join(cleaned_lines).strip()

            lines = query_all("""
                SELECT 
                    sol.*,
                    COALESCE(sol.pricing_scheme_id, so.pricing_scheme_id, 100) as pricing_scheme_id,
                    p.name as product_name,
                    p.sku as product_sku,
                    COALESCE(p.image_url, '') as product_image_url,
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
                    COALESCE(sol.description, p.description, '') as description,
                    addon_p.name as addon_product_name,
                    addon_p.sku as addon_product_sku,
                    addon_p.default_price as addon_default_price,
                    pco.option_name as combine_option_name
                FROM sales_order_lines sol
                JOIN products p ON sol.product_id = p.id
                LEFT JOIN sales_orders so ON sol.sales_order_id = so.id
                LEFT JOIN (
                    SELECT product_id, location_id,
                           SUM(quantity) as quantity,
                           SUM(reserved_quantity) as reserved_quantity
                    FROM inventory
                    GROUP BY product_id, location_id
                ) inv ON p.id = inv.product_id AND inv.location_id = %s
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
                'sales_rep': (session.get('username') or ''),
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
            'sales_rep': (session.get('username') or ''),
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
                   COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as display_address
            FROM customers WHERE id = %s
        """, (int(target_cust_id),))
        if cust_row:
            cust_bid = cust_row.get('branch_id')
            order_bid = order.get('branch_id')
            if cust_bid == order_bid:
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
        date_filter = request.args.get('date_filter') or 'All'
        session['so_date_filter'] = date_filter
    elif 'so_date_filter' in session and session.get('so_date_filter'):
        date_filter = session['so_date_filter']
    else:
        date_filter = 'All'

    if 'status_filter' in request.args:
        status_filter = request.args.get('status_filter', 'Open').strip()
        session['so_status_filter'] = status_filter
    elif 'so_status_filter' in session and session.get('so_status_filter'):
        status_filter = session['so_status_filter']
    else:
        status_filter = 'Open'

    curr_user = (session.get('username') or '').strip().lower()
    if 'search' in request.args:
        search_query = request.args.get('search', '').strip()
        if search_query and search_query.lower() != curr_user:
            session['so_search_query'] = search_query
        else:
            session.pop('so_search_query', None)
            search_query = ''
    elif 'q' in request.args:
        search_query = request.args.get('q', '').strip()
        if search_query and search_query.lower() != curr_user:
            session['so_search_query'] = search_query
        else:
            session.pop('so_search_query', None)
            search_query = ''
    elif 'so_search_query' in session and session.get('so_search_query'):
        search_query = session['so_search_query'].strip()
        if curr_user and search_query.lower() == curr_user:
            session.pop('so_search_query', None)
            search_query = ''
    else:
        search_query = ''

    if 'customer_search' in request.args and request.args.get('customer_search'):
        customer_search = request.args.get('customer_search', '').strip()
    else:
        customer_search = ''
        session.pop('so_customer_search', None)

    # customer_id is used above to pre-fill order customer; do NOT filter sidebar orders list
    customer_filter = None

    if not is_main:
        req_branch = str(user_bid or -1)
    elif branch:
        req_branch = str(branch['id'])
    elif session.get('active_branch_id'):
        req_branch = str(session.get('active_branch_id'))
    elif 'branch' in request.args and request.args.get('branch'):
        b_arg = request.args.get('branch').strip().lower()
        if b_arg in ('all', 'main') or b_arg.isdigit():
            req_branch = b_arg
        else:
            req_branch = 'main'
    else:
        req_branch = 'main'
    scheme_id = order.get('pricing_scheme_id') or 100
    drawer_data = _get_drawer_and_metadata(date_filter, status_filter, customer_search, customer_filter, scheme_id=scheme_id, branch_id=req_branch, search_query=search_query)

    components_map = drawer_data.get('components_map') or _get_product_components_map()
    for l in lines:
        pid = l['product_id']
        comps = components_map.get(pid, [])
        l['components'] = comps
        if comps:
            min_buildable = 999999999
            for c in comps:
                c_qty = float(c.get('quantity') or 1.0)
                c_avail = max(0.0, float(c.get('stock_available') or 0.0))
                b = int(c_avail // c_qty) if c_qty > 0 else 0
                if b < min_buildable:
                    min_buildable = b
            max_kits = max(0, min_buildable) if min_buildable != 999999999 else 0
            l['max_kits_buildable'] = max_kits
            l['is_backordered'] = (float(max_kits) < float(l.get('quantity') or 0))
        else:
            l['max_kits_buildable'] = 0
            l['is_backordered'] = (float(l.get('stock_on_hand') or 0) < float(l.get('quantity') or 0))
        ps_id = l.get('pricing_scheme_id') or scheme_id or 100
        l['case_price'] = drawer_data['product_prices_map'].get(pid, {}).get(ps_id, float(l['unit_price'] or 0))

    preview_so_number = preview_order_number('SO', branch_id=branch['id'] if branch else None)

    return render_template('sales/detail.html',
                           order=order,
                           lines=lines,
                           sidebar_orders=drawer_data['sidebar_orders'],
                           preview_map=drawer_data.get('preview_map', {}),
                           status_counts=drawer_data.get('status_counts', {}),
                           active_delivery_man=drawer_data.get('active_delivery_man', ''),
                           search_query=drawer_data.get('search_query', ''),
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
                           all_users=drawer_data.get('all_users', []),
                           order_payment_method='ABA Bank',
                           payments=[],
                           company=drawer_data['company'],
                           is_paid=False,
                           is_new=True,
                           is_copied_draft=is_copied_draft,
                           current_branch=branch,
                           is_branch_order=bool(branch),
                           attachments=[],
                           versions=[],
                           preview_so_number=preview_so_number,
                           submission_token=submission_token)

def _get_order_attachments_and_versions(order_id):
    _ensure_so_tables_exist()
    raw_attachments = query_all("""
        SELECT id, sales_order_id, file_name, file_path, file_size, file_type, caption, uploaded_by,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM sales_order_attachments
        WHERE sales_order_id = %s
        ORDER BY created_at DESC, id DESC
    """, (order_id,))
    attachments = []
    for a in raw_attachments:
        d = dict(a)
        d['original_name'] = d.get('file_name')
        d['file_url'] = d.get('file_path')
        d['mime_type'] = d.get('file_type')
        ftype = (d.get('file_type') or '').lower()
        fname = (d.get('file_name') or '').lower()
        if ftype.startswith('image/') or fname.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            d['file_category'] = 'image'
        elif 'pdf' in ftype or fname.endswith('.pdf'):
            d['file_category'] = 'pdf'
        else:
            d['file_category'] = 'file'
        attachments.append(d)

    raw_versions = query_all("""
        SELECT id, sales_order_id, version_number, order_number, status, payment_status,
               customer_name, total_amount, paid_amount, balance_due, items_count,
               user_name, change_summary,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM sales_order_versions
        WHERE sales_order_id = %s
        ORDER BY version_number DESC, created_at DESC
    """, (order_id,))

    if not raw_versions:
        _record_order_version(order_id, change_summary="Base Version (v1)")
        raw_versions = query_all("""
            SELECT id, sales_order_id, version_number, order_number, status, payment_status,
                   customer_name, total_amount, paid_amount, balance_due, items_count,
                   user_name, change_summary,
                   TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
            FROM sales_order_versions
            WHERE sales_order_id = %s
            ORDER BY version_number DESC, created_at DESC
        """, (order_id,))

    versions = []
    for v in raw_versions:
        vd = dict(v)
        vd['created_by'] = vd.get('user_name') or 'admin'
        vd['order_status'] = vd.get('status') or 'UNFULFILLED'
        versions.append(vd)

    return attachments, versions

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

    is_partial = (
        request.headers.get('X-Inflow-Partial') == 'canvas' or
        request.args.get('partial') in ('canvas', '1', 'true')
    )

    if not order:
        if is_partial:
            return ("<div class='inflow-error-banner' style='padding:20px;color:#DC2626;'>Order not found.</div>", 404)
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    if not _check_order_branch_access(order):
        if is_partial:
            return ("<div class='inflow-error-banner' style='padding:20px;color:#DC2626;'>Access denied to this store order.</div>", 403)
        flash("You do not have permission to view orders from another store or Main Store. / អ្នកមិនមានសិទ្ធិមើលការបញ្ជាទិញរបស់សាខាផ្សេង ឬហាងធំទេ", "warning")
        user_bid = _get_user_branch_id()
        if user_bid:
            return redirect(url_for('sales_orders.list_orders', status='PAID', branch=user_bid))
    order = dict(order)
    # Ensure biller name shows only login name (username)
    raw_rep = (order.get('sales_rep') or order.get('completed_by') or '').strip()
    if raw_rep:
        u_match = query_one("SELECT username FROM users WHERE display_name = %s OR username = %s LIMIT 1", (raw_rep, raw_rep))
        if u_match and u_match.get('username'):
            order['sales_rep'] = u_match['username']
        else:
            order['sales_rep'] = raw_rep

    if 'date_filter' in request.args:
        date_filter = request.args.get('date_filter') or 'All'
        session['so_date_filter'] = date_filter
    elif 'so_date_filter' in session and session.get('so_date_filter'):
        date_filter = session['so_date_filter']
    else:
        date_filter = 'All'

    if 'status_filter' in request.args:
        status_filter = request.args.get('status_filter', 'Open').strip()
        session['so_status_filter'] = status_filter
    elif 'so_status_filter' in session and session.get('so_status_filter'):
        status_filter = session['so_status_filter']
    else:
        status_filter = 'Open'

    curr_user = (session.get('username') or '').strip().lower()
    if 'search' in request.args:
        search_query = request.args.get('search', '').strip()
        if search_query and search_query.lower() != curr_user:
            session['so_search_query'] = search_query
        else:
            session.pop('so_search_query', None)
            search_query = ''
    elif 'q' in request.args:
        search_query = request.args.get('q', '').strip()
        if search_query and search_query.lower() != curr_user:
            session['so_search_query'] = search_query
        else:
            session.pop('so_search_query', None)
            search_query = ''
    else:
        # Check session search query if previously set
        search_query = (session.get('so_search_query') or '').strip()
        if curr_user and search_query.lower() == curr_user:
            session.pop('so_search_query', None)
            search_query = ''

    if 'customer_search' in request.args and request.args.get('customer_search'):
        customer_search = request.args.get('customer_search', '').strip()
    else:
        customer_search = ''
        session.pop('so_customer_search', None)

    # Do not auto filter sidebar orders to only customer of selected bill
    customer_filter = None
    submission_token = uuid.uuid4().hex

    lines = query_all("""
        SELECT 
            sol.*,
            COALESCE(sol.pricing_scheme_id, so.pricing_scheme_id, 100) as pricing_scheme_id,
            p.name as product_name,
            p.sku as product_sku,
            COALESCE(p.image_url, '') as product_image_url,
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
            COALESCE(sol.description, p.description, '') as description,
            addon_p.name as addon_product_name,
            addon_p.sku as addon_product_sku,
            addon_p.default_price as addon_default_price,
            pco.option_name as combine_option_name
        FROM sales_order_lines sol
        JOIN products p ON sol.product_id = p.id
        LEFT JOIN sales_orders so ON sol.sales_order_id = so.id
        LEFT JOIN (
            SELECT product_id, location_id,
                   SUM(quantity) as quantity,
                   SUM(reserved_quantity) as reserved_quantity
            FROM inventory
            GROUP BY product_id, location_id
        ) inv ON p.id = inv.product_id AND inv.location_id = %s
        LEFT JOIN products addon_p ON sol.addon_product_id = addon_p.id
        LEFT JOIN product_combine_options pco ON sol.combine_option_id = pco.id
        WHERE sol.sales_order_id = %s
        ORDER BY sol.line_num ASC
    """, (order.get('location_id') or 100, id))

    if is_partial:
        # Fast partial response: avoids running heavy drawer queries for 500 orders and customer/product catalogs (~15ms)
        all_branches = query_all("SELECT id, name, code FROM branches ORDER BY name ASC")
        all_locations = query_all("SELECT id, name, is_default FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
        pricing_schemes = query_all("SELECT id, name FROM pricing_schemes ORDER BY id ASC")
        all_delivery_men = query_all("SELECT * FROM delivery_men ORDER BY name ASC")
        company = query_one("SELECT * FROM companies LIMIT 1") or {}

        scheme_id = order.get('pricing_scheme_id') or 100
        components_map = _get_product_components_map()
        for l in lines:
            pid = l['product_id']
            comps = components_map.get(pid, [])
            l['components'] = comps
            if comps:
                min_buildable = 999999999
                for c in comps:
                    c_qty = float(c.get('quantity') or 1.0)
                    c_avail = max(0.0, float(c.get('stock_available') or 0.0))
                    b = int(c_avail // c_qty) if c_qty > 0 else 0
                    if b < min_buildable:
                        min_buildable = b
                max_kits = max(0, min_buildable) if min_buildable != 999999999 else 0
                l['max_kits_buildable'] = max_kits
                l['is_backordered'] = (float(max_kits) < float(l.get('quantity') or 0))
            else:
                l['max_kits_buildable'] = 0
                l['is_backordered'] = (float(l.get('stock_on_hand') or 0) < float(l.get('quantity') or 0))
            l['case_price'] = float(l.get('unit_price') or 0)
            suom = (l.get('sales_uom') or '').strip()
            curr_uom = (l.get('display_uom') or '').strip()
            if not curr_uom:
                l['display_uom'] = l.get('base_uom') or 'pcs.'
            elif suom and _match_uom(curr_uom, suom):
                l['display_uom'] = suom

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
        order_payment_method = (order.get('payment_method') or (payments[0]['payment_method'] if payments else '') or 'ABA Bank').strip()

        attachments, versions = _get_order_attachments_and_versions(id)
        branch_scope = request.args.get('branch') or (str(order['branch_id']) if order.get('branch_id') else 'main')

        ord_bid = order.get('branch_id')
        if ord_bid:
            partial_custs = query_all("""
                SELECT id, name, contact_name, phone, branch_id,
                       COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as customer_address,
                       COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as address1,
                       balance 
                FROM customers 
                WHERE is_active = TRUE AND branch_id = %s
                ORDER BY name ASC
            """, (ord_bid,))
        else:
            partial_custs = query_all("""
                SELECT id, name, contact_name, phone, branch_id,
                       COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as customer_address,
                       COALESCE(NULLIF(address1, ''), NULLIF(shipping_address, ''), '') as address1,
                       balance 
                FROM customers 
                WHERE is_active = TRUE AND branch_id IS NULL
                ORDER BY name ASC
            """)

        return render_template('sales/_detail_canvas.html',
                               order=order,
                               lines=lines,
                               all_branches=all_branches,
                               all_locations=all_locations,
                               pricing_schemes=pricing_schemes,
                               all_delivery_men=all_delivery_men,
                               all_users=query_all("SELECT id, username, display_name FROM users WHERE is_active = TRUE ORDER BY username ASC"),
                               all_customers=partial_custs,
                               all_products=[],
                               company=company,
                               payments=payments,
                               attachments=attachments,
                               versions=versions,
                               branch_scope=branch_scope,
                               current_branch=branch_obj,
                               is_branch_order=bool(branch_obj),
                               order_payment_method=order_payment_method,
                               is_paid=is_paid,
                               status_filter=status_filter,
                               date_filter=date_filter,
                               search_query=search_query,
                               is_new=False,
                               submission_token=submission_token)

    is_main = _is_main_admin()
    user_bid = _get_user_branch_id()

    # Allow user to switch branch filter in drawer or default to the order's branch scope
    if not is_main:
        branch_scope = str(user_bid or order.get('branch_id') or -1)
    else:
        raw_b = request.args.get('branch')
        if raw_b and raw_b.strip().lower() in ('all', 'main'):
            branch_scope = raw_b.strip().lower()
        elif raw_b and raw_b.strip().isdigit():
            branch_scope = raw_b.strip()
        elif order.get('branch_id'):
            # When viewing a branch order, strictly scope drawer to that branch!
            branch_scope = str(order['branch_id'])
        else:
            # HQ order (branch_id IS NULL)
            branch_scope = 'main'

    scheme_id = order.get('pricing_scheme_id') or 100
    drawer_data = _get_drawer_and_metadata(date_filter, status_filter, customer_search, customer_filter, scheme_id=scheme_id, branch_id=branch_scope, search_query=search_query, current_order_id=id)

    # Mark backorder flag if stock is insufficient and resolve case price / display UOM
    components_map = drawer_data.get('components_map') or _get_product_components_map()
    for l in lines:
        pid = l['product_id']
        comps = components_map.get(pid, [])
        l['components'] = comps
        if comps:
            min_buildable = 999999999
            for c in comps:
                c_qty = float(c.get('quantity') or 1.0)
                c_avail = max(0.0, float(c.get('stock_available') or 0.0))
                b = int(c_avail // c_qty) if c_qty > 0 else 0
                if b < min_buildable:
                    min_buildable = b
            max_kits = max(0, min_buildable) if min_buildable != 999999999 else 0
            l['max_kits_buildable'] = max_kits
            l['is_backordered'] = (float(max_kits) < float(l.get('quantity') or 0))
        else:
            l['max_kits_buildable'] = 0
            l['is_backordered'] = (float(l.get('stock_on_hand') or 0) < float(l.get('quantity') or 0))
        ps_id = l.get('pricing_scheme_id') or scheme_id or 100
        l['case_price'] = drawer_data['product_prices_map'].get(pid, {}).get(ps_id, float(l['unit_price'] or 0))

        suom = (l.get('sales_uom') or '').strip()
        curr_uom = (l.get('display_uom') or '').strip()
        if not curr_uom:
            l['display_uom'] = l.get('base_uom') or 'pcs.'
        elif suom and _match_uom(curr_uom, suom):
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
    order_payment_method = (order.get('payment_method') or (payments[0]['payment_method'] if payments else '') or 'ABA Bank').strip()

    # Load attachments & versions for this sales order
    attachments, versions = _get_order_attachments_and_versions(id)

    return render_template('sales/detail.html',
                           order=order,
                           lines=lines,
                           sidebar_orders=drawer_data['sidebar_orders'],
                           preview_map=drawer_data.get('preview_map', {}),
                           status_counts=drawer_data.get('status_counts', {}),
                           active_delivery_man=drawer_data.get('active_delivery_man', ''),
                           search_query=drawer_data.get('search_query', ''),
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
                           all_users=drawer_data.get('all_users', []),
                           order_payment_method=order_payment_method,
                           company=drawer_data['company'],
                           payments=payments,
                           is_paid=is_paid,
                           is_new=False,
                           attachments=attachments,
                           versions=versions,
                           current_branch=branch_obj,
                           is_branch_order=bool(branch_obj),
                           submission_token=submission_token)

@sales_orders_bp.route('/sales/api/preview_items/<int:id>')
def api_order_preview_items(id):
    order = query_one("""
        SELECT so.id, so.order_number, so.order_date, so.status, so.payment_status,
               so.total_amount, so.delivery_man, COALESCE(c.name, 'No Customer') as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.id = %s
    """, (id,))
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    lines = query_all("""
        SELECT 
            sol.id,
            sol.line_num,
            p.name,
            COALESCE(p.sku, '') as sku,
            COALESCE(sol.quantity_display, sol.quantity, 1) as qty,
            COALESCE(sol.uom, p.uom, 'pcs.') as uom,
            COALESCE(sol.unit_price, 0) as price,
            COALESCE(sol.subtotal, 0) as subtotal
        FROM sales_order_lines sol
        JOIN products p ON sol.product_id = p.id
        WHERE sol.sales_order_id = %s
        ORDER BY sol.line_num ASC
    """, (id,))

    items = [{
        'name': l['name'],
        'sku': l['sku'],
        'qty': float(l['qty'] or 0),
        'uom': l['uom'],
        'price': float(l['price'] or 0),
        'subtotal': float(l['subtotal'] or 0)
    } for l in lines]
    total_qty = sum(item['qty'] for item in items)

    st = order.get('status') or 'Open'
    pst = order.get('payment_status') or ''
    if str(st).upper() in ('SHIPPED', 'INVOICED', 'PAID') or str(pst).upper() == 'PAID':
        badge = 'Paid'
    elif str(st).upper() == 'CANCELLED':
        badge = 'Cancelled'
    elif str(st).upper() == 'QUOTE':
        badge = 'Quote'
    else:
        badge = 'Open'

    return jsonify({
        'id': order['id'],
        'order_number': order['order_number'],
        'order_date': str(order['order_date'] or ''),
        'customer_name': order['customer_name'],
        'status': st,
        'fulfillment_badge': badge,
        'delivery_man': order.get('delivery_man') or '',
        'total_amount': float(order['total_amount'] or 0),
        'total_items': len(items),
        'total_qty': total_qty,
        'items': items
    })

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
        if location_id:
            loc_valid = query_one("SELECT id FROM locations WHERE id = %s AND is_active = TRUE AND name NOT LIKE '<%%>'", (location_id,))
            if not loc_valid:
                def_loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1") or query_one("SELECT id FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' LIMIT 1")
                location_id = def_loc['id'] if def_loc else 100
        else:
            def_loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1") or query_one("SELECT id FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' LIMIT 1")
            location_id = def_loc['id'] if def_loc else 100
        
        raw_date = data.get('order_date')
        from datetime import date
        fallback_date = (order['order_date'] if order and order.get('order_date') else date.today())
        order_date = _parse_order_date(raw_date, default_date=fallback_date)

        sales_rep = (data.get('sales_rep') or (order['sales_rep'] if order else '') or '').strip()
        if is_new and not sales_rep:
            sales_rep = (session.get('username') or '').strip()
        elif sales_rep:
            u_match = query_one("SELECT username FROM users WHERE display_name = %s OR username = %s LIMIT 1", (sales_rep, sales_rep))
            if u_match and u_match.get('username'):
                sales_rep = u_match['username']
        
        # When notes are submitted, use submitted value (allowing empty string to delete notes!)
        if 'notes' in data:
            notes = str(data.get('notes') or '').strip()
        else:
            notes = (order.get('notes') if order else '') or ''

        # When change date of the bill the previous date must add to remark (ONLY for existing orders)
        if not is_new and order and order.get('order_date'):
            old_date = order['order_date']
            if old_date and order_date and old_date != order_date:
                old_date_str = old_date.strftime('%d-%b-%Y')
                date_note = f"Previous bill date: {old_date_str}"
                if date_note not in notes:
                    notes = f"{notes}\n{date_note}".strip() if notes else date_note
        elif is_new and notes:
            # Strip any accidental 'Previous bill date: ...' from new or copied orders
            import re
            cleaned_lines = [
                line for line in notes.splitlines()
                if not re.match(r'^\s*previous\s+bill\s+date\s*:', line, re.IGNORECASE)
            ]
            notes = "\n".join(cleaned_lines).strip()

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

        # Preserve existing order address/contact/phone if submitted values are blank
        if not customer_address and order and order.get('customer_address'):
            customer_address = str(order['customer_address']).strip()
        if not customer_contact and order and order.get('customer_contact'):
            customer_contact = str(order['customer_contact']).strip()
        if not customer_phone and order and order.get('customer_phone'):
            customer_phone = str(order['customer_phone']).strip()

        # Fallback to customer's saved address, contact, and phone if still blank
        if customer_id and (not customer_address or not customer_contact or not customer_phone):
            cust_fallback = query_one("""
                SELECT 
                    COALESCE(NULLIF(shipping_address, ''), NULLIF(address1, ''), NULLIF(billing_address, ''), NULLIF(address2, ''), '') as default_addr,
                    COALESCE(NULLIF(contact_name, ''), '') as default_contact,
                    COALESCE(NULLIF(phone, ''), '') as default_phone
                FROM customers WHERE id = %s
            """, (customer_id,))
            if cust_fallback:
                if not customer_address:
                    customer_address = (cust_fallback.get('default_addr') or '').strip()
                if not customer_contact:
                    customer_contact = (cust_fallback.get('default_contact') or '').strip()
                if not customer_phone:
                    customer_phone = (cust_fallback.get('default_phone') or '').strip()

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

        carrier = (str(data.get('carrier') or '').strip()) if 'carrier' in data else ((order.get('carrier') if order else '') or '')
        try:
            package_count = max(1, int(data.get('package_count') or (order.get('package_count') if order else 1) or 1))
        except (ValueError, TypeError):
            package_count = 1
        try:
            cod_amount = max(0.0, float(data.get('cod_amount') if data.get('cod_amount') is not None else ((order.get('cod_amount') if order else 0.0) or 0.0)))
        except (ValueError, TypeError):
            cod_amount = 0.0

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

        # Resolve branch context & enforce branch isolation
        is_main = _is_main_admin()
        user_bid = _get_user_branch_id()

        if not is_new:
            if not is_main:
                branch_id = order['branch_id']
                if not _check_order_branch_access(order):
                    if request.is_json:
                        return jsonify({'success': False, 'message': 'Access denied: Cannot edit order belonging to another branch.'}), 403
                    flash("Access denied: Cannot edit order belonging to another branch.", "error")
                    return redirect(url_for('sales_orders.list_orders'))
            else:
                raw_b = data.get('branch_id') if data.get('branch_id') is not None else request.form.get('branch_id')
                if raw_b is not None:
                    raw_str = str(raw_b).strip().lower()
                    if raw_str in ('main', 'none', '', 'hq', '0', 'null'):
                        branch_id = None
                    elif raw_str.isdigit():
                        branch_id = int(raw_str)
                    else:
                        branch_id = order.get('branch_id')
                else:
                    branch_id = order.get('branch_id')
        else:
            if not is_main:
                branch_id = user_bid
            else:
                raw_b = data.get('branch_id') or request.form.get('branch_id') or data.get('branch') or request.form.get('branch')
                if raw_b and str(raw_b).lower() not in ('main', 'all', 'none', '', 'hq', '0', 'null') and str(raw_b).isdigit():
                    branch_id = int(raw_b)
                elif session.get('active_branch_id'):
                    branch_id = int(session.get('active_branch_id'))
                else:
                    branch_id = None

        # Verify customer belongs to the target branch (prevent cross-branch customer assignment)
        # Keep HQ and Branch customers strictly independent!
        if customer_id:
            cust_check = query_one("SELECT branch_id FROM customers WHERE id = %s", (customer_id,))
            if cust_check:
                cust_bid = cust_check.get('branch_id')
                if cust_bid != branch_id:
                    msg = "Access denied: Selected customer belongs to another branch or HQ. Customers of HQ and Branch are kept independently."
                    if request.is_json:
                        return jsonify({'success': False, 'message': msg}), 403
                    flash(msg, "error")
                    return redirect(url_for('sales_orders.list_orders'))

        # Check for duplicate submission prevention (Idempotency token & rapid duplicate protection)
        form_sub_token = (data.get('form_submission_token') or data.get('submission_token') or
                          request.form.get('form_submission_token') or request.form.get('submission_token') or '').strip()

        if is_new:
            # Check 1: Idempotency token in persistent database & session
            if form_sub_token:
                existing_ord = query_one("SELECT id, order_number FROM sales_orders WHERE submission_token = %s", (form_sub_token,))
                if not existing_ord:
                    cached_order_id = session.get(f'so_sub_{form_sub_token}')
                    if cached_order_id:
                        existing_ord = query_one("SELECT id, order_number FROM sales_orders WHERE id = %s", (cached_order_id,))
                if existing_ord:
                    logger.info(f"Duplicate submission prevented via submission_token '{form_sub_token}'. Order {existing_ord['order_number']} (id={existing_ord['id']})")
                    target_id = existing_ord['id']
                    order_number = existing_ord['order_number']
                    redirect_kwargs = {
                        'id': target_id,
                        'branch': request.form.get('branch') or request.args.get('branch') or (str(branch_id) if branch_id else 'main'),
                        'date_filter': request.form.get('date_filter') or request.args.get('date_filter') or 'All',
                        'status_filter': request.form.get('status_filter') or request.args.get('status_filter') or 'Open, In Progress, Paid'
                    }
                    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)
                    if request.is_json:
                        return jsonify({'success': True, 'message': 'Saved successfully', 'order_id': target_id, 'order_number': order_number, 'redirect_url': redirect_url})
                    flash(f"Sales Order {order_number} saved successfully!", "success")
                    return redirect(redirect_url)

            # Check 2: Rapid deduplication guard (protects against concurrent requests within 60 seconds for same customer & branch)
            if customer_id:
                recent_order = query_one("""
                    SELECT id, order_number, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at)) as seconds_ago
                    FROM sales_orders
                    WHERE customer_id = %s
                      AND ((branch_id IS NULL AND %s IS NULL) OR branch_id = %s)
                      AND created_at >= (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
                    ORDER BY id DESC
                    LIMIT 1
                """, (customer_id, branch_id, branch_id))
                if recent_order:
                    recent_id = recent_order['id']
                    recent_lines = query_all("SELECT product_id, quantity, quantity_display FROM sales_order_lines WHERE sales_order_id = %s ORDER BY line_num", (recent_id,))
                    current_items = [(int(it.get('product_id')), float(it.get('quantity') or 1)) for it in (lines_data or []) if it.get('product_id')]
                    # In recent_lines, quantity_display is user display qty (e.g. 5 cases), while quantity is std pcs (2800)
                    recent_items_display = [(int(rl['product_id']), float(rl.get('quantity_display') or rl['quantity'] or 1)) for rl in recent_lines]
                    recent_items_std = [(int(rl['product_id']), float(rl['quantity'] or 1)) for rl in recent_lines]

                    is_match = False
                    if len(current_items) == 0 and len(recent_lines) == 0:
                        is_match = True
                    elif current_items == recent_items_display or current_items == recent_items_std:
                        is_match = True
                    elif len(current_items) == len(recent_lines) and sorted(current_items) == sorted(recent_items_display):
                        is_match = True
                    elif len(current_items) == len(recent_lines) and sorted(current_items) == sorted(recent_items_std):
                        is_match = True

                    if is_match:
                        logger.warning(f"Rapid duplicate sales order prevented for customer {customer_id} (within {recent_order.get('seconds_ago', 0):.1f}s). Returning existing order {recent_order['order_number']}")
                        target_id = recent_id
                        order_number = recent_order['order_number']
                        if form_sub_token:
                            session[f'so_sub_{form_sub_token}'] = target_id
                            session.modified = True
                            try:
                                execute("UPDATE sales_orders SET submission_token = %s WHERE id = %s AND (submission_token IS NULL OR submission_token = '')", (form_sub_token, target_id))
                            except Exception:
                                pass
                        redirect_kwargs = {
                            'id': target_id,
                            'branch': request.form.get('branch') or request.args.get('branch') or (str(branch_id) if branch_id else 'main'),
                            'date_filter': request.form.get('date_filter') or request.args.get('date_filter') or 'All',
                            'status_filter': request.form.get('status_filter') or request.args.get('status_filter') or 'Open, In Progress, Paid'
                        }
                        redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)
                        if request.is_json:
                            return jsonify({'success': True, 'message': 'Saved successfully', 'order_id': target_id, 'order_number': order_number, 'redirect_url': redirect_url})
                        flash(f"Sales Order {order_number} saved successfully!", "success")
                        return redirect(redirect_url)

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
                order_number = get_next_order_number('SO', branch_id=branch_id, cur=cur)

                cur.execute("""
                    INSERT INTO sales_orders (
                        order_number, customer_id, location_id, order_date,
                        status, payment_status, subtotal, tax_rate, tax_amount,
                        discount_amount, shipping_fee, total_amount, paid_amount, balance_due,
                        sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone,
                        branch_id, delivery_man, delivery_helper, delivery_fee_khr, delivery_notes, payment_method,
                        carrier, package_count, cod_amount, submission_token
                    ) VALUES (%s, %s, %s, %s, 'OPEN', 'UNPAID', 0, 0, 0, 0, 0, 0, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (order_number, customer_id, location_id, order_date, sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone, branch_id, delivery_man or None, delivery_helper or None, delivery_fee_khr, delivery_notes or None, payment_method or None, carrier or None, package_count, cod_amount, form_sub_token or None))
                id = cur.fetchone()['id']
                if form_sub_token:
                    session[f'so_sub_{form_sub_token}'] = id
                    session.modified = True
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
                        branch_id = %s,
                        carrier = COALESCE(NULLIF(%s, ''), carrier),
                        package_count = COALESCE(%s, package_count),
                        cod_amount = COALESCE(%s, cod_amount),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (customer_id, location_id, order_date, sales_rep, notes, pricing_scheme_id, customer_address, customer_contact, customer_phone, delivery_man or None, delivery_helper or None, delivery_fee_khr, delivery_notes or None, payment_method or None, branch_id, carrier or None, package_count, cod_amount, id))

            if customer_id:
                from database import sync_customers_from_latest_orders
                sync_customers_from_latest_orders(cur=cur, customer_ids=[customer_id])

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

                total_amount = subtotal
                if mark_complete_pay:
                    status = 'PAID'
                    payment_status = 'PAID'
                    paid_amount = total_amount
                    balance_due = 0.0
                    pay_method = payment_method or 'ABA Bank'
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

                    # Deduct physical inventory upon Complete & Pay
                    cur.execute("""
                        SELECT sol.product_id, sol.quantity, sol.addon_product_id, sol.addon_quantity,
                               p.name as product_name, ap.name as addon_name
                        FROM sales_order_lines sol
                        LEFT JOIN products p ON sol.product_id = p.id
                        LEFT JOIN products ap ON sol.addon_product_id = ap.id
                        WHERE sol.sales_order_id = %s
                    """, (id,))
                    so_lines = cur.fetchall()
                    order_ref = {'id': id, 'order_number': order_number, 'location_id': location_id}
                    for l in so_lines:
                        if l['product_id']:
                            qty = float(l['quantity'] or 0)
                            _deduct_order_stock(cur, order_ref, l['product_id'], qty, l.get('product_name'), "Fulfillment Complete & Pay")
                            if l.get('addon_product_id'):
                                a_qty = qty * float(l.get('addon_quantity') or 1.0)
                                _deduct_order_stock(cur, order_ref, l['addon_product_id'], a_qty, l.get('addon_name') or 'Add-on', "Fulfillment Add-on")
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

                # Synchronize live inventory reservations
                sync_inventory_reserved_quantities(cur=cur)

        # Record version snapshot
        try:
            current_status = (order.get('status') if order else 'Open') or 'Open'
            ver_action = "Order Created" if is_new else f"Saved Order (Status: {current_status}, Total: ${total_amount:,.2f})"
            _record_order_version(id, change_summary=ver_action)
        except Exception as ve:
            logger.warning(f"Failed to record version on save: {ve}")

        cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
        date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
        status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
        branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(branch_id) if branch_id else 'main')
        if 'search' in request.form:
            search_param = (request.form.get('search') or '').strip()
        elif 'search' in request.args:
            search_param = (request.args.get('search') or '').strip()
        elif 'so_search_query' in session and session.get('so_search_query'):
            search_param = session.get('so_search_query').strip()
        else:
            search_param = ''

        session['so_date_filter'] = date_filter
        session['so_status_filter'] = status_filter
        session['so_customer_search'] = cust_search
        session['so_branch_filter'] = branch_param
        if search_param:
            session['so_search_query'] = search_param
        elif 'search' in request.form or 'search' in request.args:
            session.pop('so_search_query', None)

        target_id = id

        redirect_kwargs = {
            'id': target_id,
            'branch': branch_param,
            'date_filter': date_filter,
            'status_filter': status_filter
        }
        if cust_search:
            redirect_kwargs['customer_search'] = cust_search
        if search_param:
            redirect_kwargs['search'] = search_param
        redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

        if request.is_json:
            return jsonify({'success': True, 'message': 'Saved successfully', 'order_id': id, 'order_number': order_number, 'redirect_url': redirect_url})
        if mark_complete_pay:
            user_login_name = session.get('username') or session.get('display_name') or 'admin'
            flash(f"Sales Order {order_number} marked Complete & Paid by {user_login_name}!", "success")
        else:
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
    if not _check_order_branch_access(order):
        if request.is_json:
            return jsonify({'success': False, 'message': 'Access denied: Order belongs to another branch.'}), 403
        flash("Access denied: Order belongs to another branch.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    data = request.get_json(silent=True) or request.form or {}
    payment_method = (data.get('payment_method') or order.get('payment_method') or 'ABA Bank').strip()
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
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(order.get('branch_id')) if order.get('branch_id') else 'main')
    search_param = request.form.get('search') or request.args.get('search') or session.get('so_search_query') or ''

    session['so_date_filter'] = date_filter
    session['so_status_filter'] = status_filter
    session['so_customer_search'] = cust_search
    session['so_branch_filter'] = branch_param
    if search_param:
        session['so_search_query'] = search_param
    elif 'search' in request.form or 'search' in request.args:
        session.pop('so_search_query', None)

    target_id = id

    redirect_kwargs = {
        'id': target_id,
        'branch': branch_param,
        'date_filter': date_filter,
        'status_filter': status_filter
    }
    if cust_search:
        redirect_kwargs['customer_search'] = cust_search
    if search_param:
        redirect_kwargs['search'] = search_param
    redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)

    try:
        _record_order_version(id, change_summary=f"Marked Completed & Paid ({payment_method})")
    except Exception as ve:
        logger.warning(f"Failed to record version on complete: {ve}")

    if request.is_json:
        return jsonify({
            'success': True,
            'message': f"Order {order['order_number']} completed and marked paid by {payment_method}!",
            'payment_method': payment_method,
            'redirect_url': redirect_url,
            'next_order_id': target_id
        })

    flash(f"Order {order['order_number']} is marked Complete & Paid by {user_login_name} ({payment_method})!", "success")
    return redirect(redirect_url)

@sales_orders_bp.route('/sales/<int:id>/reopen', methods=['POST'])
def reopen_order(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))
    if not _check_order_branch_access(order):
        flash("Access denied: Order belongs to another branch.", "error")
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

    try:
        _record_order_version(id, change_summary="Order Reopened to Open")
    except Exception as ve:
        logger.warning(f"Failed to record version on reopen: {ve}")

    if request.is_json:
        return jsonify({'success': True, 'message': 'Order is Re-opened! You can now edit the order.', 'redirect_url': redirect_url})

    flash("Order is Re-opened! You can now edit the order.", "success")
    return redirect(redirect_url)

@sales_orders_bp.route('/sales/<int:id>/cancel_order', methods=['POST'])
def cancel_order_direct(id):
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        flash("Order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))
    if not _check_order_branch_access(order):
        if request.is_json:
            return jsonify({'success': False, 'message': 'Access denied: Order belongs to another branch.'}), 403
        flash("Access denied: Order belongs to another branch.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    with get_db_cursor(commit=True) as cur:
        # If order was OPEN (unpaid/not shipped), release the reserved stock
        if (order.get('status') or '').upper() == 'OPEN':
            loc_id = order.get('location_id') or 100
            cur.execute("""
                SELECT product_id, quantity, addon_product_id, addon_quantity
                FROM sales_order_lines
                WHERE sales_order_id = %s
            """, (id,))
            for l in cur.fetchall():
                if l['product_id']:
                    qty = float(l['quantity'] or 0)
                    _unreserve_order_stock(cur, loc_id, l['product_id'], qty)
                if l.get('addon_product_id'):
                    a_qty = float(l['quantity'] or 0) * float(l.get('addon_quantity') or 1.0)
                    _unreserve_order_stock(cur, loc_id, l['addon_product_id'], a_qty)

        cur.execute("""
            UPDATE sales_orders
            SET status = 'CANCELLED',
                balance_due = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (id,))

        sync_inventory_reserved_quantities(cur=cur)

    try:
        _record_order_version(id, change_summary="Order Cancelled")
    except Exception as ve:
        logger.warning(f"Failed to record version on cancel: {ve}")

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
    if not _check_order_branch_access(order):
        if request.is_json:
            return jsonify({'error': 'Access denied: Order belongs to another branch.'}), 403
        flash("Access denied: Order belongs to another branch.", "error")
        return redirect(url_for('sales_orders.list_orders', view='table'))

    order_number = order['order_number']
    customer_id = order['customer_id']
    balance_due = float(order.get('balance_due') or 0.0)
    location_id = order.get('location_id')
    branch_id = order.get('branch_id')
    status = (order.get('status') or '').upper()

    date_filter = request.form.get('date_filter') or request.args.get('date_filter') or session.get('so_date_filter') or 'All'
    status_filter = request.form.get('status_filter') or request.args.get('status_filter') or session.get('so_status_filter') or 'Open, In Progress, Paid'
    cust_search = request.form.get('customer_search') or request.args.get('customer_search') or session.get('so_customer_search') or ''
    branch_param = request.form.get('branch') or request.args.get('branch') or session.get('so_branch_filter') or (str(branch_id) if branch_id else 'main')
    if 'search' in request.form:
        search_param = (request.form.get('search') or '').strip()
    elif 'search' in request.args:
        search_param = (request.args.get('search') or '').strip()
    elif 'so_search_query' in session and session.get('so_search_query'):
        search_param = session.get('so_search_query').strip()
    else:
        search_param = ''

    session['so_date_filter'] = date_filter
    session['so_status_filter'] = status_filter
    session['so_customer_search'] = cust_search
    session['so_branch_filter'] = branch_param
    if search_param:
        session['so_search_query'] = search_param
    elif 'search' in request.form or 'search' in request.args:
        session.pop('so_search_query', None)

    req_upper_id = request.form.get('upper_order_id') or (request.get_json(silent=True) or {}).get('upper_order_id')

    # Find upper or adjacent order BEFORE deleting the record
    target_id = _find_upper_or_adjacent_order(
        current_id=id,
        date_filter=date_filter,
        status_filter=status_filter,
        customer_search=cust_search,
        branch_id=branch_param,
        requested_upper_id=req_upper_id,
        search_query=search_param
    )

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

            # 4. Re-synchronize numbering sequences so new orders continue properly without gaps
            resync_all_sequences(cur=cur)

        if target_id:
            redirect_kwargs = {
                'id': target_id,
                'branch': branch_param,
                'date_filter': date_filter,
                'status_filter': status_filter
            }
            if cust_search:
                redirect_kwargs['customer_search'] = cust_search
            if search_param:
                redirect_kwargs['search'] = search_param
            redirect_url = url_for('sales_orders.detail_order', **redirect_kwargs)
        else:
            # If no remaining orders in drawer/system, stay in sales order workspace with a new order form
            redirect_url = url_for('sales_orders.new_order', branch=branch_param)

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Order {order_number} deleted successfully.',
                'redirect_url': redirect_url,
                'next_order_id': target_id
            })
        flash(f"Order {order_number} deleted successfully.", "success")
        return redirect(redirect_url)

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
    if not _check_order_branch_access(order):
        flash("Access denied: Order belongs to another branch.", "error")
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

        sync_inventory_reserved_quantities(cur=cur)

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
        if not _check_order_branch_access(order):
            flash("Access denied: Order belongs to another branch.", "error")
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

    token = request.args.get('token') or request.args.get('share_token')
    is_valid_token = verify_order_share_token(id, token)

    if not is_valid_token and not _check_order_branch_access(order):
        return "Access denied: Order belongs to another branch.", 403

    is_shared = bool(is_valid_token or request.args.get('shared') == '1' or request.args.get('nosettings') == '1' or not session.get('user_id'))

    lines = query_all("""
        SELECT 
            sol.*,
            COALESCE(p.name, 'Item') as product_name,
            p.sku as product_sku,
            p.barcode as product_barcode,
            COALESCE(sol.uom, p.uom, 'pcs.') as product_uom,
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
            'show_tax': True,
            'seller_signature_url': None,
            'seller_name': None
        }

    # Branch specific invoice styles & branding override
    branch = None
    is_branch = False
    if order.get('branch_id'):
        branch = query_one("SELECT * FROM branches WHERE id = %s", (order['branch_id'],))
        if branch and not branch.get('is_main'):
            is_branch = True
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
                      'show_sku', 'show_tax', 'enable_khr_total', 'khr_exchange_rate',
                      'primary_color', 'secondary_color', 'font_family', 'paper_size',
                      'qr_size', 'qr_position', 'bank_info_size', 'bank_info_position',
                      'qr_offset_x', 'qr_offset_y', 'bank_offset_x', 'bank_offset_y',
                      'unit_price_decimals']:
                if k in b_settings and b_settings[k] not in (None, ''):
                    inv_settings[k] = b_settings[k]

            # INDEPENDENT SIGNATURE FOR BRANCHES (HQ signature is for HQ only):
            # A branch ONLY uses its own signature and seller name if configured in its own b_settings!
            inv_settings['seller_signature_url'] = b_settings.get('seller_signature_url') or None
            inv_settings['seller_name'] = b_settings.get('seller_name') or None
            if 'show_signature' in b_settings:
                inv_settings['show_signature'] = bool(b_settings['show_signature'])
            else:
                inv_settings['show_signature'] = True

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

        override_address = request.args.get('address')
        if override_address is not None and override_address.strip():
            order['customer_address'] = override_address.strip()

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
                           branch=branch,
                           is_branch=is_branch,
                           inv_settings=inv_settings,
                           doc_type=doc_type,
                           khr_rate=rate,
                           total_khr=total_khr,
                           paid_khr=paid_khr,
                           balance_khr=balance_khr,
                           is_shared=is_shared)


@sales_orders_bp.route('/api/invoice/save-signature-settings', methods=['POST'])
def save_invoice_signature_settings():
    try:
        seller_name = request.form.get('seller_name', '').strip()
        show_sig_val = request.form.get('show_signature')
        show_signature = None
        if show_sig_val is not None:
            show_signature = (show_sig_val in ('1', 'true', 'True', 'on', True))

        remove_sig = (request.form.get('remove_signature') in ('1', 'true', 'True', 'on', True))
        
        branch_id = request.form.get('branch_id')
        branch = None
        if branch_id and str(branch_id).strip() not in ('', 'null', 'None', 'main', 'hq'):
            branch = query_one("SELECT id, name, is_main, settings_json FROM branches WHERE id = %s", (branch_id,))

        is_branch = bool(branch and not branch.get('is_main'))

        # Handle uploaded signature image file (or base64 fallback)
        signature_url = None
        has_new_file = ('signature_file' in request.files and request.files['signature_file'].filename)
        if has_new_file:
            file = request.files['signature_file']
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
            if ext in ('png', 'jpg', 'jpeg', 'webp', 'svg'):
                upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'invoice', 'signatures')
                try:
                    os.makedirs(upload_dir, mode=0o777, exist_ok=True)
                except Exception:
                    pass
                prefix = f"branch_{branch['id']}" if is_branch else "hq"
                fname = f"seller_sig_{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                try:
                    file.save(save_path)
                    try:
                        os.chmod(save_path, 0o666)
                    except Exception:
                        pass
                    signature_url = f"/static/uploads/invoice/signatures/{fname}"
                except Exception as save_err:
                    logger.warning(f"File save failed ({save_err}), falling back to base64 data-URI for signature")
                    import base64
                    file.seek(0)
                    file_bytes = file.read()
                    mime_type = f"image/{'svg+xml' if ext == 'svg' else ('jpeg' if ext == 'jpg' else ext)}"
                    b64_str = base64.b64encode(file_bytes).decode('utf-8')
                    signature_url = f"data:{mime_type};base64,{b64_str}"

        if is_branch:
            # =========================================================
            # BRANCH INDEPENDENT SIGNATURE (Does NOT touch HQ!)
            # =========================================================
            b_set = branch.get('settings_json')
            if isinstance(b_set, str):
                try:
                    b_set = json.loads(b_set) if b_set else {}
                except Exception:
                    b_set = {}
            elif not isinstance(b_set, dict):
                b_set = {}

            if remove_sig:
                b_set['seller_signature_url'] = None
                signature_url = None
            elif has_new_file:
                b_set['seller_signature_url'] = signature_url
            else:
                signature_url = b_set.get('seller_signature_url')

            if request.form.get('seller_name') is not None:
                b_set['seller_name'] = seller_name
            if show_signature is not None:
                b_set['show_signature'] = show_signature

            execute("UPDATE branches SET settings_json = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (json.dumps(b_set), branch['id']))

            return jsonify({
                'success': True,
                'is_branch': True,
                'branch_id': branch['id'],
                'branch_name': branch.get('name', ''),
                'seller_signature_url': signature_url or '',
                'seller_name': seller_name,
                'show_signature': show_signature if show_signature is not None else b_set.get('show_signature', True)
            })

        else:
            # =========================================================
            # HQ INDEPENDENT SIGNATURE (Does NOT touch any branch!)
            # =========================================================
            current_inv = query_one("SELECT id, seller_signature_url, seller_name, show_signature FROM invoice_settings LIMIT 1")
            if not current_inv:
                from routes.settings import get_invoice_settings
                current_inv = get_invoice_settings()

            if remove_sig:
                signature_url = None
            elif not has_new_file:
                signature_url = current_inv.get('seller_signature_url')

            updates = []
            params = []
            if request.form.get('seller_name') is not None:
                updates.append("seller_name = %s")
                params.append(seller_name)
            if show_signature is not None:
                updates.append("show_signature = %s")
                params.append(show_signature)
            if remove_sig or has_new_file:
                updates.append("seller_signature_url = %s")
                params.append(signature_url)

            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(current_inv['id'])
                execute(f"UPDATE invoice_settings SET {', '.join(updates)} WHERE id = %s", tuple(params))

            return jsonify({
                'success': True,
                'is_branch': False,
                'branch_id': None,
                'seller_signature_url': signature_url or '',
                'seller_name': seller_name,
                'show_signature': show_signature if show_signature is not None else (current_inv.get('show_signature', True) if current_inv else True)
            })

    except Exception as e:
        logger.error(f"Error saving invoice signature settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@sales_orders_bp.route('/sales/<int:id>/upload-share-image', methods=['POST'])
def upload_sales_share_image(id):
    try:
        order = query_one("""
            SELECT so.id, so.order_number, so.total_amount, c.name as customer_name, so.branch_id
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.id = %s
        """, (id,))
        if not order or not _check_order_branch_access(order):
            return jsonify({'success': False, 'message': 'Access denied or order not found'}), 403

        data = request.get_json(silent=True) or request.form
        image_data = data.get('image_data') if hasattr(data, 'get') else request.form.get('image_data')

        # Support multipart file upload if sent via FormData
        if not image_data and 'image_file' in request.files:
            file = request.files['image_file']
            image_bytes = file.read()
            ext = 'jpg' if 'jpeg' in (file.content_type or '') or (file.filename and file.filename.endswith(('.jpg', '.jpeg'))) else 'png'
        elif image_data:
            import base64
            if ',' in image_data:
                header, encoded = image_data.split(',', 1)
                ext = 'png' if 'png' in header else 'jpg'
            else:
                encoded = image_data
                ext = 'jpg'
            image_bytes = base64.b64decode(encoded)
        else:
            return jsonify({'success': False, 'error': 'No image data provided'}), 400

        # Save to static/uploads/shared_invoices/
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'shared_invoices')
        os.makedirs(upload_dir, mode=0o777, exist_ok=True)

        clean_order_num = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(order.get('order_number') or f'SO-{id}'))
        filename = f"Invoice_{clean_order_num}.{ext}"
        save_path = os.path.join(upload_dir, filename)

        with open(save_path, 'wb') as f:
            f.write(image_bytes)
        try:
            os.chmod(save_path, 0o666)
        except Exception:
            pass

        base_host = request.host_url.rstrip('/')
        image_url = f"{base_host}/static/uploads/shared_invoices/{filename}?v={int(time.time())}"

        share_data = build_order_telegram_share(order, base_host, image_url)

        return jsonify({
            'success': True,
            'filename': filename,
            'image_url': image_url,
            'token': share_data['token'],
            'preview_url': share_data['preview_url'],
            'direct_print_url': share_data['direct_print_url'],
            'telegram_url': share_data['telegram_url'],
            'caption': share_data['caption']
        })
    except Exception as e:
        logger.error(f"Error in upload_sales_share_image: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@sales_orders_bp.route('/sales/<int:id>/telegram-share-data', methods=['GET'])
def get_order_telegram_share_data(id):
    try:
        order = query_one("""
            SELECT so.id, so.order_number, so.total_amount, c.name as customer_name, so.branch_id
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.id = %s
        """, (id,))
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        token = request.args.get('token') or request.args.get('share_token')
        is_valid_token = verify_order_share_token(id, token)
        if not is_valid_token and not _check_order_branch_access(order):
            return jsonify({'success': False, 'message': 'Access denied or unauthorized branch'}), 403

        base_host = request.host_url.rstrip('/')
        clean_order_num = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(order.get('order_number') or f'SO-{id}'))
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'shared_invoices')
        image_url = None
        for ext in ('jpg', 'jpeg', 'png'):
            fn = f"Invoice_{clean_order_num}.{ext}"
            if os.path.exists(os.path.join(upload_dir, fn)):
                image_url = f"{base_host}/static/uploads/shared_invoices/{fn}"
                break

        share_data = build_order_telegram_share(order, base_host, image_url)
        share_data['success'] = True
        return jsonify(share_data)
    except Exception as e:
        logger.error(f"Error in get_order_telegram_share_data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@sales_orders_bp.route('/api/invoice/toggle-signature', methods=['POST'])
def toggle_invoice_signature():
    try:
        data = request.get_json(silent=True) or request.form
        show_sig = data.get('show_signature')
        is_show = (show_sig in (True, 'true', 'True', '1', 'on', 1))
        
        branch_id = data.get('branch_id')
        branch = None
        if branch_id and str(branch_id).strip() not in ('', 'null', 'None', 'main', 'hq'):
            branch = query_one("SELECT id, is_main, settings_json FROM branches WHERE id = %s", (branch_id,))

        if branch and not branch.get('is_main'):
            b_set = branch.get('settings_json')
            if isinstance(b_set, str):
                try:
                    b_set = json.loads(b_set) if b_set else {}
                except Exception:
                    b_set = {}
            elif not isinstance(b_set, dict):
                b_set = {}
            b_set['show_signature'] = is_show
            execute("UPDATE branches SET settings_json = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (json.dumps(b_set), branch['id']))
            return jsonify({'success': True, 'is_branch': True, 'branch_id': branch['id'], 'show_signature': is_show})
        else:
            execute("UPDATE invoice_settings SET show_signature = %s, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM invoice_settings LIMIT 1);", (is_show,))
            return jsonify({'success': True, 'is_branch': False, 'branch_id': None, 'show_signature': is_show})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'message': 'Access denied or order not found'}), 403

    data = request.get_json(silent=True) or request.form
    carrier = (data.get('carrier') or '').strip()
    province = (data.get('destination_province') or '').strip()
    package_count = max(1, int(data.get('package_count') or 1))
    delivery_notes = (data.get('delivery_notes') or '').strip()
    cod_amount = max(0.0, float(data.get('cod_amount') or 0.0))
    customer_address = (data.get('customer_address') or '').strip()

    if customer_address:
        execute("""
            UPDATE sales_orders
            SET carrier = %s,
                destination_province = %s,
                package_count = %s,
                delivery_notes = %s,
                cod_amount = %s,
                customer_address = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (carrier, province, package_count, delivery_notes, cod_amount, customer_address, id))
    else:
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

    return jsonify({
        'success': True,
        'message': 'Shipping details updated',
        'carrier': carrier,
        'destination_province': province,
        'package_count': package_count,
        'delivery_notes': delivery_notes,
        'cod_amount': cod_amount,
        'customer_address': customer_address
    })


@sales_orders_bp.route('/sales/<int:id>/shipping', methods=['GET'])
def get_sales_shipping(id):
    order = query_one("SELECT id, carrier, destination_province, package_count, delivery_notes, cod_amount, customer_address, total_amount, balance_due FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'message': 'Access denied or order not found'}), 403
    return jsonify({
        'success': True,
        'carrier': order.get('carrier') or 'Virak Buntham',
        'destination_province': order.get('destination_province') or '',
        'package_count': order.get('package_count') or 1,
        'delivery_notes': order.get('delivery_notes') or '',
        'cod_amount': float(order.get('cod_amount') if order.get('cod_amount') is not None else (order.get('total_amount') or order.get('balance_due') or 0.0)),
        'customer_address': order.get('customer_address') or ''
    })



@sales_orders_bp.route('/sales/<int:id>/update-delivery', methods=['POST'])
def update_sales_delivery(id):
    try:
        order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
        if not order or not _check_order_branch_access(order):
            return jsonify({'success': False, 'error': 'Access denied or order not found'}), 403

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
    if not order or not _check_order_branch_access(order):
        return "Access denied or order not found", 403
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
    writer.writerow(["Customer Phone", order.get('customer_phone') or ''])
    writer.writerow(["Customer Address", order.get('customer_address') or ''])
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
    order = query_one("SELECT * FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        if request.is_json:
            return jsonify({'success': False, 'error': 'Access denied or order not found'}), 403
        flash("Access denied or order not found.", "error")
        return redirect(url_for('sales_orders.list_orders'))

    if request.method == 'GET':
        cust_search = request.args.get('customer_search', '').strip()
        branch_id = request.args.get('branch', '').strip()
        params = {'copy_from': id}
        if cust_search:
            params['customer_search'] = cust_search
        if branch_id:
            params['branch'] = branch_id
        return redirect(url_for('sales_orders.new_order', **params))

    req_data = request.get_json(silent=True) or {}
    source_lines = query_all("SELECT * FROM sales_order_lines WHERE sales_order_id = %s ORDER BY line_num ASC", (id,))

    new_order_number = get_next_order_number('SO', branch_id=order.get('branch_id'))

    import re
    raw_notes = (req_data.get('notes') if 'notes' in req_data else order.get('notes') or '').strip()
    cleaned_lines = [
        line for line in raw_notes.splitlines()
        if not re.match(r'^\s*previous\s+bill\s+date\s*:', line, re.IGNORECASE)
        and not re.match(r'^\s*copied\s+from\s+so-\d+', line, re.IGNORECASE)
    ]
    combined_notes = "\n".join(cleaned_lines).strip()

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

    po_number = get_next_order_number('PO')

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

    po_number = get_next_order_number('PO')

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


# ==============================================================================
# Sales Order Attachments & Photo Upload Endpoints
# ==============================================================================

@sales_orders_bp.route('/sales/<int:id>/attachments', methods=['GET'])
def get_order_attachments(id):
    _ensure_so_tables_exist()
    order = query_one("SELECT id FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404

    raw_attachments = query_all("""
        SELECT id, sales_order_id, file_name, file_path, file_size, file_type, caption, uploaded_by,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM sales_order_attachments
        WHERE sales_order_id = %s
        ORDER BY created_at DESC, id DESC
    """, (id,))
    attachments = []
    for a in raw_attachments:
        d = dict(a)
        d['original_name'] = d.get('file_name')
        d['file_url'] = d.get('file_path')
        d['mime_type'] = d.get('file_type')
        ftype = (d.get('file_type') or '').lower()
        fname = (d.get('file_name') or '').lower()
        if ftype.startswith('image/') or fname.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            d['file_category'] = 'image'
        elif 'pdf' in ftype or fname.endswith('.pdf'):
            d['file_category'] = 'pdf'
        else:
            d['file_category'] = 'file'
        attachments.append(d)
    return jsonify(attachments)


@sales_orders_bp.route('/sales/<int:id>/attachments/upload', methods=['POST'])
def upload_order_attachment(id):
    _ensure_so_tables_exist()
    order = query_one("SELECT id, order_number FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404

    files = request.files.getlist('files') or request.files.getlist('attachment_files')
    if not files or not files[0].filename:
        if 'file' in request.files:
            files = [request.files['file']]
        elif 'attachment_file' in request.files:
            files = [request.files['attachment_file']]

    if not files or not files[0].filename:
        return jsonify({'success': False, 'error': 'No file selected for upload'}), 400

    upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'sales_attachments')
    os.makedirs(upload_dir, exist_ok=True)

    uploaded_items = []
    uname = session.get('username') or session.get('display_name') or 'Admin'
    caption = (request.form.get('caption') or '').strip()

    for f in files:
        if f and f.filename:
            orig_name = f.filename
            safe_name = f"so_{id}_{int(time.time())}_{secure_filename(orig_name)}"
            fpath = os.path.join(upload_dir, safe_name)
            f.save(fpath)
            fsize = os.path.getsize(fpath)
            url_path = f"/static/uploads/sales_attachments/{safe_name}"
            ftype, _ = mimetypes.guess_type(orig_name)
            ftype = ftype or ('image/jpeg' if orig_name.lower().endswith(('.jpg', '.jpeg')) else 'application/octet-stream')

            att_id = execute_returning_id("""
                INSERT INTO sales_order_attachments (sales_order_id, file_name, file_path, file_size, file_type, caption, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (id, orig_name, url_path, fsize, ftype, caption, uname))

            uploaded_items.append({
                'id': att_id,
                'file_name': orig_name,
                'original_name': orig_name,
                'file_path': url_path,
                'file_url': url_path,
                'file_size': fsize,
                'file_type': ftype,
                'mime_type': ftype,
                'caption': caption,
                'uploaded_by': uname
            })

    if uploaded_items:
        _record_order_version(id, user_name=uname, change_summary=f"Added {len(uploaded_items)} attachment(s): {', '.join(x['file_name'] for x in uploaded_items)}")

    total_count = query_one("SELECT COUNT(*) as cnt FROM sales_order_attachments WHERE sales_order_id = %s", (id,))['cnt']
    return jsonify({'success': True, 'uploaded': uploaded_items, 'total_count': total_count})


@sales_orders_bp.route('/sales/<int:id>/attachments/<int:att_id>/delete', methods=['POST'])
def delete_order_attachment(id, att_id):
    _ensure_so_tables_exist()
    order = query_one("SELECT id FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    att = query_one("SELECT * FROM sales_order_attachments WHERE id = %s AND sales_order_id = %s", (att_id, id))
    if att:
        try:
            rel_path = att['file_path'].lstrip('/')
            full_path = os.path.join(os.path.dirname(__file__), '..', rel_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception as e:
            logger.warning(f"Error removing physical attachment file: {e}")

        execute("DELETE FROM sales_order_attachments WHERE id = %s AND sales_order_id = %s", (att_id, id))
        uname = session.get('username') or session.get('display_name') or 'Admin'
        _record_order_version(id, user_name=uname, change_summary=f"Deleted attachment: {att['file_name']}")

    total_count = query_one("SELECT COUNT(*) as cnt FROM sales_order_attachments WHERE sales_order_id = %s", (id,))['cnt']
    return jsonify({'success': True, 'total_count': total_count})


# ==============================================================================
# Sales Order Version History Endpoints
# ==============================================================================

@sales_orders_bp.route('/sales/<int:id>/versions', methods=['GET'])
def get_order_versions(id):
    _ensure_so_tables_exist()
    order = query_one("SELECT id FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404

    versions = query_all("""
        SELECT id, sales_order_id, version_number, order_number, status, payment_status,
               customer_name, total_amount, paid_amount, balance_due, items_count,
               user_name, change_summary,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM sales_order_versions
        WHERE sales_order_id = %s
        ORDER BY version_number DESC, created_at DESC
    """, (id,))

    if not versions:
        _record_order_version(id, change_summary="Base Version (v1)")
        versions = query_all("""
            SELECT id, sales_order_id, version_number, order_number, status, payment_status,
                   customer_name, total_amount, paid_amount, balance_due, items_count,
                   user_name, change_summary,
                   TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
            FROM sales_order_versions
            WHERE sales_order_id = %s
            ORDER BY version_number DESC, created_at DESC
        """, (id,))

    return jsonify({'success': True, 'versions': versions})


@sales_orders_bp.route('/sales/<int:id>/versions/<int:ver_id>', methods=['GET'])
def get_order_version_snapshot(id, ver_id):
    _ensure_so_tables_exist()
    order = query_one("SELECT id FROM sales_orders WHERE id = %s", (id,))
    if not order or not _check_order_branch_access(order):
        return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404

    ver = query_one("""
        SELECT id, sales_order_id, version_number, order_number, status, payment_status,
               customer_name, total_amount, paid_amount, balance_due, items_count,
               user_name, change_summary, snapshot_data,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM sales_order_versions
        WHERE id = %s AND sales_order_id = %s
    """, (ver_id, id))

    if not ver:
        return jsonify({'success': False, 'error': 'Version snapshot not found'}), 404

    v_dict = dict(ver)
    v_dict['created_by'] = v_dict.get('user_name') or 'admin'
    v_dict['order_status'] = v_dict.get('status') or 'UNFULFILLED'
    snapshot = v_dict.get('snapshot_data') or {}

    return jsonify({
        'success': True,
        'version': v_dict,
        'snapshot': snapshot
    })

@sales_orders_bp.route('/api/products/<int:id>/components', methods=['GET'])
def get_order_product_components(id):
    """Returns component details with live on-hand and reserved quantities for a kit/combined product."""
    try:
        comp_map = _get_product_components_map()
        comps = comp_map.get(id, [])
        min_buildable = 999999999 if comps else 0
        for c in comps:
            c_qty = float(c.get('quantity') or 1.0)
            c_avail = max(0.0, float(c.get('stock_available') or 0.0))
            b = int(c_avail // c_qty) if c_qty > 0 else 0
            if b < min_buildable:
                min_buildable = b
        max_kits = max(0, min_buildable) if min_buildable != 999999999 else 0
        return jsonify({
            'success': True,
            'is_combined': len(comps) > 0,
            'max_kits_buildable': max_kits,
            'components': comps
        })
    except Exception as e:
        logger.error(f"Error fetching components for product {id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



