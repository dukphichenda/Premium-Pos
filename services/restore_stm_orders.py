"""
Service to restore Sales Orders and POS Orders for Premium Ecopack STM Branch (Branch ID 1)
from SMA database backup (MySQL dump).
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.stdout.reconfigure(encoding='utf-8')
import re
from datetime import datetime
from database import get_db_cursor, query_one, query_all

def parse_mysql_insert(line):
    """Parses a MySQL INSERT INTO ... VALUES (...) line into a list of Python values."""
    start = line.find('VALUES')
    if start == -1:
        return []
    p_start = line.find('(', start)
    if p_start == -1:
        return []
    
    content = line[p_start + 1 : line.rfind(');')].strip()
    tokens = []
    i = 0
    n = len(content)
    
    while i < n:
        while i < n and content[i] in ' \t\r\n,':
            i += 1
        if i >= n:
            break
        
        if content[i] == "'":
            i += 1
            chars = []
            while i < n:
                c = content[i]
                if c == '\\':
                    i += 1
                    if i < n:
                        chars.append(content[i])
                elif c == "'":
                    i += 1
                    break
                else:
                    chars.append(c)
                i += 1
            tokens.append(''.join(chars))
        else:
            j = i
            while j < n and content[j] not in ',)':
                j += 1
            val = content[i:j].strip()
            if val.upper() == 'NULL':
                tokens.append(None)
            else:
                tokens.append(val)
            i = j
            
    return tokens

def restore_stm_data(dump_path, dry_run=False, start_seq=1, wipe_existing_stm=True):
    """
    Restores all Sales Orders and POS orders for Premium Ecopack STM branch (branch_id=1).
    - Sequential order numbering: SO-STM-00001 ...
    - Scopes customers to branch_id = 1
    - Creates missing products with correct SKU and names
    - Inserts sales orders and order line items
    - Synchronizes the so_branch_1_seq sequence
    """
    if not os.path.exists(dump_path):
        raise FileNotFoundError(f"Dump file not found at: {dump_path}")

    print(f"Reading and parsing MySQL dump: {dump_path}...")
    
    dump_customers = {}
    dump_products = {}
    dump_items = {}
    dump_payments = {}
    dump_sales = []
    
    with open(dump_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('INSERT INTO `sma_companies`'):
                tokens = parse_mysql_insert(line)
                if tokens and len(tokens) > 6 and tokens[2] == 'customer':
                    cid = tokens[0]
                    name = (tokens[5] or '').strip()
                    phone = (tokens[13] or '').strip() if len(tokens) > 13 else ''
                    address = (tokens[8] or '').strip() if len(tokens) > 8 else ''
                    email = (tokens[14] or '').strip() if len(tokens) > 14 else ''
                    dump_customers[cid] = {
                        'name': name or f"Customer {cid}",
                        'phone': phone,
                        'address': address,
                        'email': email
                    }
            elif line.startswith('INSERT INTO `sma_products`'):
                tokens = parse_mysql_insert(line)
                if tokens and len(tokens) > 5:
                    pid = tokens[0]
                    code = (tokens[1] or '').strip()
                    name = (tokens[2] or '').strip()
                    cost = float(tokens[4] or 0.0) if len(tokens) > 4 and tokens[4] else 0.0
                    price = float(tokens[5] or 0.0)
                    dump_products[pid] = {
                        'code': code or f"PR-{pid}",
                        'name': name or f"Product {pid}",
                        'cost': cost,
                        'price': price
                    }
            elif line.startswith('INSERT INTO `sma_sale_items`'):
                tokens = parse_mysql_insert(line)
                if tokens and len(tokens) >= 17:
                    sale_id = int(tokens[1])
                    pid = tokens[2]
                    code = (tokens[3] or '').strip()
                    name = (tokens[4] or '').strip()
                    unit_price = float(tokens[8] or 0.0) if tokens[8] else 0.0
                    qty = float(tokens[9] or 1.0) if tokens[9] else 1.0
                    subtotal = float(tokens[16] or (qty * unit_price)) if tokens[16] else (qty * unit_price)
                    uom = (tokens[21] or 'pcs').strip() if len(tokens) > 21 and tokens[21] else 'pcs'
                    
                    if sale_id not in dump_items:
                        dump_items[sale_id] = []
                    dump_items[sale_id].append({
                        'product_dump_id': pid,
                        'sku': code,
                        'name': name,
                        'unit_price': unit_price,
                        'quantity': qty,
                        'subtotal': subtotal,
                        'uom': uom
                    })
            elif line.startswith('INSERT INTO `sma_payments`'):
                tokens = parse_mysql_insert(line)
                if tokens and len(tokens) >= 15:
                    sale_id_str = tokens[2]
                    if sale_id_str and sale_id_str != 'NULL':
                        try:
                            sale_id = int(sale_id_str)
                            pdate = tokens[1]
                            paid_by = (tokens[7] or 'cash').strip()
                            amount = float(tokens[14] or 0.0) if tokens[14] else 0.0
                            if sale_id not in dump_payments:
                                dump_payments[sale_id] = []
                            dump_payments[sale_id].append({
                                'date': pdate,
                                'method': paid_by,
                                'amount': amount
                            })
                        except ValueError:
                            pass
            elif line.startswith('INSERT INTO `sma_sales`'):
                tokens = parse_mysql_insert(line)
                if tokens and len(tokens) >= 31:
                    sid = int(tokens[0])
                    sdate = tokens[1]
                    ref = tokens[2]
                    cid = tokens[3]
                    cname = tokens[4]
                    total = float(tokens[10] or 0.0) if tokens[10] else 0.0
                    discount = float(tokens[13] or 0.0) if tokens[13] else 0.0
                    shipping = float(tokens[19] or 0.0) if tokens[19] else 0.0
                    grand_total = float(tokens[20] or 0.0) if tokens[20] else 0.0
                    sale_status = (tokens[21] or 'completed').strip().lower()
                    payment_status = (tokens[22] or 'paid').strip().lower()
                    pos = str(tokens[29]).strip() if tokens[29] is not None else '0'
                    paid = float(tokens[30] or 0.0) if tokens[30] else 0.0
                    note = tokens[8] or ''
                    staff_note = tokens[9] or ''
                    
                    dump_sales.append({
                        'dump_id': sid,
                        'date': sdate,
                        'reference_no': ref,
                        'customer_dump_id': cid,
                        'customer_name': cname,
                        'total': total,
                        'discount': discount,
                        'shipping': shipping,
                        'grand_total': grand_total,
                        'sale_status': sale_status,
                        'payment_status': payment_status,
                        'pos': pos,
                        'paid': paid,
                        'note': note,
                        'staff_note': staff_note
                    })

    # Chronological sort
    dump_sales.sort(key=lambda s: (s['date'], s['dump_id']))

    print(f"Extracted {len(dump_sales)} sales and {len(dump_items)} item sets from dump.")

    if dry_run:
        print("[DRY-RUN] Validation completed successfully. No changes written to database.")
        return {
            'sales_count': len(dump_sales),
            'items_count': sum(len(v) for v in dump_items.values()),
            'customers_count': len(dump_customers),
            'products_count': len(dump_products),
            'first_order_date': dump_sales[0]['date'],
            'last_order_date': dump_sales[-1]['date']
        }

    # Execute DB Insertion
    with get_db_cursor(commit=True) as cur:
        # Branch validation
        cur.execute("SELECT id, code, name, location_id FROM branches WHERE id = 1")
        branch = cur.fetchone()
        if not branch:
            raise ValueError("Branch ID 1 (Premium Ecopack STM) does not exist in branches table!")
        
        branch_id = branch['id']
        stm_loc_id = branch['location_id'] or 101

        if wipe_existing_stm:
            print("Cleaning up existing STM sales orders for clean restoration...")
            cur.execute("""
                DELETE FROM sales_order_lines 
                WHERE sales_order_id IN (SELECT id FROM sales_orders WHERE branch_id = %s);
            """, (branch_id,))
            cur.execute("DELETE FROM sales_orders WHERE branch_id = %s;", (branch_id,))
            cur.execute("DELETE FROM customers WHERE branch_id = %s;", (branch_id,))

        # 1. Ensure Products Exist
        print("Synchronizing products...")
        cur.execute("SELECT id, sku, LOWER(name) as lname FROM products")
        pg_products = cur.fetchall()
        sku_to_pid = {p['sku'].strip().lower(): p['id'] for p in pg_products if p['sku']}
        name_to_pid = {p['lname'].strip(): p['id'] for p in pg_products if p['lname']}

        # Check dump products
        for dpid, dp in dump_products.items():
            sku_k = dp['code'].strip().lower()
            name_k = dp['name'].strip().lower()
            if sku_k in sku_to_pid:
                continue
            if name_k in name_to_pid:
                sku_to_pid[sku_k] = name_to_pid[name_k]
                continue
            
            # Create product
            cur.execute("""
                INSERT INTO products (sku, name, default_price, standard_cost, uom, is_active, is_sellable)
                VALUES (%s, %s, %s, %s, 'pcs', TRUE, TRUE)
                RETURNING id;
            """, (dp['code'], dp['name'], dp['price'], dp['cost']))
            new_pid = cur.fetchone()['id']
            sku_to_pid[sku_k] = new_pid
            name_to_pid[name_k] = new_pid

        # Also check items in case any item SKU was not in sma_products
        for s_items in dump_items.values():
            for it in s_items:
                sku_k = it['sku'].strip().lower()
                name_k = it['name'].strip().lower()
                if sku_k not in sku_to_pid and name_k not in name_to_pid:
                    cur.execute("""
                        INSERT INTO products (sku, name, default_price, standard_cost, uom, is_active, is_sellable)
                        VALUES (%s, %s, %s, 0.0, %s, TRUE, TRUE)
                        RETURNING id;
                    """, (it['sku'], it['name'], it['unit_price'], it['uom']))
                    new_pid = cur.fetchone()['id']
                    sku_to_pid[sku_k] = new_pid
                    name_to_pid[name_k] = new_pid

        # 2. Ensure Customers for Branch 1
        print("Synchronizing customers for STM branch...")
        cust_map = {} # dump_cid or name -> pg_cust_id
        for cid, cd in dump_customers.items():
            cur.execute("""
                INSERT INTO customers (name, phone, address1, email, branch_id, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id;
            """, (cd['name'], cd['phone'], cd['address'], cd['email'], branch_id))
            pg_cid = cur.fetchone()['id']
            cust_map[cid] = pg_cid
            cust_map[cd['name'].strip().lower()] = pg_cid

        # 3. Insert Sales Orders
        print(f"Restoring {len(dump_sales)} sales orders for STM branch...")
        seq_num = start_seq
        created_orders = 0
        created_lines = 0

        for s in dump_sales:
            so_number = f"SO-STM-{seq_num:05d}"
            seq_num += 1

            # Resolve customer
            cid = s['customer_dump_id']
            cname = (s['customer_name'] or '').strip()
            pg_cust_id = cust_map.get(cid) or cust_map.get(cname.lower())
            if not pg_cust_id:
                # Auto-create customer for branch 1
                cur.execute("""
                    INSERT INTO customers (name, branch_id, is_active)
                    VALUES (%s, %s, TRUE)
                    RETURNING id;
                """, (cname or 'Walk In', branch_id))
                pg_cust_id = cur.fetchone()['id']
                if cid:
                    cust_map[cid] = pg_cust_id
                if cname:
                    cust_map[cname.lower()] = pg_cust_id

            # Date parsing
            try:
                order_dt = datetime.strptime(s['date'], '%Y-%m-%d %H:%M:%S')
                order_date = order_dt.date()
            except Exception:
                order_date = date.today()

            # Status & Payment
            grand_total = s['grand_total']
            paid = s['paid']
            balance_due = max(0.0, grand_total - paid)
            
            if balance_due <= 0.001 and grand_total > 0:
                payment_status = 'PAID'
            elif paid > 0:
                payment_status = 'PARTIAL'
            else:
                payment_status = 'UNPAID'

            if s['sale_status'] == 'completed':
                status = 'PAID' if payment_status == 'PAID' else 'INVOICED'
            elif s['sale_status'] in ('returned', 'cancelled'):
                status = 'CANCELLED'
            else:
                status = 'OPEN'

            # Payment method notes
            payments_for_sale = dump_payments.get(s['dump_id'], [])
            pay_method = payments_for_sale[0]['method'] if payments_for_sale else (
                'Cash' if s['pos'] == '1' else None
            )

            notes_parts = []
            if s['pos'] == '1':
                notes_parts.append("[POS Sale - STM]")
            if s['note']:
                notes_parts.append(s['note'].strip())
            if s['staff_note']:
                notes_parts.append(f"Staff: {s['staff_note'].strip()}")
            notes_str = " | ".join(notes_parts)

            cur.execute("""
                INSERT INTO sales_orders (
                    order_number, customer_id, branch_id, location_id, order_date,
                    status, payment_status, subtotal, discount_amount, shipping_fee,
                    total_amount, paid_amount, balance_due, notes, payment_method,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s
                ) RETURNING id;
            """, (
                so_number, pg_cust_id, branch_id, stm_loc_id, order_date,
                status, payment_status, s['total'], s['discount'], s['shipping'],
                grand_total, paid, balance_due, notes_str, pay_method,
                s['date'], s['date']
            ))
            new_so_id = cur.fetchone()['id']
            created_orders += 1

            # Insert lines
            items_for_sale = dump_items.get(s['dump_id'], [])
            for line_idx, it in enumerate(items_for_sale, 1):
                sku_k = it['sku'].strip().lower()
                name_k = it['name'].strip().lower()
                pid = sku_to_pid.get(sku_k) or name_to_pid.get(name_k)
                if not pid:
                    pid = list(sku_to_pid.values())[0]  # fallback
                
                cur.execute("""
                    INSERT INTO sales_order_lines (
                        sales_order_id, line_num, product_id, quantity, unit_price, subtotal, uom, description
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    new_so_id, line_idx, pid, it['quantity'], it['unit_price'], it['subtotal'],
                    it['uom'], it['name']
                ))
                created_lines += 1

        # 4. Synchronize sequence in PostgreSQL
        max_seq = seq_num - 1
        seq_name = f"so_branch_{branch_id}_seq"
        print(f"Synchronizing sequence '{seq_name}' to {max_seq}...")
        cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1;")
        cur.execute(f"SELECT setval('{seq_name}', %s, true);", (max_seq,))

        print(f"DONE! Successfully restored {created_orders} sales orders and {created_lines} lines for STM branch.")
        return {
            'success': True,
            'orders_created': created_orders,
            'lines_created': created_lines,
            'first_so': f"SO-STM-{start_seq:05d}",
            'last_so': f"SO-STM-{max_seq:05d}",
            'next_so': f"SO-STM-{max_seq + 1:05d}"
        }

if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    path = r'C:\Users\ADMIN\Downloads\db-backup-on-2026-10-14-16-45-59\db-backup-on-2026-10-14-16-45-59.txt'
    res = restore_stm_data(path, dry_run=dry)
    print(res)
