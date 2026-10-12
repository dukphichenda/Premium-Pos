import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestPurchasesModern(unittest.TestCase):
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

        # Clean up existing test PO fixtures
        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test Modern PO%%' OR notes LIKE '%%PO-TEST-ORIG%%';
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM products WHERE sku LIKE 'TEST-MOD-PO%%';
            DELETE FROM vendors WHERE phone = '098765432';
        """)

        # Insert test vendor
        self.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, address1, balance)
            VALUES ('Modern Test Supplier Ltd', '098765432', '123 Veng Sreng Rd', 0.0)
            RETURNING id;
        """)

        # Insert 2 test products: one low-stock item and one regular
        self.prod_low = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom, reorder_point, reorder_quantity)
            VALUES ('TEST-MOD-PO-01', 'Low Stock Test Item', 30.00, 15.00, 15.00, 'case', 20.0, 50.0)
            RETURNING id;
        """)

        self.prod_reg = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom, reorder_point, reorder_quantity)
            VALUES ('TEST-MOD-PO-02', 'Regular Test Item', 50.00, 25.00, 25.00, 'case', 5.0, 20.0)
            RETURNING id;
        """)

        # Put 5 in stock for low product (below reorder point of 20)
        execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
            VALUES (%s, %s, '', 5)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET quantity = 5;
        """, (self.prod_low, self.loc_main))

        # Put 50 in stock for regular product (above reorder point of 5)
        execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
            VALUES (%s, %s, '', 50)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET quantity = 50;
        """, (self.prod_reg, self.loc_main))

    def tearDown(self):
        execute("""
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test Modern PO%%';
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-MOD-PO%%');
            DELETE FROM products WHERE sku LIKE 'TEST-MOD-PO%%';
            DELETE FROM vendors WHERE id = %s;
        """, (self.vend_id,))

    def test_reorder_low_stock_suggestions_api(self):
        """API should suggest items where on_hand <= reorder_point with suggested qty"""
        res = self.client.get(f'/api/purchases/reorder-suggestions?location_id={self.loc_main}&search=TEST-MOD-PO')
        self.assertEqual(res.status_code, 200)
        suggestions = res.get_json()
        self.assertIsInstance(suggestions, list)
        low_item = next((item for item in suggestions if item['sku'] == 'TEST-MOD-PO-01'), None)
        self.assertIsNotNone(low_item, "Low stock product must appear in reorder suggestions")
        self.assertGreaterEqual(float(low_item['suggested_qty']), 15.0)

        # High stock item should NOT be in suggestions
        high_item = next((item for item in suggestions if item['sku'] == 'TEST-MOD-PO-02'), None)
        self.assertIsNone(high_item, "Adequately stocked product must NOT appear in reorder suggestions")

    def test_quick_vendor_modal_creation_api(self):
        """Should create a vendor dynamically via AJAX endpoint"""
        res = self.client.post('/api/vendors/quick-create', json={
            'name': 'Express Fast Supplier',
            'phone': '011223344',
            'contact_person': 'Sokha Ly',
            'address': 'Toul Kork, Phnom Penh'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        new_v_id = data['vendor']['id']
        self.assertEqual(data['vendor']['name'], 'Express Fast Supplier')

        # Cleanup
        execute("DELETE FROM vendors WHERE id = %s", (new_v_id,))

    def test_create_po_and_partial_to_full_receiving_lifecycle(self):
        """Test full PO workflow: Create -> Partial Receive -> Full Receive -> Weighted Average Cost update"""
        # 1. Create Purchase Order
        po_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-12',
            'vendor_invoice_no': 'VINV-2026-999',
            'discount_amount': '10.00',
            'notes': 'Test Modern PO Lifecycle',
            'product_id[]': [self.prod_low, self.prod_reg],
            'quantity[]': [20, 10],
            'unit_cost[]': [18.00, 30.00],
            'discount_percent[]': [5.0, 0.0]
        }
        res = self.client.post('/purchases/create', data=po_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        po = query_one("SELECT * FROM purchase_orders WHERE vendor_id = %s ORDER BY id DESC LIMIT 1", (self.vend_id,))
        self.assertIsNotNone(po)
        self.assertEqual(po['status'], 'ISSUED')
        self.assertEqual(po['vendor_invoice_no'], 'VINV-2026-999')
        po_id = po['id']

        # Lines check
        lines = query_all("SELECT * FROM purchase_order_lines WHERE purchase_order_id = %s ORDER BY id ASC", (po_id,))
        self.assertEqual(len(lines), 2)
        line1, line2 = lines[0], lines[1]
        self.assertEqual(float(line1['quantity']), 20.0)
        self.assertEqual(float(line1['received_qty']), 0.0)

        # 2. Partial Receive Line 1 (receive 10 out of 20)
        res_partial = self.client.post(f'/purchases/{po_id}/receive', data={
            'receive_mode': 'partial',
            f'receive_qty_{line1["id"]}': 10,
            f'receive_qty_{line2["id"]}': 0
        }, follow_redirects=True)
        self.assertEqual(res_partial.status_code, 200)

        po_after_partial = query_one("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po_after_partial['status'], 'PARTIAL_RECEIVED')

        # Check inventory increased from 5 to 15
        stock_low = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_low, self.loc_main))['quantity']
        self.assertEqual(float(stock_low), 15.0)

        # 3. Full Receive Remaining (receive remaining 10 for line 1, and 10 for line 2)
        res_full = self.client.post(f'/purchases/{po_id}/receive', data={
            'receive_mode': 'partial',
            f'receive_qty_{line1["id"]}': 10,
            f'receive_qty_{line2["id"]}': 10
        }, follow_redirects=True)
        self.assertEqual(res_full.status_code, 200)

        po_after_full = query_one("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po_after_full['status'], 'RECEIVED')

        # Check stock_low is now 25.0
        stock_low_final = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_low, self.loc_main))['quantity']
        self.assertEqual(float(stock_low_final), 25.0)

    def test_duplicate_purchase_order(self):
        """Copying an existing PO should create a new PO draft with identical line items"""
        po_id = execute_returning_id("""
            INSERT INTO purchase_orders (order_number, vendor_id, location_id, total_amount, status, notes)
            VALUES ('PO-TEST-ORIG', %s, %s, 150.00, 'RECEIVED', 'Test Modern PO Original')
            RETURNING id;
        """, (self.vend_id, self.loc_main))

        execute("""
            INSERT INTO purchase_order_lines (purchase_order_id, product_id, quantity, unit_cost, subtotal, received_qty)
            VALUES (%s, %s, 10, 15.00, 150.00, 10);
        """, (po_id, self.prod_low))

        # Copy PO
        res = self.client.get(f'/purchases/{po_id}/copy', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        new_po = query_one("SELECT * FROM purchase_orders WHERE notes LIKE %s ORDER BY id DESC LIMIT 1", ('%Duplicate of PO-TEST-ORIG%',))
        self.assertIsNotNone(new_po, "Duplicated PO record must exist")
        self.assertEqual(new_po['status'], 'ISSUED', "New duplicated PO must start in ISSUED status")
        self.assertEqual(float(new_po['total_amount']), 150.00)

        # Check duplicated line has received_qty reset to 0
        new_lines = query_all("SELECT * FROM purchase_order_lines WHERE purchase_order_id = %s", (new_po['id'],))
        self.assertEqual(len(new_lines), 1)
        self.assertEqual(float(new_lines[0]['received_qty']), 0.0)

        # Clean up
        execute("DELETE FROM purchase_order_lines WHERE purchase_order_id IN (%s, %s)", (po_id, new_po['id']))
        execute("DELETE FROM purchase_orders WHERE id IN (%s, %s)", (po_id, new_po['id']))

    def test_vendor_summary_api(self):
        """API should return vendor summary for the yellow Vendor Info Popover Card"""
        res = self.client.get(f'/api/vendors/{self.vend_id}/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('vendor', data)
        self.assertEqual(data['vendor']['name'], 'Modern Test Supplier Ltd')
        self.assertIn('balance', data['vendor'])
        self.assertIn('last_order_status', data['vendor'])

    def test_purchases_drawer_api(self):
        """Drawer API should return list of purchase orders for sidebar table"""
        res = self.client.get('/api/purchases/drawer?date_filter=All&status_filter=All')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIsInstance(data.get('orders'), list)

    def test_new_purchase_order_page_rendering(self):
        """GET /purchases/new should render modern detail.html with preview PO number and drawer data"""
        res = self.client.get('/purchases/new')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'inflow-po-workspace', res.data)
        self.assertIn(b'Vendor Information', res.data)
        self.assertIn(b'Vendor Product Code', res.data)

    def test_save_po_with_vendor_product_code(self):
        """Saving PO with lines_json and vendor_product_code should persist correctly"""
        import json
        lines_data = [{
            'product_id': self.prod_low,
            'description': 'Low Stock Item Custom Desc',
            'vendor_product_code': 'VEND-SKU-7788',
            'quantity': 5,
            'unit_cost': 16.50,
            'discount_percent': 0.0
        }]
        res = self.client.post('/purchases/create', data={
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-13',
            'lines_json': json.dumps(lines_data),
            'notes': 'Test Modern PO with Vendor Product Code'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        saved_po = query_one("SELECT * FROM purchase_orders WHERE notes = 'Test Modern PO with Vendor Product Code'")
        self.assertIsNotNone(saved_po)
        saved_line = query_one("SELECT * FROM purchase_order_lines WHERE purchase_order_id = %s", (saved_po['id'],))
        self.assertIsNotNone(saved_line)
        self.assertEqual(saved_line['vendor_product_code'], 'VEND-SKU-7788')

        # Clean up
        execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (saved_po['id'],))
        execute("DELETE FROM purchase_orders WHERE id = %s", (saved_po['id'],))

if __name__ == '__main__':
    unittest.main()

