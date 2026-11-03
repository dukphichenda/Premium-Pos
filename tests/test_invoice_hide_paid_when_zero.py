import unittest
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

        # Create an unpaid order ($83 total, 0 paid)
        unpaid_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES ('TEST-UNPAID-INV', %s, %s, 83.00, 0.00, 83.00, 'OPEN', 'UNPAID', '2026-11-03') RETURNING id",
            (cust_id, branch_id)
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

        # Create a partially paid order ($100 total, $30 paid, $70 balance)
        paid_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES ('TEST-PARTIAL-INV', %s, %s, 100.00, 30.00, 70.00, 'OPEN', 'PARTIAL', '2026-11-03') RETURNING id",
            (cust_id, branch_id)
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

if __name__ == '__main__':
    unittest.main()
