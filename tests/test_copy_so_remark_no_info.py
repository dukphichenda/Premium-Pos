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
        cust = query_one("SELECT id, branch_id FROM customers ORDER BY id DESC LIMIT 1 OFFSET 1") or query_one("SELECT id, branch_id FROM customers LIMIT 1")
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

    def test_existing_order_date_change_adds_previous_bill_date_only_once(self):
        """When changing the date on an existing order, 'Previous bill date' is added only once upon save."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        import time
        t_str = str(int(time.time() * 1000))

        order_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, status, payment_status, order_date, notes) "
            "VALUES (%s, %s, %s, 100, 'OPEN', 'UNPAID', '2026-10-01', %s) RETURNING id",
            (f'TEST-ONCE-{t_str}', cust_id, branch_id, "Order notes initial")
        )

        # 1. Update with changed date and note added by frontend
        post_data = {
            'order_id': order_id,
            'customer_id': cust_id,
            'branch_id': branch_id or '',
            'order_date': '2026-10-05',
            'notes': 'Order notes initial\nPrevious bill date: 01-Oct-26',
            'lines_json': '[]',
            'subtotal': 100.0,
            'total_amount': 100.0
        }
        resp = self.client.post(f'/sales/{order_id}/save', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        saved = query_one("SELECT notes FROM sales_orders WHERE id = %s", (order_id,))
        lines = [l for l in (saved['notes'] or '').splitlines() if re.search(r'previous\s+bill\s+date', l, re.I)]
        self.assertEqual(len(lines), 1, f"Expected exactly 1 previous bill date line, got: {saved['notes']}")

        # 2. Saving again must NOT add another line
        resp2 = self.client.post(f'/sales/{order_id}/save', data=post_data, follow_redirects=True)
        self.assertEqual(resp2.status_code, 200)
        saved2 = query_one("SELECT notes FROM sales_orders WHERE id = %s", (order_id,))
        lines2 = [l for l in (saved2['notes'] or '').splitlines() if re.search(r'previous\s+bill\s+date', l, re.I)]
        self.assertEqual(len(lines2), 1, f"Expected still 1 previous bill date line after saving again, got: {saved2['notes']}")

    def test_existing_order_deduplicates_duplicate_previous_bill_date_lines(self):
        """Saving an order that already contains duplicate 'Previous bill date' lines deduplicates them."""
        cust = query_one("SELECT id, branch_id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        branch_id = cust.get('branch_id') if cust else None
        import time
        t_str = str(int(time.time() * 1000))

        order_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, status, payment_status, order_date, notes) "
            "VALUES (%s, %s, %s, 100, 'OPEN', 'UNPAID', '2026-10-01', %s) RETURNING id",
            (f'TEST-DEDUP-{t_str}', cust_id, branch_id, "Note text\nPrevious bill date: 01-Nov-26\nPrevious bill date: 01-Nov-2026")
        )

        post_data = {
            'order_id': order_id,
            'customer_id': cust_id,
            'branch_id': branch_id or '',
            'order_date': '2026-10-01',
            'notes': "Note text\nPrevious bill date: 01-Nov-26\nPrevious bill date: 01-Nov-2026",
            'lines_json': '[]',
            'subtotal': 100.0,
            'total_amount': 100.0
        }
        resp = self.client.post(f'/sales/{order_id}/save', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        saved = query_one("SELECT notes FROM sales_orders WHERE id = %s", (order_id,))
        lines = [l for l in (saved['notes'] or '').splitlines() if re.search(r'previous\s+bill\s+date', l, re.I)]
        self.assertEqual(len(lines), 1, f"Expected duplicate lines to be deduplicated to 1, got: {saved['notes']}")
        self.assertEqual(lines[0], 'Previous bill date: 01-Nov-26')

if __name__ == '__main__':
    unittest.main()
