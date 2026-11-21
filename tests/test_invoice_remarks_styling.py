import unittest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one

class TestInvoiceRemarksStyling(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

    def test_invoice_remarks_bold_red_styling(self):
        """Verify that order remarks in invoice_print.html render with bold red and bigger font size."""
        # Find any order with notes, or pick an existing sales order
        order = query_one("""
            SELECT id, order_number FROM sales_orders 
            WHERE status != 'CANCELLED' AND notes IS NOT NULL AND TRIM(notes) != ''
            ORDER BY id DESC LIMIT 1
        """)
        if not order:
            order = query_one("SELECT id, order_number FROM sales_orders WHERE status != 'CANCELLED' ORDER BY id DESC LIMIT 1")

        if not order:
            self.skipTest("No sales orders found to test invoice print")

        order_id = order['id']
        resp = self.client.get(f'/sales/{order_id}/print')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Verify new CSS classes and red styling exist in rendered output
        self.assertIn('.totals-remarks-title', html)
        self.assertIn('.totals-remarks-text', html)
        self.assertIn('#DC2626', html)
        self.assertIn('14px', html)
        self.assertIn('font-weight: 800', html)

if __name__ == '__main__':
    unittest.main()
