import unittest
import time
from app import create_app
from database import query_one, execute_returning_id

class TestInvoiceHidePaidWhenZero(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_invoice_hides_paid_and_balance_due_when_no_amount_paid(self):
        """When no amount has been paid, the Paid & Balance Due rows must not be displayed on the invoice."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        t_str = str(int(time.time() * 1000))

        # Create an unpaid order ($83 total, 0 paid)
        unpaid_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES (%s, %s, %s, 83.00, 0.00, 83.00, 'OPEN', 'UNPAID', '2026-11-03') RETURNING id",
            (f'TEST-UNPAID-{t_str}', cust_id, branch_id)
        )

        response = self.client.get(f'/sales/{unpaid_id}/print?type=invoice')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Must not show Paid or Balance Due rows
        self.assertNotIn('ប្រាក់បានបង់ / Paid:', html)
        self.assertNotIn('ប្រាក់នៅខ្វះ / Balance Due:', html)
        self.assertNotIn('id="paidUsdDisplay"', html)
        self.assertNotIn('id="balanceUsdDisplay"', html)

        # But must still show Grand Total USD and KHR
        self.assertIn('សរុបរួម / Grand Total (USD):', html)
        self.assertIn('$83.00', html)

    def test_invoice_shows_paid_and_balance_due_when_amount_paid(self):
        """When an amount has been paid (partial or full), Paid & Balance Due rows must be displayed."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        t_str = str(int(time.time() * 1000))

        # Create a partially paid order ($100 total, $30 paid, $70 balance)
        paid_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES (%s, %s, %s, 100.00, 30.00, 70.00, 'OPEN', 'PARTIAL', '2026-11-03') RETURNING id",
            (f'TEST-PARTIAL-{t_str}', cust_id, branch_id)
        )

        response = self.client.get(f'/sales/{paid_id}/print?type=invoice')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Must show Paid and Balance Due rows
        self.assertIn('ប្រាក់បានបង់ / Paid:', html)
        self.assertIn('ប្រាក់នៅខ្វះ / Balance Due:', html)
        self.assertIn('id="paidUsdDisplay"', html)
        self.assertIn('id="balanceUsdDisplay"', html)
        self.assertIn('$30.00', html)
        self.assertIn('$70.00', html)

    def test_invoice_bill_does_not_show_fulfillment(self):
        """On standard invoice / bill, the Fulfillment & Logistics box must not be shown."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        t_str = str(int(time.time() * 1000))

        order_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES (%s, %s, %s, 26.00, 0.00, 26.00, 'OPEN', 'UNPAID', '2026-11-04') RETURNING id",
            (f'TEST-NO-FULFILL-{t_str}', cust_id, branch_id)
        )

        # 1. Invoice type
        response = self.client.get(f'/sales/{order_id}/print?type=invoice')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('ព័ត៌មានដឹកជញ្ជូន / FULFILLMENT', html)
        self.assertIn('single-col', html)
        self.assertIn('ព័ត៌មានអតិថិជន / CUSTOMER DETAILS', html)

        # 2. Pick list type should still include fulfillment for warehouse
        response_pick = self.client.get(f'/sales/{order_id}/print?type=pick')
        self.assertEqual(response_pick.status_code, 200)
        html_pick = response_pick.get_data(as_text=True)
        self.assertIn('ព័ត៌មានដឹកជញ្ជូន / FULFILLMENT', html_pick)

    def test_invoice_header_no_email_and_single_row_phone(self):
        """Invoice header must not show email and phone must stay on 1 row with white-space: nowrap."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        t_str = str(int(time.time() * 1000))

        order_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES (%s, %s, %s, 10.00, 0.00, 10.00, 'OPEN', 'UNPAID', '2026-11-04') RETURNING id",
            (f'TEST-HDR-PHONE-{t_str}', cust_id, branch_id)
        )

        response = self.client.get(f'/sales/{order_id}/print?type=invoice')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Must not show email in header
        self.assertNotIn('✉️', html)

        # Phone row must be styled with white-space: nowrap to guarantee 1 row
        self.assertIn('class="shop-meta-line" style="white-space: nowrap;"', html)
        self.assertIn('<span>📞</span>', html)

if __name__ == '__main__':
    unittest.main()

