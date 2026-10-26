import unittest
import json
from decimal import Decimal
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from database import query_one, query_all, execute, get_db_cursor


class TestPoExpenseSync(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

    def test_po_expense_sync_and_api(self):
        # 1. Fetch an existing product to use in PO
        product = query_one("SELECT id, sku, name, default_price, standard_cost FROM products WHERE is_active = TRUE LIMIT 1")
        self.assertIsNotNone(product, "Active product should exist")
        pid = product['id']

        # Ensure vendor exists
        vendor = query_one("SELECT id FROM vendors LIMIT 1")
        if not vendor:
            vendor_id = execute_returning_id("INSERT INTO vendors (name, balance) VALUES ('Test Vendor Sync', 0) RETURNING id")
        else:
            vendor_id = vendor['id']

        location = query_one("SELECT id FROM locations LIMIT 1")
        location_id = location['id'] if location else 1

        # 2. Create a test PO with 2 items at cost $30 each -> Subtotal $60.00
        po_create_data = {
            'vendor_id': vendor_id,
            'location_id': location_id,
            'order_date': '2026-10-26',
            'carrier': '',
            'notes': 'Test Sync PO',
            'lines_json': json.dumps([{
                'product_id': pid,
                'description': product['name'],
                'vendor_product_code': '',
                'quantity': 2,
                'unit_cost': 30.0,
                'discount_percent': 0,
                'uom': 'pcs.'
            }])
        }

        resp = self.client.post('/purchases/create', data=po_create_data, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)
        res_data = resp.get_json()
        self.assertTrue(res_data.get('success'))
        po_id = res_data.get('po_id')
        po_order_number = res_data.get('order_number')
        self.assertIsNotNone(po_id)

        try:
            # Verify PO total is 60.00
            po = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
            self.assertAlmostEqual(float(po['total_amount']), 60.0, places=2)

            # Check /api/purchases/<id>/data initially has linked_expense = None
            api_resp = self.client.get(f"/api/purchases/{po_id}/data")
            self.assertEqual(api_resp.status_code, 200)
            api_json = api_resp.get_json()
            self.assertTrue(api_json.get('success'))
            self.assertIsNone(api_json.get('linked_expense'))

            # 3. Add to expenses ($60.00)
            exp_data = {
                'item': f"{po_order_number} - Test Vendor",
                'expense_date': '2026-10-26',
                'amount': 60.0,
                'category': 'Purchases',
                'paid_by': 'ABA Bank',
                'month_key': '2026-10',
                'notes': f"Purchase Order: {po_order_number} • Vendor: Test Vendor"
            }
            exp_resp = self.client.post(f"/purchases/{po_id}/add-to-expenses", json=exp_data, headers={'X-Requested-With': 'XMLHttpRequest'})
            self.assertEqual(exp_resp.status_code, 200)
            exp_json = exp_resp.get_json()
            self.assertTrue(exp_json.get('success'))
            exp_id = exp_json.get('expense_id')
            self.assertIsNotNone(exp_id)

            # Verify in DB
            db_exp = query_one("SELECT * FROM expenses WHERE id = %s", (exp_id,))
            self.assertAlmostEqual(float(db_exp['total_price']), 60.0, places=2)

            # Check /api/purchases/<id>/data now returns linked_expense with 60.00
            api_resp2 = self.client.get(f"/api/purchases/{po_id}/data")
            api_json2 = api_resp2.get_json()
            self.assertIsNotNone(api_json2.get('linked_expense'))
            self.assertEqual(api_json2['linked_expense']['id'], exp_id)
            self.assertAlmostEqual(api_json2['linked_expense']['total_price'], 60.0, places=2)

            # 4. Now update PO detail to 3 items at cost $35 each -> Subtotal $105.00
            po_update_data = {
                'vendor_id': vendor_id,
                'location_id': location_id,
                'order_date': '2026-10-26',
                'carrier': '',
                'notes': 'Test Sync PO Updated',
                'lines_json': json.dumps([{
                    'product_id': pid,
                    'description': product['name'],
                    'vendor_product_code': '',
                    'quantity': 3,
                    'unit_cost': 35.0,
                    'discount_percent': 0,
                    'uom': 'pcs.'
                }])
            }
            up_resp = self.client.post(f"/purchases/{po_id}/save", data=po_update_data, headers={'X-Requested-With': 'XMLHttpRequest'})
            self.assertEqual(up_resp.status_code, 200)
            up_json = up_resp.get_json()
            self.assertTrue(up_json.get('success'))
            self.assertAlmostEqual(float(up_json.get('total_amount')), 105.0, places=2)

            # 5. Verify the linked expense in expenses table automatically updated to $105.00!
            db_exp_after = query_one("SELECT * FROM expenses WHERE id = %s", (exp_id,))
            self.assertAlmostEqual(float(db_exp_after['total_price']), 105.0, places=2, msg="Linked expense total_price should update to 105.00")
            self.assertAlmostEqual(float(db_exp_after['unit_price']), 105.0, places=2, msg="Linked expense unit_price should update to 105.00")

            # Check /api/purchases/<id>/data returns linked_expense with 105.00
            api_resp3 = self.client.get(f"/api/purchases/{po_id}/data")
            api_json3 = api_resp3.get_json()
            self.assertIsNotNone(api_json3.get('linked_expense'))
            self.assertAlmostEqual(api_json3['linked_expense']['total_price'], 105.0, places=2)

            # 6. Test re-submitting Add to Expenses modal updates the SAME record (no duplicates)
            exp_data_update = {
                'item': f"{po_order_number} - Test Vendor Renamed",
                'expense_date': '2026-10-26',
                'amount': 105.0,
                'category': 'Supplies',
                'paid_by': 'Cash',
                'month_key': '2026-10',
                'notes': f"Purchase Order: {po_order_number} • Vendor: Test Vendor"
            }
            exp_resp2 = self.client.post(f"/purchases/{po_id}/add-to-expenses", json=exp_data_update, headers={'X-Requested-With': 'XMLHttpRequest'})
            self.assertEqual(exp_resp2.status_code, 200)
            exp_json2 = exp_resp2.get_json()
            self.assertTrue(exp_json2.get('success'))
            self.assertEqual(exp_json2.get('expense_id'), exp_id, "Should update the same existing expense record")

            all_exps = query_all("SELECT id FROM expenses WHERE notes ILIKE %s OR item ILIKE %s", (f"%{po_order_number}%", f"%{po_order_number}%"))
            self.assertEqual(len(all_exps), 1, "There should be exactly 1 expense row for this PO, never duplicates")

            # 7. Check RULE 1: Product catalog fields were not mutated
            p_after = query_one("SELECT id, sku, name, default_price, standard_cost FROM products WHERE id = %s", (pid,))
            self.assertEqual(p_after['sku'], product['sku'])
            self.assertEqual(p_after['name'], product['name'])
            self.assertEqual(p_after['default_price'], product['default_price'])
            self.assertEqual(p_after['standard_cost'], product['standard_cost'])

        finally:
            # Clean up test records
            execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (po_id,))
            execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
            execute("DELETE FROM expenses WHERE notes ILIKE %s OR item ILIKE %s", (f"%{po_order_number}%", f"%{po_order_number}%"))


if __name__ == '__main__':
    unittest.main()
