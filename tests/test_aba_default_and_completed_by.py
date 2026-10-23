import unittest
from app import create_app
from database import query_one, get_db_cursor

class TestCompletePayAndAbaDefault(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'sokha_tester'
            sess['display_name'] = 'Sokha Tester'
            sess['role'] = 'main_admin'

    def test_aba_bank_is_first_and_default_payment_method(self):
        """Verify ABA Bank is the first tile and default active payment method."""
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Hidden input defaults to ABA Bank
        self.assertIn('name="payment_method" id="orderPaymentMethodHidden" value="ABA Bank"', html)

        # ABA Bank is the first tile in grid with active class
        aba_idx = html.find('data-method="ABA Bank"')
        cash_idx = html.find('data-method="Cash"')
        acleda_idx = html.find('data-method="ACLEDA"')
        prasac_idx = html.find('data-method="KB PRASAC"')

        self.assertNotEqual(aba_idx, -1)
        self.assertNotEqual(cash_idx, -1)
        self.assertNotEqual(acleda_idx, -1)
        self.assertNotEqual(prasac_idx, -1)

        # ABA is before Cash in the rendered HTML
        self.assertLess(aba_idx, cash_idx, "ABA Bank tile should be placed before Cash tile")

    def test_complete_pay_records_login_username_and_displays_notice(self):
        """Verify completing an order saves completed_by as the session login name and displays it."""
        import time
        uniq_num = f"SO-TABA-{int(time.time()*1000)}"
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO customers (name, phone)
                VALUES ('Test Buyer ABA', '012999888')
                RETURNING id;
            """)
            cust_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO sales_orders (
                    order_number, customer_id, status, payment_status, total_amount, balance_due, paid_amount
                ) VALUES (%s, %s, 'OPEN', 'UNPAID', 88.00, 88.00, 0.00)
                RETURNING id;
            """, (uniq_num, cust_id))
            order_id = cur.fetchone()['id']

        # 2. Complete & Pay via edit order with mark_complete_pay=1
        resp = self.client.post(f'/sales/{order_id}/save', data={
            'customer_id': str(cust_id),
            'order_date': '2026-10-24',
            'mark_complete_pay': '1',
            'payment_method': 'ABA Bank',
            'lines_json': '[]',
        }, follow_redirects=True)
        if b'alert alert-danger' in resp.data or b'Error saving order' in resp.data:
            print("FLASH/ERROR:", [line for line in resp.data.decode('utf-8').split('\n') if 'alert' in line or 'Error' in line])
        self.assertEqual(resp.status_code, 200)

        # 3. Verify in database that completed_by is 'sokha_tester'
        order = query_one("SELECT * FROM sales_orders WHERE id = %s", (order_id,))
        self.assertEqual(order['status'], 'PAID')
        self.assertEqual(order['payment_status'], 'PAID')
        self.assertEqual(order['payment_method'], 'ABA Bank')
        self.assertEqual(order['completed_by'], 'sokha_tester')

        # 4. View the order detail and verify completed_by notice is displayed
        resp_detail = self.client.get(f'/sales/{order_id}')
        self.assertEqual(resp_detail.status_code, 200)
        html_detail = resp_detail.data.decode('utf-8')

        self.assertIn('sokha_tester', html_detail)
        self.assertIn('Completed by:', html_detail)

if __name__ == '__main__':
    unittest.main()
