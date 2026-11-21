import unittest
import os
from app import app
from database import query_one, query_all

class TestCustomerOrderHistoryDateSort(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')
        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

    def test_viewer_template_has_order_date_sort_toggle(self):
        """Verify ORDER DATE header is clickable and has sort arrow indicators"""
        self.assertIn("toggleCustomerOrderHistoryDateSort()", self.viewer_content)
        self.assertIn("inflow-sortable-date-th", self.viewer_content)
        self.assertIn("inflow-date-sort-arrow", self.viewer_content)
        self.assertIn("sort_by in ['Date Descending', 'date_desc', 'DESC']", self.viewer_content)
        self.assertIn("function toggleCustomerOrderHistoryDateSort()", self.viewer_content)
        self.assertIn("Date Descending", self.viewer_content)
        self.assertIn("Date Ascending", self.viewer_content)

    def test_customer_order_history_descending_sort_response(self):
        """Verify request with sort_by=Date Descending returns 200 and down arrow"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/customer-order-history?sort_by=Date+Descending&date_range=All')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('▼', html)
        self.assertIn('toggleCustomerOrderHistoryDateSort()', html)

    def test_customer_order_history_ascending_sort_response(self):
        """Verify request with sort_by=Date Ascending returns 200 and up arrow"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/customer-order-history?sort_by=Date+Ascending&date_range=All')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('▲', html)
        self.assertIn('toggleCustomerOrderHistoryDateSort()', html)

    def test_customer_order_history_default_sort_response(self):
        """Verify default request (no sort_by param) defaults to ascending arrow"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/customer-order-history?date_range=All')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('▲', html)

    def test_customer_order_history_csv_export_sort(self):
        """Verify CSV export accepts sort_by=Date Descending and Date Ascending"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res_desc = self.client.get('/reports/export/customer-order-history?sort_by=Date+Descending&date_range=All')
        self.assertEqual(res_desc.status_code, 200)
        self.assertIn('text/csv', res_desc.content_type)

        res_asc = self.client.get('/reports/export/customer-order-history?sort_by=Date+Ascending&date_range=All')
        self.assertEqual(res_asc.status_code, 200)
        self.assertIn('text/csv', res_asc.content_type)

if __name__ == '__main__':
    unittest.main()
