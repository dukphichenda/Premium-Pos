import unittest
import csv
import io
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all

class TestSalesOrderProfitAmountFilter(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

    def test_ui_amount_elements_exist(self):
        """Verify the Sale Amount input, chip, clear button, and JS handlers are rendered in the HTML."""
        resp = self.client.get('/reports/view/sales-order-profit')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check input and chip elements
        self.assertIn('id="repSaleAmountInput"', html)
        self.assertIn('id="formSaleAmountInput"', html)
        self.assertIn('id="repSaleAmountClearBtn"', html)
        self.assertIn('id="drawerSaleAmountInput"', html)
        self.assertIn('onSaleAmountTyping(this.value)', html)
        self.assertIn('liveFilterTableByAmount(', html)
        self.assertIn('toggleSortBySalesAmount()', html)

    def test_amount_filtering_exact_and_range(self):
        """Verify that passing sale_amount filters orders correctly by amount and range."""
        # Find an existing sales order in the DB (pick the first order on page 1)
        order = query_one("""
            SELECT id, order_number, total_amount 
            FROM sales_orders 
            WHERE status != 'CANCELLED' AND total_amount > 0 
            ORDER BY order_number ASC LIMIT 1
        """)
        if not order:
            self.skipTest("No valid sales orders found in database")

        target_amount = float(order['total_amount'])
        target_num = order['order_number']

        # 1. Exact amount test (e.g. 27.00)
        resp_exact = self.client.get(f'/reports/view/sales-order-profit?date_range=All&status=All&sale_amount={target_amount:.2f}')
        self.assertEqual(resp_exact.status_code, 200)
        html_exact = resp_exact.data.decode('utf-8')
        self.assertIn(target_num, html_exact)

        # 2. Integer amount test (e.g. 27)
        resp_int = self.client.get(f'/reports/view/sales-order-profit?date_range=All&status=All&sale_amount={int(target_amount)}')
        self.assertEqual(resp_int.status_code, 200)
        html_int = resp_int.data.decode('utf-8')
        self.assertIn(target_num, html_int)

        # 3. Range amount test (e.g. target_amount - 1 to target_amount + 1)
        low = max(0, target_amount - 5)
        high = target_amount + 5
        resp_range = self.client.get(f'/reports/view/sales-order-profit?date_range=All&status=All&sale_amount={low:.1f}-{high:.1f}')
        self.assertEqual(resp_range.status_code, 200)
        html_range = resp_range.data.decode('utf-8')
        self.assertIn(target_num, html_range)

        # 4. Comparison amount test (e.g. <= target_amount)
        resp_comp = self.client.get(f'/reports/view/sales-order-profit?date_range=All&status=All&sale_amount=<={high:.1f}')
        self.assertEqual(resp_comp.status_code, 200)
        html_comp = resp_comp.data.decode('utf-8')
        self.assertIn(target_num, html_comp)

        # 5. Non-matching amount test (e.g. 9999999.99)
        resp_nomatch = self.client.get('/reports/view/sales-order-profit?date_range=All&status=All&sale_amount=9999999.99')
        self.assertEqual(resp_nomatch.status_code, 200)
        html_nomatch = resp_nomatch.data.decode('utf-8')
        self.assertNotIn(target_num, html_nomatch)

    def test_export_with_sale_amount_filter(self):
        """Verify CSV export respects the sale_amount filter."""
        order = query_one("""
            SELECT id, order_number, total_amount 
            FROM sales_orders 
            WHERE status != 'CANCELLED' AND total_amount > 0 
            ORDER BY id DESC LIMIT 1
        """)
        if not order:
            self.skipTest("No valid sales orders found in database")

        target_amount = float(order['total_amount'])
        target_num = order['order_number']

        # Matching export
        resp = self.client.get(f'/reports/export/sales-order-profit?date_range=All&status=All&sale_amount={target_amount:.2f}')
        self.assertEqual(resp.status_code, 200)
        content = resp.data.decode('utf-8')
        self.assertIn(target_num, content)

        # Non-matching export
        resp_none = self.client.get('/reports/export/sales-order-profit?date_range=All&status=All&sale_amount=9999999.99')
        self.assertEqual(resp_none.status_code, 200)
        content_none = resp_none.data.decode('utf-8')
        self.assertNotIn(target_num, content_none)

if __name__ == '__main__':
    unittest.main()
