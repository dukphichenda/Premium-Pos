import sys
import os

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config

def sql_quote(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    # string or date
    s = str(val).replace("'", "''")
    return f"'{s}'"

def generate_deploy_sql():
    conn = psycopg2.connect(host=Config.PG_HOST, port=Config.PG_PORT, user=Config.PG_USER, password=Config.PG_PASSWORD, dbname=Config.PG_DATABASE)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    sql_parts = ["-- ====================================================",
                 "-- Deploy Sales Orders >= SO-022821 to Hostinger VPS",
                 "-- ====================================================",
                 "BEGIN;\n"]

    # 1. Customer 2775 (MO NI)
    cur.execute("SELECT * FROM customers WHERE id = 2775")
    cust = cur.fetchone()
    if cust:
        sql_parts.append(f"""
        INSERT INTO customers (
            id, name, contact_name, phone, fax, email,
            address1, address2, city, state, country, postal_code,
            billing_address, shipping_address, default_pricing_scheme_id, discount_percent,
            is_active, website, balance, branch_id
        ) VALUES (
            {cust['id']}, {sql_quote(cust['name'])}, {sql_quote(cust['contact_name'])}, {sql_quote(cust['phone'])}, {sql_quote(cust['fax'])}, {sql_quote(cust['email'])},
            {sql_quote(cust['address1'])}, {sql_quote(cust['address2'])}, {sql_quote(cust['city'])}, {sql_quote(cust['state'])}, {sql_quote(cust['country'])}, {sql_quote(cust['postal_code'])},
            {sql_quote(cust['billing_address'])}, {sql_quote(cust['shipping_address'])}, {sql_quote(cust['default_pricing_scheme_id'])}, {sql_quote(cust['discount_percent'])},
            {sql_quote(cust['is_active'])}, {sql_quote(cust['website'])}, {sql_quote(cust['balance'])}, NULL
        )
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            phone = EXCLUDED.phone,
            address1 = EXCLUDED.address1;
        """)

    # 2. Products 252, 469, 487 (or missing products)
    cur.execute("SELECT * FROM products WHERE id IN (252, 469, 487)")
    prods = cur.fetchall()
    for p in prods:
        sql_parts.append(f"""
        INSERT INTO products (
            id, sku, name, description, barcode, category_id, uom,
            master_pack_qty, inner_pack_qty, default_location_id, reorder_point, reorder_quantity,
            standard_cost, average_cost, last_purchase_cost, default_price,
            is_sellable, is_purchaseable, is_active,
            item_type, tax_code, costing_method,
            sales_uom, sales_uom_ratio, sales_uom_ratio_std,
            purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std
        ) VALUES (
            {p['id']}, {sql_quote(p['sku'])}, {sql_quote(p['name'])}, {sql_quote(p['description'])}, {sql_quote(p['barcode'])}, {sql_quote(p['category_id'])}, {sql_quote(p['uom'])},
            {sql_quote(p['master_pack_qty'])}, {sql_quote(p['inner_pack_qty'])}, 100, {sql_quote(p['reorder_point'])}, {sql_quote(p['reorder_quantity'])},
            {sql_quote(p['standard_cost'])}, {sql_quote(p['average_cost'])}, {sql_quote(p['last_purchase_cost'])}, {sql_quote(p['default_price'])},
            {sql_quote(p['is_sellable'])}, {sql_quote(p['is_purchaseable'])}, {sql_quote(p['is_active'])},
            {sql_quote(p['item_type'])}, {sql_quote(p['tax_code'])}, {sql_quote(p['costing_method'])},
            {sql_quote(p['sales_uom'])}, {sql_quote(p['sales_uom_ratio'])}, {sql_quote(p['sales_uom_ratio_std'])},
            {sql_quote(p['purchasing_uom'])}, {sql_quote(p['purchasing_uom_ratio'])}, {sql_quote(p['purchasing_uom_ratio_std'])}
        )
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            sku = EXCLUDED.sku,
            uom = EXCLUDED.uom,
            sales_uom = EXCLUDED.sales_uom,
            sales_uom_ratio_std = EXCLUDED.sales_uom_ratio_std;
        """)

    # 3. Synchronize exact product names for all products
    cur.execute("SELECT id, name FROM products")
    all_prods = cur.fetchall()
    for p in all_prods:
        sql_parts.append(f"UPDATE products SET name = {sql_quote(p['name'])} WHERE id = {p['id']};")

    # 4. Sales Orders >= SO-022821
    cur.execute("SELECT * FROM sales_orders WHERE order_number >= 'SO-022821' ORDER BY id")
    orders = cur.fetchall()
    so_ids = [o['id'] for o in orders]
    so_ids_str = ','.join(map(str, so_ids))

    for o in orders:
        sql_parts.append(f"""
        INSERT INTO sales_orders (
            id, order_number, customer_id, location_id, order_date, due_date,
            status, payment_status, subtotal, tax_amount, total_amount, paid_amount, balance_due,
            sales_rep, notes, picked_date, packed_date, invoiced_date,
            customer_contact, customer_phone, customer_address, destination_province, pricing_scheme_id, po_number, branch_id
        ) VALUES (
            {o['id']}, {sql_quote(o['order_number'])}, {sql_quote(o['customer_id'])}, {sql_quote(o['location_id'])}, {sql_quote(o['order_date'])}, {sql_quote(o['due_date'])},
            {sql_quote(o['status'])}, {sql_quote(o['payment_status'])}, {sql_quote(o['subtotal'])}, {sql_quote(o['tax_amount'])}, {sql_quote(o['total_amount'])}, {sql_quote(o['paid_amount'])}, {sql_quote(o['balance_due'])},
            {sql_quote(o['sales_rep'])}, {sql_quote(o['notes'])}, {sql_quote(o['picked_date'])}, {sql_quote(o['packed_date'])}, {sql_quote(o['invoiced_date'])},
            {sql_quote(o['customer_contact'])}, {sql_quote(o['customer_phone'])}, {sql_quote(o['customer_address'])}, {sql_quote(o['destination_province'])}, {sql_quote(o['pricing_scheme_id'])}, {sql_quote(o['po_number'])}, NULL
        )
        ON CONFLICT (id) DO UPDATE SET
            order_number = EXCLUDED.order_number,
            customer_id = EXCLUDED.customer_id,
            location_id = EXCLUDED.location_id,
            order_date = EXCLUDED.order_date,
            due_date = EXCLUDED.due_date,
            status = EXCLUDED.status,
            payment_status = EXCLUDED.payment_status,
            subtotal = EXCLUDED.subtotal,
            tax_amount = EXCLUDED.tax_amount,
            total_amount = EXCLUDED.total_amount,
            paid_amount = EXCLUDED.paid_amount,
            balance_due = EXCLUDED.balance_due,
            sales_rep = EXCLUDED.sales_rep,
            notes = EXCLUDED.notes,
            picked_date = EXCLUDED.picked_date,
            packed_date = EXCLUDED.packed_date,
            invoiced_date = EXCLUDED.invoiced_date,
            customer_contact = EXCLUDED.customer_contact,
            customer_phone = EXCLUDED.customer_phone,
            customer_address = EXCLUDED.customer_address,
            destination_province = EXCLUDED.destination_province,
            pricing_scheme_id = EXCLUDED.pricing_scheme_id,
            po_number = EXCLUDED.po_number,
            updated_at = CURRENT_TIMESTAMP;
        """)

    # 5. Sales Order Lines
    sql_parts.append(f"DELETE FROM sales_order_lines WHERE sales_order_id IN ({so_ids_str});")
    cur.execute(f"SELECT * FROM sales_order_lines WHERE sales_order_id IN ({so_ids_str}) ORDER BY sales_order_id, line_num")
    lines = cur.fetchall()
    for l in lines:
        sql_parts.append(f"""
        INSERT INTO sales_order_lines (
            id, sales_order_id, line_num, product_id, description,
            quantity, unit_price, discount_percent, subtotal, cost_price,
            picked_qty, packed_qty, shipped_qty, uom, quantity_display
        ) VALUES (
            {l['id']}, {l['sales_order_id']}, {l['line_num']}, {sql_quote(l['product_id'])}, {sql_quote(l['description'])},
            {sql_quote(l['quantity'])}, {sql_quote(l['unit_price'])}, {sql_quote(l['discount_percent'])}, {sql_quote(l['subtotal'])}, {sql_quote(l['cost_price'])},
            {sql_quote(l['picked_qty'])}, {sql_quote(l['packed_qty'])}, {sql_quote(l['shipped_qty'])}, {sql_quote(l['uom'])}, {sql_quote(l['quantity_display'])}
        )
        ON CONFLICT (id) DO UPDATE SET
            sales_order_id = EXCLUDED.sales_order_id,
            line_num = EXCLUDED.line_num,
            product_id = EXCLUDED.product_id,
            description = EXCLUDED.description,
            quantity = EXCLUDED.quantity,
            unit_price = EXCLUDED.unit_price,
            discount_percent = EXCLUDED.discount_percent,
            subtotal = EXCLUDED.subtotal,
            cost_price = EXCLUDED.cost_price,
            picked_qty = EXCLUDED.picked_qty,
            packed_qty = EXCLUDED.packed_qty,
            shipped_qty = EXCLUDED.shipped_qty,
            uom = EXCLUDED.uom,
            quantity_display = EXCLUDED.quantity_display;
        """)

    # 6. Resync PostgreSQL Sequences
    sql_parts.append("""
    DO $$
    DECLARE
        t text;
        s text;
        m bigint;
    BEGIN
        FOR t IN SELECT unnest(ARRAY[
            'sales_orders', 'sales_order_lines', 'order_payments', 'products', 'customers'
        ]) LOOP
            s := pg_get_serial_sequence(t, 'id');
            IF s IS NOT NULL THEN
                EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I', t) INTO m;
                IF m > 0 THEN
                    PERFORM setval(s, m, true);
                END IF;
            END IF;
        END LOOP;
    END $$;

    SELECT setval('so_number_seq', (SELECT COALESCE(MAX(SUBSTRING(order_number FROM '^SO-([0-9]+)$')::bigint), 1) FROM sales_orders WHERE order_number ~ '^SO-[0-9]+$'), true);
    """)

    sql_parts.append("COMMIT;\n")
    conn.close()

    return '\n'.join(sql_parts), len(orders), len(lines)

def deploy_to_hostinger():
    print("=" * 70)
    print("  Deploying Sales Orders >= SO-022821 to Hostinger VPS (179.197.243.175)")
    print("=" * 70)

    print("Step 1: Generating transactional SQL patch from local database...")
    sql_content, order_count, line_count = generate_deploy_sql()
    patch_file = os.path.abspath("scratch/deploy_so_22821.sql")
    with open(patch_file, "w", encoding="utf-8") as f:
        f.write(sql_content)
    print(f"  SQL patch generated: {order_count} orders, {line_count} order lines.")

    print("\nStep 2: Transferring and executing SQL patch on Hostinger VPS...")
    # Feed SQL script directly via SSH to psql on Hostinger
    cmd = [
        "ssh", "-o", "BatchMode=yes", "root@179.197.243.175",
        "sudo -u postgres psql -d inflow_premium"
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    stdout, stderr = p.communicate(input=sql_content)
    if p.returncode != 0:
        print(f"  [ERROR] Database patch failed on Hostinger: {stderr}")
        sys.exit(1)
    else:
        print("  [OK] Database patch applied successfully on Hostinger!")

    print("\nStep 3: Pulling latest application code on Hostinger VPS...")
    git_pull_cmd = [
        "ssh", "-o", "BatchMode=yes", "root@179.197.243.175",
        "cd /var/www/inflow && git pull origin main"
    ]
    res = subprocess.run(git_pull_cmd, capture_output=True, text=True, encoding='utf-8')
    print(f"  Git pull output:\n{res.stdout.strip()}")

    print("\nStep 4: Ensuring permissions and restarting 'inflow' systemd service...")
    restart_cmd = [
        "ssh", "-o", "BatchMode=yes", "root@179.197.243.175",
        "chown -R www-data:www-data /var/www/inflow && systemctl restart inflow && systemctl is-active inflow"
    ]
    res_svc = subprocess.run(restart_cmd, capture_output=True, text=True, encoding='utf-8')
    print(f"  Service status: {res_svc.stdout.strip()}")

    print("\nStep 5: Verifying orders >= SO-022820 on Hostinger database...")
    verify_cmd = [
        "ssh", "-o", "BatchMode=yes", "root@179.197.243.175",
        "sudo -u postgres psql -d inflow_premium -c \"SELECT order_number, status, payment_status, total_amount, balance_due, (SELECT count(*) FROM sales_order_lines WHERE sales_order_id = sales_orders.id) as lines FROM sales_orders WHERE order_number >= 'SO-022820' ORDER BY order_number;\""
    ]
    res_verify = subprocess.run(verify_cmd, capture_output=True, text=True, encoding='utf-8')
    print(res_verify.stdout)

    print("=" * 70)
    print("  Deployment to Hostinger COMPLETE!")
    print("=" * 70)

if __name__ == '__main__':
    deploy_to_hostinger()
