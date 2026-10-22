import unittest
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestPoMoveAndDeleteItems(unittest.TestCase):
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

        cls.loc_main = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")['id']

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-MOVE%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test PO Move Reorder%%';
            DELETE FROM products WHERE sku LIKE 'TEST-PO-MOVE%%';
            DELETE FROM vendors WHERE phone = '0123456789_move';
        """)

        self.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, address1, balance)
            VALUES ('PO Move Reorder Supplier', '0123456789_move', 'Phnom Penh', 0.0)
            RETURNING id;
        """)

        self.prod_a = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom)
            VALUES ('TEST-PO-MOVE-A', 'Product Alpha', 10.00, 5.00, 5.00, 'case')
            RETURNING id;
        """)

        self.prod_b = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom)
            VALUES ('TEST-PO-MOVE-B', 'Product Beta', 20.00, 12.00, 12.00, 'case')
            RETURNING id;
        """)

    def tearDown(self):
        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-MOVE%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test PO Move Reorder%%';
            DELETE FROM products WHERE sku LIKE 'TEST-PO-MOVE%%';
            DELETE FROM vendors WHERE phone = '0123456789_move';
        """)

    def test_po_detail_template_contains_move_and_delete_controls(self):
        """Verify PO detail HTML contains selector column, move up/down buttons, delete cross button, and action bar."""
        po_id = execute_returning_id("""
            INSERT INTO purchase_orders (order_number, vendor_id, location_id, order_date, status, payment_status, total_amount, balance_due, notes)
            VALUES ('PO-TEST-MOVE-01', %s, %s, CURRENT_DATE, 'ISSUED', 'UNPAID', 170.0, 170.0, 'Test PO Move Reorder 01')
            RETURNING id;
        """, (self.vend_id, self.loc_main))

        execute("""
            INSERT INTO purchase_order_lines (purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal, uom)
            VALUES (%s, 1, %s, 'Product Alpha', 10, 5.0, 50.0, 'case'),
                   (%s, 2, %s, 'Product Beta', 10, 12.0, 120.0, 'case');
        """, (po_id, self.prod_a, po_id, self.prod_b))

        resp = self.client.get(f"/purchases/{po_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Master select-all checkbox
        self.assertIn('id="masterSelectAllPoLines"', html)
        self.assertIn('toggleSelectAllPoLines', html)

        # 2. Row controls
        self.assertIn('class="line-select-chk"', html)
        self.assertIn('class="line-delete-cross-btn"', html)
        self.assertIn('class="po-line-move-btn"', html)
        self.assertIn('class="po-line-move-stack"', html)

        # 3. Grid action buttons bar (matching SO Page)
        self.assertIn('class="inflow-grid-actions-bar"', html)
        self.assertIn('moveSelectedPoLineUp', html)
        self.assertIn('moveSelectedPoLineDown', html)
        self.assertIn('deleteSelectedPoLine', html)
        self.assertIn('deleteSpecificPoLine', html)
        self.assertIn('movePoLineUp', html)
        self.assertIn('movePoLineDown', html)
        self.assertIn('resequencePoLineIndices', html)

    def test_po_reordering_persistence_on_save(self):
        """Verify reordering lines (moving Beta up, Alpha down) persists line_num and loads in new order."""
        po_id = execute_returning_id("""
            INSERT INTO purchase_orders (order_number, vendor_id, location_id, order_date, status, payment_status, total_amount, balance_due, notes)
            VALUES ('PO-TEST-MOVE-02', %s, %s, CURRENT_DATE, 'ISSUED', 'UNPAID', 170.0, 170.0, 'Test PO Move Reorder 02')
            RETURNING id;
        """, (self.vend_id, self.loc_main))

        # Initial order: Alpha (line 1), Beta (line 2)
        execute("""
            INSERT INTO purchase_order_lines (purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal, uom)
            VALUES (%s, 1, %s, 'Product Alpha', 10, 5.0, 50.0, 'case'),
                   (%s, 2, %s, 'Product Beta', 10, 12.0, 120.0, 'case');
        """, (po_id, self.prod_a, po_id, self.prod_b))

        # Reorder via update_purchase: Beta first, Alpha second
        post_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-22',
            'notes': 'Test PO Move Reorder 02',
            'lines': [
                {
                    'product_id': self.prod_b,
                    'description': 'Product Beta',
                    'vendor_product_code': 'VPC-B',
                    'quantity': 10,
                    'unit_cost': 12.0,
                    'discount_percent': 0,
                    'uom': 'case'
                },
                {
                    'product_id': self.prod_a,
                    'description': 'Product Alpha',
                    'vendor_product_code': 'VPC-A',
                    'quantity': 10,
                    'unit_cost': 5.0,
                    'discount_percent': 0,
                    'uom': 'case'
                }
            ]
        }

        resp = self.client.post(
            f"/purchases/{po_id}/save",
            data=json.dumps(post_data),
            content_type='application/json',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(resp.status_code, 200)

        # Check DB lines order
        lines_db = query_all("SELECT product_id, line_num FROM purchase_order_lines WHERE purchase_order_id = %s ORDER BY line_num ASC", (po_id,))
        self.assertEqual(len(lines_db), 2)
        self.assertEqual(lines_db[0]['product_id'], self.prod_b)
        self.assertEqual(lines_db[0]['line_num'], 1)
        self.assertEqual(lines_db[1]['product_id'], self.prod_a)
        self.assertEqual(lines_db[1]['line_num'], 2)

        # Verify detail page / JSON endpoint returns lines in reordered sequence
        resp_json = self.client.get(f"/api/purchases/{po_id}/data")
        self.assertEqual(resp_json.status_code, 200)
        data = resp_json.get_json()
        self.assertEqual(data['lines'][0]['product_id'], self.prod_b)
        self.assertEqual(data['lines'][1]['product_id'], self.prod_a)

    def test_po_delete_line_item_on_save(self):
        """Verify deleting a line item updates DB lines upon saving."""
        po_id = execute_returning_id("""
            INSERT INTO purchase_orders (order_number, vendor_id, location_id, order_date, status, payment_status, total_amount, balance_due, notes)
            VALUES ('PO-TEST-MOVE-03', %s, %s, CURRENT_DATE, 'ISSUED', 'UNPAID', 170.0, 170.0, 'Test PO Move Reorder 03')
            RETURNING id;
        """, (self.vend_id, self.loc_main))

        execute("""
            INSERT INTO purchase_order_lines (purchase_order_id, line_num, product_id, description, quantity, unit_cost, subtotal, uom)
            VALUES (%s, 1, %s, 'Product Alpha', 10, 5.0, 50.0, 'case'),
                   (%s, 2, %s, 'Product Beta', 10, 12.0, 120.0, 'case');
        """, (po_id, self.prod_a, po_id, self.prod_b))

        # Save with only Product Alpha
        post_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-22',
            'notes': 'Test PO Move Reorder 03',
            'lines': [
                {
                    'product_id': self.prod_a,
                    'description': 'Product Alpha',
                    'vendor_product_code': 'VPC-A',
                    'quantity': 10,
                    'unit_cost': 5.0,
                    'discount_percent': 0,
                    'uom': 'case'
                }
            ]
        }

        resp = self.client.post(
            f"/purchases/{po_id}/save",
            data=json.dumps(post_data),
            content_type='application/json',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(resp.status_code, 200)

        lines_db = query_all("SELECT product_id, line_num FROM purchase_order_lines WHERE purchase_order_id = %s ORDER BY line_num ASC", (po_id,))
        self.assertEqual(len(lines_db), 1)
        self.assertEqual(lines_db[0]['product_id'], self.prod_a)

if __name__ == '__main__':
    unittest.main()
