from database import get_db_cursor

with get_db_cursor(commit=True) as cur:
    cur.execute("""
        SELECT so.id, so.order_number, c.name 
        FROM sales_orders so 
        LEFT JOIN customers c ON c.id = so.customer_id 
        WHERE so.order_number ILIKE '%TEST%' 
           OR so.order_number ILIKE '%TEMP%' 
           OR c.name ILIKE '%TEST%';
    """)
    rows = cur.fetchall()
    print("Found test SO rows:", rows)
    if rows:
        ids = [r['id'] for r in rows]
        print("Cleaning up leftover test SO IDs:", ids)
        cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM sales_orders WHERE id = ANY(%s)", (ids,))
        print("Cleanup done!")

