import unittest
import json
from app import app
from database import query_one, query_all, execute, execute_returning_id

class TestPoAutosaveAndPopups(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Create temporary vendor and product
        self.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, balance)
            VALUES ('Test AutoSave Vendor', '012345678', 0)
            RETURNING id;
        """)

        self.prod_id = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, uom)
            VALUES ('TEST-AUTOSAVE-PO-01', 'AutoSave Product Item', 10.00, 5.00, 'case')
            RETURNING id;
        """)

        self.loc_id = execute_returning_id("""
            SELECT id FROM locations LIMIT 1;
        """) or 1

    def tearDown(self):
        execute("DELETE FROM purchase_order_lines WHERE purchase_order_id IN (SELECT id FROM purchase_orders WHERE vendor_id = %s)", (self.vend_id,))
        execute("DELETE FROM purchase_orders WHERE vendor_id = %s", (self.vend_id,))
        execute("DELETE FROM products WHERE id = %s", (self.prod_id,))
        execute("DELETE FROM vendors WHERE id = %s", (self.vend_id,))

    def test_ajax_create_purchase_auto_save(self):
        """Creating PO via AJAX with lines_json should auto-save and return po_id, order_number, total_amount"""
        lines_data = [{
            'product_id': self.prod_id,
            'description': 'AutoSave Product Item',
            'vendor_product_code': 'VEND-CODE-1',
            'quantity': 10,
            'unit_cost': 5.00,
            'discount_percent': 0.0,
            'uom': 'case'
        }]

        res = self.client.post('/purchases/create', data={
            'vendor_id': self.vend_id,
            'location_id': self.loc_id,
            'order_date': '2026-11-19',
            'lines_json': json.dumps(lines_data),
            'notes': 'Auto-saved test order'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('po_id', data)
        self.assertIn('order_number', data)
        self.assertEqual(float(data.get('total_amount')), 50.0)

        # Verify database
        po = query_one("SELECT * FROM purchase_orders WHERE id = %s", (data['po_id'],))
        self.assertIsNotNone(po)
        self.assertEqual(float(po['total_amount']), 50.0)

        # Lines in database
        lines = query_all("SELECT * FROM purchase_order_lines WHERE purchase_order_id = %s", (data['po_id'],))
        self.assertEqual(len(lines), 1)
        self.assertEqual(float(lines[0]['quantity']), 10.0)
        self.assertEqual(float(lines[0]['unit_cost']), 5.0)

    def test_ajax_update_purchase_auto_save(self):
        """Updating PO via AJAX with lines_json should update lines and return po_id, order_number, total_amount"""
        # Create initial PO
        lines_initial = [{
            'product_id': self.prod_id,
            'description': 'AutoSave Item Initial',
            'quantity': 4,
            'unit_cost': 5.00,
            'discount_percent': 0.0,
            'uom': 'case'
        }]
        res_init = self.client.post('/purchases/create', data={
            'vendor_id': self.vend_id,
            'location_id': self.loc_id,
            'order_date': '2026-11-19',
            'lines_json': json.dumps(lines_initial)
        }, headers={'X-Requested-With': 'XMLHttpRequest'})
        po_id = res_init.get_json()['po_id']

        # Update via AJAX
        lines_updated = [{
            'product_id': self.prod_id,
            'description': 'AutoSave Item Updated',
            'quantity': 8,
            'unit_cost': 7.50,
            'discount_percent': 0.0,
            'uom': 'case'
        }]
        res_upd = self.client.post(f'/purchases/{po_id}/save', data={
            'vendor_id': self.vend_id,
            'location_id': self.loc_id,
            'order_date': '2026-11-19',
            'lines_json': json.dumps(lines_updated),
            'notes': 'Updated notes via auto-save'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        self.assertEqual(res_upd.status_code, 200)
        data = res_upd.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('po_id'), po_id)
        self.assertEqual(float(data.get('total_amount')), 60.0) # 8 * 7.50 = 60.0

        # Verify database
        po = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(float(po['total_amount']), 60.0)
        self.assertEqual(po['notes'], 'Updated notes via auto-save')

    def test_ajax_create_requires_vendor(self):
        """Creating PO via AJAX without vendor should return 400 error message"""
        res = self.client.post('/purchases/create', data={
            'vendor_id': '',
            'location_id': self.loc_id
        }, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get('success'))
        self.assertIn('vendor', data.get('message', '').lower())

    def test_template_and_js_specifications(self):
        """Detail template and app.js must have auto-save and disabled backdrop dismiss"""
        with open('static/js/app.js', 'r', encoding='utf-8') as f:
            app_js = f.read()
        self.assertNotIn('overlay.classList.remove(\'active\')', app_js)

        with open('templates/purchases/detail.html', 'r', encoding='utf-8') as f:
            detail_html = f.read()
        self.assertIn('autoSavePoOrder', detail_html)
        self.assertIn('openReceiveModal', detail_html)
        self.assertIn('openPaymentModal', detail_html)
        self.assertIn('openAddToExpensesModal', detail_html)
        self.assertNotIn('onclick="if(event.target === this) closeAddToExpensesModal()"', detail_html)

if __name__ == '__main__':
    unittest.main()
