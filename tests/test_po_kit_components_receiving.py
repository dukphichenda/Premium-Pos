import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestPOKitComponentsReceiving(unittest.TestCase):
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

        loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")
        cls.loc_id = loc['id'] if loc else 1

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

        # Clean up any previous test fixtures
        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM purchase_orders WHERE notes LIKE '%%TEST_PO_KIT%%' OR order_number LIKE 'PO-TEST-KIT-%%';
            DELETE FROM product_boms WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM products WHERE sku LIKE 'TEST-PO-KIT-%%';
            DELETE FROM vendors WHERE phone = '099887766';
        """)

        # 1. Create vendor
        self.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, address1, balance)
            VALUES ('Kit Test Vendor', '099887766', 'Phnom Penh', 0.0)
            RETURNING id;
        """)

        # 2. Create Component A (e.g. Lid)
        self.comp_a = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom)
            VALUES ('TEST-PO-KIT-COMP-A', 'Component A (Lid)', 0.10, 0.02, 0.02, 'pcs.')
            RETURNING id;
        """)

        # 3. Create Component B (e.g. Bowl)
        self.comp_b = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom)
            VALUES ('TEST-PO-KIT-COMP-B', 'Component B (Bowl)', 0.15, 0.04, 0.04, 'pcs.')
            RETURNING id;
        """)

        # 4. Create Parent Kit Product (e.g. Bowl + Lid Kit, purchasing UOM = cases, ratio = 100 pcs/case)
        self.parent_kit = execute_returning_id("""
            INSERT INTO products (
                sku, name, default_price, standard_cost, average_cost, uom,
                purchasing_uom, purchasing_uom_ratio_std, combine_type
            )
            VALUES (
                'TEST-PO-KIT-PARENT', 'Bowl + Lid Combo Kit', 0.50, 0.06, 0.06, 'pcs.',
                'cases', 100.0, 'multi'
            )
            RETURNING id;
        """)

        # 5. Link BOM components (1 Component A + 1 Component B per Kit)
        execute("""
            INSERT INTO product_boms (product_id, component_product_id, quantity, cost)
            VALUES (%s, %s, 1.0, 0.02);
            INSERT INTO product_boms (product_id, component_product_id, quantity, cost)
            VALUES (%s, %s, 1.0, 0.04);
        """, (self.parent_kit, self.comp_a, self.parent_kit, self.comp_b))

    def tearDown(self):
        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM purchase_orders WHERE notes LIKE '%%TEST_PO_KIT%%' OR order_number LIKE 'PO-TEST-KIT-%%';
            DELETE FROM product_boms WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-PO-KIT-%%');
            DELETE FROM products WHERE sku LIKE 'TEST-PO-KIT-%%';
            DELETE FROM vendors WHERE phone = '099887766';
        """)

    def test_po_kit_receiving_and_unreceiving_stock_routing(self):
        # 1. Create a Purchase Order for 5 cases of the Kit product ($6.00/case)
        # 5 cases * 100 pcs/case = 500 kits -> 500 of Comp A and 500 of Comp B
        po_id = execute_returning_id("""
            INSERT INTO purchase_orders (
                order_number, vendor_id, location_id, status, notes, subtotal, total_amount, order_date
            ) VALUES (
                'PO-TEST-KIT-001', %s, %s, 'ISSUED', 'TEST_PO_KIT purchase', 30.00, 30.00, CURRENT_DATE
            ) RETURNING id;
        """, (self.vend_id, self.loc_id))

        line_id = execute_returning_id("""
            INSERT INTO purchase_order_lines (
                purchase_order_id, product_id, quantity, unit_cost, uom, received_qty, subtotal
            ) VALUES (
                %s, %s, 5.0, 6.00, 'cases', 0.0, 30.00
            ) RETURNING id;
        """, (po_id, self.parent_kit))

        # Check inventory before receiving: all 0
        inv_parent_before = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.parent_kit, self.loc_id))
        inv_a_before = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_a, self.loc_id))
        inv_b_before = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_b, self.loc_id))
        self.assertEqual(float(inv_parent_before['q']) if inv_parent_before else 0.0, 0.0)
        self.assertEqual(float(inv_a_before['q']) if inv_a_before else 0.0, 0.0)
        self.assertEqual(float(inv_b_before['q']) if inv_b_before else 0.0, 0.0)

        # 2. Receive the PO (receive_all=True)
        resp = self.client.post(f'/purchases/{po_id}/receive', data={'receive_all': '1'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # 3. Verify stock routing:
        # Parent Kit stock must NOT be added to inventory!
        inv_parent_after = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.parent_kit, self.loc_id))
        self.assertEqual(float(inv_parent_after['q']) if inv_parent_after else 0.0, 0.0, "Parent kit must NOT receive inventory stock")

        # Component A stock must be 500 (5 cases * 100 * 1.0)
        inv_a_after = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_a, self.loc_id))
        self.assertIsNotNone(inv_a_after)
        self.assertEqual(float(inv_a_after['q']), 500.0, "Component A must receive 500 pcs")

        # Component B stock must be 500 (5 cases * 100 * 1.0)
        inv_b_after = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_b, self.loc_id))
        self.assertIsNotNone(inv_b_after)
        self.assertEqual(float(inv_b_after['q']), 500.0, "Component B must receive 500 pcs")

        # Verify PO line received_qty and PO status
        po = query_one("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po['status'], 'RECEIVED')

        line = query_one("SELECT received_qty FROM purchase_order_lines WHERE id = %s", (line_id,))
        self.assertEqual(float(line['received_qty']), 5.0)

        # 4. Verify inventory_logs:
        logs_parent = query_all("SELECT * FROM inventory_logs WHERE product_id = %s AND reference_id = 'PO-TEST-KIT-001'", (self.parent_kit,))
        self.assertEqual(len(logs_parent), 0, "No inventory log should be written to parent kit")

        logs_comp_a = query_all("SELECT * FROM inventory_logs WHERE product_id = %s AND reference_id = 'PO-TEST-KIT-001'", (self.comp_a,))
        self.assertEqual(len(logs_comp_a), 1)
        self.assertEqual(logs_comp_a[0]['movement_type'], 'PO_RECEIVE')
        self.assertEqual(float(logs_comp_a[0]['quantity']), 500.0)
        self.assertIn('Kit Component', logs_comp_a[0]['reason'])

        logs_comp_b = query_all("SELECT * FROM inventory_logs WHERE product_id = %s AND reference_id = 'PO-TEST-KIT-001'", (self.comp_b,))
        self.assertEqual(len(logs_comp_b), 1)
        self.assertEqual(logs_comp_b[0]['movement_type'], 'PO_RECEIVE')
        self.assertEqual(float(logs_comp_b[0]['quantity']), 500.0)
        self.assertIn('Kit Component', logs_comp_b[0]['reason'])

        # 5. Verify Purchase History on Component A & B:
        resp_a = self.client.get(f'/products/{self.comp_a}', follow_redirects=True)
        self.assertEqual(resp_a.status_code, 200)
        content_a = resp_a.get_data(as_text=True)
        self.assertIn('PO-TEST-KIT-001', content_a)
        self.assertIn('TEST-PO-KIT-PARENT', content_a)

        # 6. Test unreceive_purchase:
        resp_unfulfill = self.client.post(f'/purchases/{po_id}/unfulfill', follow_redirects=True)
        self.assertEqual(resp_unfulfill.status_code, 200)

        # Check PO status and line received_qty
        po_unfulfilled = query_one("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po_unfulfilled['status'], 'ISSUED')

        line_unfulfilled = query_one("SELECT received_qty FROM purchase_order_lines WHERE id = %s", (line_id,))
        self.assertEqual(float(line_unfulfilled['received_qty']), 0.0)

        # Verify component stock reversed to 0
        inv_a_unfulfilled = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_a, self.loc_id))
        inv_b_unfulfilled = query_one("SELECT COALESCE(quantity, 0) as q FROM inventory WHERE product_id = %s AND location_id = %s", (self.comp_b, self.loc_id))
        self.assertEqual(float(inv_a_unfulfilled['q']), 0.0)
        self.assertEqual(float(inv_b_unfulfilled['q']), 0.0)

        # Verify unreceive log written for components
        unreceive_logs_a = query_all("SELECT * FROM inventory_logs WHERE product_id = %s AND movement_type = 'PO_UNRECEIVE'", (self.comp_a,))
        self.assertEqual(len(unreceive_logs_a), 1)
        self.assertEqual(float(unreceive_logs_a[0]['quantity']), 500.0)

if __name__ == '__main__':
    unittest.main()
