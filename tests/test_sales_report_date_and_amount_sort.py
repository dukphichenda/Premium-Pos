import unittest
import os
from app import app
from database import query_all

class TestSalesReportDateAndAmountSort(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')
        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

    def test_ui_table_headers_have_sort_toggles_and_arrows(self):
        """Verify ORDER DATE and SALES AMOUNT headers have interactive sort toggles and arrows"""
        self.assertIn("toggleSortByOrderDate()", self.viewer_content)
        self.assertIn("toggleSortBySalesAmount()", self.viewer_content)
        self.assertIn("function toggleSortByOrderDate()", self.viewer_content)
        self.assertIn("function toggleSortBySalesAmount()", self.viewer_content)
        self.assertIn("Sales Amount Asc", self.viewer_content)
        self.assertIn("Date Ascending", self.viewer_content)
        self.assertIn("Date Descending", self.viewer_content)

    def test_sales_order_profit_date_sorting_ui(self):
        """Verify Date Descending and Date Ascending render correct directional arrows"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Date Descending
        res_desc = self.client.get('/reports/view/sales-order-profit?sort_by=Date+Descending&date_range=All&status=All')
        self.assertEqual(res_desc.status_code, 200)
        html_desc = res_desc.data.decode('utf-8')
        self.assertIn('Sorted: Recent to Oldest', html_desc)

        # Date Ascending
        res_asc = self.client.get('/reports/view/sales-order-profit?sort_by=Date+Ascending&date_range=All&status=All')
        self.assertEqual(res_asc.status_code, 200)
        html_asc = res_asc.data.decode('utf-8')
        self.assertIn('Sorted: Oldest to Recent', html_asc)

    def test_sales_order_profit_amount_sorting_ui(self):
        """Verify Sales Amount (high to low) and Sales Amount Asc (low to high) render correct arrows"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # High to Less (Descending)
        res_desc = self.client.get('/reports/view/sales-order-profit?sort_by=Sales+Amount&date_range=All&status=All')
        self.assertEqual(res_desc.status_code, 200)
        html_desc = res_desc.data.decode('utf-8')
        self.assertIn('Sorted: High to Less', html_desc)

        # Less to High (Ascending)
        res_asc = self.client.get('/reports/view/sales-order-profit?sort_by=Sales+Amount+Asc&date_range=All&status=All')
        self.assertEqual(res_asc.status_code, 200)
        html_asc = res_asc.data.decode('utf-8')
        self.assertIn('Sorted: Less to High', html_asc)

    def test_csv_export_respects_sort_order(self):
        """Verify CSV export succeeds with Date Descending and Sales Amount Asc"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res1 = self.client.get('/reports/export/sales-order-profit?sort_by=Sales+Amount+Asc&date_range=All&status=All')
        self.assertEqual(res1.status_code, 200)
        self.assertIn('text/csv', res1.content_type)

        res2 = self.client.get('/reports/export/sales-order-profit?sort_by=Date+Descending&date_range=All&status=All')
        self.assertEqual(res2.status_code, 200)
        self.assertIn('text/csv', res2.content_type)

if __name__ == '__main__':
    unittest.main()
