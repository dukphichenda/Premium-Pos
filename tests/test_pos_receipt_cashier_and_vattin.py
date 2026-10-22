import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from app import app
from database import query_one

class TestPosReceiptCashierAndVatTin(unittest.TestCase):
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
            self.assertEqual(data['cashier_name'], 'veasna')

            # Check in database
            so = query_one("SELECT completed_by, sales_rep FROM sales_orders WHERE id = %s", (data['sales_order_id'],))
            self.assertIsNotNone(so)
            self.assertEqual(so['completed_by'], 'veasna')
            self.assertEqual(so['sales_rep'], 'veasna')

if __name__ == '__main__':
    unittest.main()
