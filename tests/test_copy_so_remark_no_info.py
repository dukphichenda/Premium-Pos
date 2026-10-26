import unittest
import re
from app import app
from database import query_one, execute_returning_id

class TestCopySoRemarkNoInfo(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_copied_draft_removes_previous_bill_date_info_from_remark(self):
        """When copying an SO, previous bill date info must NOT be included in remarks."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        import time
        t_str = str(int(time.time() * 1000))
        
        # Create an order with both a user note and a historical 'Previous bill date' note
        source_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, status, payment_status, order_date, notes) "
            "VALUES (%s, %s, %s, 50, 'OPEN', 'UNPAID', '2026-10-08', %s) RETURNING id",
            (f'TEST-COPY-{t_str}', cust_id, branch_id, "Customer remark here\nPrevious bill date: 26-Oct-26")
        )

        resp = self.client.get(f'/sales/new?copy_from={source_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # The user's actual remark must be retained
        self.assertIn('Customer remark here', html)
        # But 'Previous bill date: 26-Oct-26' must NOT be in the textarea / remark
        self.assertNotIn('Previous bill date: 26-Oct-26', html)

        # The data-original-date must be empty for copied drafts
        self.assertIn('data-original-date=""', html)

    def test_new_order_date_change_does_not_save_previous_bill_date_note(self):
        """Saving a new order must never add 'Previous bill date' note even if date is changed or passed."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        import time
        t_str = str(int(time.time() * 1000))

        post_data = {
            'order_id': 0,
            'customer_id': cust_id,
            'branch_id': branch_id or '',
            'order_date': '2026-10-27',
            'notes': 'Call before deliver\nPrevious bill date: 26-Oct-26',
            'lines_json': '[]',
            'subtotal': 0.0,
            'total_amount': 0.0
        }

        resp = self.client.post('/sales/new/save', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Fetch the newly saved order
        new_order = query_one("SELECT id, notes FROM sales_orders WHERE customer_id = %s ORDER BY id DESC LIMIT 1", (cust_id,))
        self.assertIsNotNone(new_order)
        self.assertIn('Call before deliver', new_order['notes'])
        self.assertNotIn('Previous bill date', new_order['notes'])

if __name__ == '__main__':
    unittest.main()
