import unittest
import time
from app import create_app
from database import query_one, execute_returning_id, get_db_cursor, resync_all_sequences

class TestSoKhrRateMatchesPreview(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.created_so_ids = []
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def tearDown(self):
        if hasattr(self, 'created_so_ids') and self.created_so_ids:
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_order_versions WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_orders WHERE id = ANY(%s)", (self.created_so_ids,))
            resync_all_sequences()

    def test_hq_so_khr_matches_invoice_preview(self):
        """Verify that HQ sales order detail view displays KHR matching invoice preview exactly (46,600 KHR for $11.50 with rate 4050)."""
        cust = query_one("SELECT id FROM customers WHERE branch_id IS NULL LIMIT 1") or query_one("SELECT id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        t_str = str(int(time.time() * 1000))

        order_id = execute_returning_id(
            "INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, subtotal, paid_amount, balance_due, status, payment_status, order_date) "
            "VALUES (%s, %s, NULL, 11.50, 11.50, 0.00, 11.50, 'OPEN', 'UNPAID', '2026-11-06') RETURNING id",
            (f'TEST-KHR-{t_str}', cust_id)
        )
        self.created_so_ids.append(order_id)

        # 1. Check Invoice Preview
        resp_prev = self.client.get(f'/sales/{order_id}/print?type=invoice')
        self.assertEqual(resp_prev.status_code, 200)
        prev_html = resp_prev.get_data(as_text=True)
        # Should show rate 4,050 and 46,600
        self.assertIn('4,050', prev_html)
        self.assertIn('46,600', prev_html)

        # 2. Check Sales Order Detail
        resp_detail = self.client.get(f'/sales/{order_id}')
        self.assertEqual(resp_detail.status_code, 200)
        detail_html = resp_detail.get_data(as_text=True)

        # In SO detail canvas, dispTotalKhr should show 46,600 KHR (not 47,150 KHR)
        self.assertIn('46,600 KHR', detail_html)
        self.assertNotIn('47,150 KHR', detail_html)
        self.assertIn('window.CURRENT_KHR_RATE', detail_html)

if __name__ == '__main__':
    unittest.main()
