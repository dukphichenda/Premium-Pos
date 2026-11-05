import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from app import app
from database import query_one, get_db_cursor, resync_all_sequences

class TestPosReceiptCashierAndVatTin(unittest.TestCase):
    def setUp(self):
        self.created_so_ids = []

    def tearDown(self):
        if hasattr(self, 'created_so_ids') and self.created_so_ids:
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_order_versions WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_orders WHERE id = ANY(%s)", (self.created_so_ids,))
            resync_all_sequences()
    def test_pos_receipt_no_vattin_and_cashier_name(self):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'chenda'
                sess['display_name'] = 'Main Store Administrator'
                sess['role'] = 'main_admin'
                sess['branch_id'] = None

            resp = client.get('/branches/1/pos')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)

            # 1. Verify VATTIN is NOT in the rendered receipt
            self.assertNotIn('VATTIN', html)
            self.assertNotIn('លេខអត្តសញ្ញាណ', html)

            # 2. Verify Cashier Name displays the login name 'chenda' (not hardcoded 'Kiev Kumpeak')
            self.assertIn('id="recCashierName"', html)
            self.assertIn('>chenda</strong>', html)
            self.assertIn('class="pos-cashier-name">chenda<', html)

            # 3. Verify Payment method, Received, Change rows are deleted from POS receipt
            self.assertNotIn('វិធីទូទាត់ / Payment Method:', html)
            self.assertNotIn('ប្រាក់ទទួលបាន / Received:', html)
            self.assertNotIn('ប្រាក់អាប់ / Change Returned:', html)
            self.assertNotIn('id="recMethod"', html)
            self.assertNotIn('id="recPaidRow"', html)
            self.assertNotIn('id="recChangeRow"', html)

            # 4. Verify Thank You greeting & Powered by footer are deleted
            self.assertNotIn('សូមអរគុណ! សូមអញ្ជើញមកវិញ!', html)
            self.assertNotIn('Powered by inFlow Premium POS', html)

            # 5. Verify Rate & Return policy remain intact
            self.assertIn('អត្រាប្តូរប្រាក់ / Rate:', html)
            self.assertIn('* សូមពិនិត្យទំនិញ និងប្រាក់អាប់មុនពេលចាកចេញ *', html)
            self.assertIn('(Please check your items & change before leaving)', html)

            # 6. Verify 80mm full width print styles and all-bold receipt text
            self.assertIn('size: 80mm auto;', html)
            self.assertIn('font-weight: 700 !important;', html)
            self.assertIn('.pos-container,', html)
            self.assertIn('posThermalPrintFrame', html)
            self.assertIn('72mm', html)

            # 7. Verify Date & Invoice number have separate clean rows and DD/MM/YYYY formatting
            self.assertIn('id="recOrderNum"', html)
            self.assertIn('id="recDate"', html)
            self.assertIn('getPosFormattedNow', html)

    def test_pos_receipt_cashier_custom_user(self):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 99
                sess['username'] = 'sreynich'
                sess['display_name'] = 'Sreynich POS'
                sess['role'] = 'branch_cashier'
                sess['branch_id'] = 1

            resp = client.get('/branches/1/pos')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)

            # 1. No VATTIN
            self.assertNotIn('VATTIN', html)

            # 2. Cashier Name is 'sreynich'
            self.assertIn('id="recCashierName"', html)
            self.assertIn('>sreynich</strong>', html)
            self.assertIn('class="pos-cashier-name">sreynich<', html)

    def test_pos_checkout_returns_cashier_name(self):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 6
                sess['username'] = 'veasna'
                sess['display_name'] = 'Samrith Veasna'
                sess['role'] = 'main_admin'
                sess['branch_id'] = None

            # Fetch a valid product ID
            p = query_one("SELECT id FROM products LIMIT 1")
            prod_id = p['id'] if p else 248

            checkout_payload = {
                'items': [{
                    'product_id': prod_id,
                    'quantity': 1,
                    'uom': 'Pack',
                    'unit_price': 10.0,
                    'total_pcs': 1
                }],
                'payment_method': 'Cash',
                'paid_amount': 10.0,
                'force_checkout': True
            }

            resp = client.post('/branches/1/pos/checkout', json=checkout_payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])
            if data.get('sales_order_id'):
                self.created_so_ids.append(data['sales_order_id'])
            self.assertEqual(data['cashier_name'], 'veasna')

            # Check in database
            so = query_one("SELECT completed_by, sales_rep FROM sales_orders WHERE id = %s", (data['sales_order_id'],))
            self.assertIsNotNone(so)
            self.assertEqual(so['completed_by'], 'veasna')
            self.assertEqual(so['sales_rep'], 'veasna')

if __name__ == '__main__':
    unittest.main()
