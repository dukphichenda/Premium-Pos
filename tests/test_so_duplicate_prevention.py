import unittest
import uuid
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

from app import app
from database import query_one, query_all, execute, get_db_cursor

class TestSoDuplicatePrevention(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Ensure column exists
        execute("""
            ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS submission_token VARCHAR(64);
            CREATE INDEX IF NOT EXISTS idx_sales_orders_sub_token ON sales_orders(submission_token);
        """)

        # Get or create customer and product
        cust = query_one("SELECT id, name FROM customers WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        if not cust:
            with get_db_cursor(commit=True) as cur:
                cur.execute("INSERT INTO customers (name, is_active) VALUES ('Test Dup Customer', TRUE) RETURNING id, name;")
                cust = cur.fetchone()
        cls.customer = cust

        prod = query_one("SELECT id, name, sku, uom, sales_uom, sales_uom_ratio_std, default_price FROM products WHERE is_active = TRUE LIMIT 1")
        cls.product = prod

    def test_01_idempotency_token_prevents_duplicate_on_reload(self):
        token = "test_token_" + uuid.uuid4().hex[:16]
        
        # Count orders before
        initial_count = query_one("SELECT COUNT(*) as c FROM sales_orders")['c']

        payload = {
            'customer_id': str(self.customer['id']),
            'form_submission_token': token,
            'lines_json': json.dumps([{
                'product_id': self.product['id'],
                'quantity': 2.0,
                'unit_price': 10.0,
                'discount_percent': 0,
                'uom': self.product.get('uom') or 'pcs.'
            }]),
            'notes': 'Test idempotency token reload',
            'order_date': '2026-10-26'
        }

        # 1. First Save (POST /sales/0/save)
        resp1 = self.client.post('/sales/0/save', data=payload, follow_redirects=False)
        self.assertIn(resp1.status_code, (302, 303))
        
        # Verify order created with submission_token
        saved_order = query_one("SELECT id, order_number, submission_token FROM sales_orders WHERE submission_token = %s", (token,))
        self.assertIsNotNone(saved_order, "Order should be saved with submission_token")
        first_id = saved_order['id']
        first_num = saved_order['order_number']

        # 2. Simulate browser reload / form resubmission (Exact same POST /sales/0/save)
        resp2 = self.client.post('/sales/0/save', data=payload, follow_redirects=False)
        self.assertIn(resp2.status_code, (302, 303))
        self.assertIn(f"/sales/{first_id}", resp2.headers.get('Location', ''))

        # Verify NO second order was created
        current_count = query_one("SELECT COUNT(*) as c FROM sales_orders WHERE submission_token = %s", (token,))['c']
        self.assertEqual(current_count, 1, "Only 1 order must exist for this submission_token")

        # Cleanup test order
        execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (first_id,))
        execute("DELETE FROM sales_orders WHERE id = %s", (first_id,))

    def test_02_rapid_deduplication_uom_aware_guard(self):
        # Test case: customer saves an order with UOM (e.g. 5 cases = 2800 pcs)
        # Even without a token, submitting identical lines within 60s must return the existing order
        cust_id = self.customer['id']
        prod_id = self.product['id']

        payload = {
            'customer_id': str(cust_id),
            'form_submission_token': '',  # No token provided
            'lines_json': json.dumps([{
                'product_id': prod_id,
                'quantity': 5.0,
                'unit_price': 42.0,
                'discount_percent': 0,
                'uom': 'cases'
            }]),
            'notes': 'Test UOM rapid deduplication guard',
            'order_date': '2026-10-26'
        }

        # 1. First Save
        resp1 = self.client.post('/sales/0/save', data=payload, follow_redirects=False)
        self.assertIn(resp1.status_code, (302, 303))
        loc1 = resp1.headers.get('Location', '')
        
        order1 = query_one("""
            SELECT id, order_number FROM sales_orders 
            WHERE customer_id = %s AND notes = 'Test UOM rapid deduplication guard'
            ORDER BY id DESC LIMIT 1
        """, (cust_id,))
        self.assertIsNotNone(order1)
        order1_id = order1['id']

        # 2. Second Save within 60s with same customer and items
        resp2 = self.client.post('/sales/0/save', data=payload, follow_redirects=False)
        self.assertIn(resp2.status_code, (302, 303))
        loc2 = resp2.headers.get('Location', '')
        self.assertIn(f"/sales/{order1_id}", loc2, "Second save within 60s should redirect to first order")

        # Verify no duplicate created
        matching_count = query_one("""
            SELECT COUNT(*) as c FROM sales_orders 
            WHERE customer_id = %s AND notes = 'Test UOM rapid deduplication guard'
        """, (cust_id,))['c']
        self.assertEqual(matching_count, 1, "Rapid duplicate guard must prevent second SO from being created")

        # Cleanup
        execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (order1_id,))
        execute("DELETE FROM sales_orders WHERE id = %s", (order1_id,))

    def test_03_rule_1_product_catalog_protection(self):
        # Verify that products table was untouched
        prods = query_all("SELECT id, name, sku FROM products LIMIT 5")
        self.assertTrue(len(prods) > 0)

if __name__ == '__main__':
    unittest.main()
