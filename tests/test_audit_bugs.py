import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestAuditBugs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'
        execute("""
            DELETE FROM sales_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'AUDIT-%%');
            DELETE FROM sales_orders WHERE customer_id IN (SELECT id FROM customers WHERE name LIKE 'Audit%%');
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'AUDIT-%%');
            DELETE FROM purchase_orders WHERE vendor_id IN (SELECT id FROM vendors WHERE name LIKE 'Audit%%');
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'AUDIT-%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'AUDIT-%%');
            DELETE FROM products WHERE sku LIKE 'AUDIT-%%';
            DELETE FROM customers WHERE name LIKE 'Audit%%';
            DELETE FROM vendors WHERE name LIKE 'Audit%%';
        """)

    def test_duplicate_shipment_bug(self):
        """Test if shipping an already shipped order double-deducts stock"""
        pid = execute_returning_id("INSERT INTO products (sku, name, default_price) VALUES ('AUDIT-BUG-SO', 'Audit Bug Prod', 10.0) RETURNING id;")
        lid = query_one("SELECT id FROM locations LIMIT 1")['id']
        cid = execute_returning_id("INSERT INTO customers (name) VALUES ('Audit Bug Customer') RETURNING id;")
        execute("INSERT INTO inventory (product_id, location_id, quantity) VALUES (%s, %s, 100);", (pid, lid))

        post_data = {
            'customer_id': cid,
            'location_id': lid,
            'product_id[]': [pid],
            'quantity[]': [10],
            'unit_price[]': [10.0]
        }
        self.client.post('/sales/create', data=post_data, follow_redirects=True)
        so = query_one("SELECT id FROM sales_orders WHERE customer_id = %s", (cid,))
        so_id = so['id']

        # 1st shipment: 100 -> 90
        self.client.post(f'/sales/{so_id}/status', data={'status': 'SHIPPED'}, follow_redirects=True)
        inv1 = query_one("SELECT quantity FROM inventory WHERE product_id = %s", (pid,))['quantity']
        self.assertEqual(float(inv1), 90.0)

        # 2nd shipment request (replay/double-click)
        self.client.post(f'/sales/{so_id}/status', data={'status': 'SHIPPED'}, follow_redirects=True)
        inv2 = query_one("SELECT quantity FROM inventory WHERE product_id = %s", (pid,))['quantity']

        # Clean up
        execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (so_id,))
        execute("DELETE FROM sales_orders WHERE id = %s", (so_id,))
        execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
        execute("DELETE FROM inventory_logs WHERE product_id = %s", (pid,))
        execute("DELETE FROM products WHERE id = %s", (pid,))
        execute("DELETE FROM customers WHERE id = %s", (cid,))

        # Verify stock did not drop to 80
        self.assertEqual(float(inv2), 90.0, f"Stock was double-deducted! Expected 90, got {inv2}")

    def test_duplicate_purchase_receive_bug(self):
        """Test if receiving an already received PO double-adds stock"""
        pid = execute_returning_id("INSERT INTO products (sku, name, default_price, average_cost) VALUES ('AUDIT-BUG-PO', 'Audit PO Prod', 10.0, 5.0) RETURNING id;")
        lid = query_one("SELECT id FROM locations LIMIT 1")['id']
        vid = execute_returning_id("INSERT INTO vendors (name) VALUES ('Audit Bug Vendor') RETURNING id;")
        execute("INSERT INTO inventory (product_id, location_id, quantity) VALUES (%s, %s, 50);", (pid, lid))

        post_data = {
            'vendor_id': vid,
            'location_id': lid,
            'product_id[]': [pid],
            'quantity[]': [20],
            'unit_cost[]': [5.0]
        }
        self.client.post('/purchases/create', data=post_data, follow_redirects=True)
        po = query_one("SELECT id FROM purchase_orders WHERE vendor_id = %s", (vid,))
        po_id = po['id']

        # 1st receive: 50 -> 70
        self.client.post(f'/purchases/{po_id}/receive', follow_redirects=True)
        inv1 = query_one("SELECT quantity FROM inventory WHERE product_id = %s", (pid,))['quantity']
        self.assertEqual(float(inv1), 70.0)

        # 2nd receive request (replay/double-click)
        self.client.post(f'/purchases/{po_id}/receive', follow_redirects=True)
        inv2 = query_one("SELECT quantity FROM inventory WHERE product_id = %s", (pid,))['quantity']

        # Clean up
        execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
        execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
        execute("DELETE FROM inventory_logs WHERE product_id = %s", (pid,))
        execute("DELETE FROM products WHERE id = %s", (pid,))
        execute("DELETE FROM vendors WHERE id = %s", (vid,))

        self.assertEqual(float(inv2), 70.0, f"Stock was double-added on PO receive! Expected 70, got {inv2}")

    def test_product_edit_preserves_unsubmitted_fields(self):
        """Test that editing product specifications does NOT erase description, default location, or pack sizes"""
        lid = query_one("SELECT id FROM locations LIMIT 1")['id']
        pid = execute_returning_id("""
            INSERT INTO products (sku, name, description, master_pack_qty, inner_pack_qty, default_location_id, default_price)
            VALUES ('AUDIT-PROD-EDIT', 'Prod Edit Test', 'Special Description', 24.0, 6.0, %s, 50.0)
            RETURNING id;
        """, (lid,))

        # Submit edit from detail page modal (which doesn't include description or pack size)
        edit_data = {
            'sku': 'AUDIT-PROD-EDIT',
            'name': 'Prod Edit Test Renamed',
            'barcode': '123456789',
            'category_id': '',
            'uom': 'pcs',
            'cost_price': '20.0',
            'default_price': '55.0',
            'reorder_point': '10',
            'reorder_quantity': '50'
        }
        self.client.post(f'/products/{pid}/edit', data=edit_data, follow_redirects=True)

        updated = query_one("SELECT * FROM products WHERE id = %s", (pid,))

        execute("DELETE FROM products WHERE id = %s", (pid,))

        self.assertEqual(updated['name'], 'Prod Edit Test Renamed')
        self.assertEqual(updated['description'], 'Special Description', f"Description was wiped! Got: {updated['description']}")
        self.assertEqual(float(updated['master_pack_qty']), 24.0, f"Master pack wiped! Expected 24, got {updated['master_pack_qty']}")
        self.assertEqual(float(updated['inner_pack_qty']), 6.0, f"Inner pack wiped! Expected 6, got {updated['inner_pack_qty']}")
        self.assertEqual(updated['default_location_id'], lid, f"Default location wiped! Expected {lid}, got {updated['default_location_id']}")

    def test_negative_transfer_quantity_rejected(self):
        """Test that negative transfer quantities are rejected"""
        pid = execute_returning_id("INSERT INTO products (sku, name, default_price) VALUES ('AUDIT-TRF-01', 'Trf Test', 10.0) RETURNING id;")
        locs = query_all("SELECT id FROM locations LIMIT 2")
        l1, l2 = locs[0]['id'], locs[1]['id']
        execute("INSERT INTO inventory (product_id, location_id, quantity) VALUES (%s, %s, 10);", (pid, l1))

        res = self.client.post('/inventory/transfers/create', data={
            'from_location_id': l1,
            'to_location_id': l2,
            'product_id': pid,
            'quantity': -5
        }, follow_redirects=True)

        inv_l1 = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (pid, l1))['quantity']

        execute("DELETE FROM stock_transfer_lines WHERE product_id = %s", (pid,))
        execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
        execute("DELETE FROM products WHERE id = %s", (pid,))

        self.assertEqual(float(inv_l1), 10.0, f"Negative transfer altered inventory! Expected 10, got {inv_l1}")

if __name__ == '__main__':
    unittest.main()
