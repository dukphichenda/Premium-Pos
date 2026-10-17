import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all

class TestBranchSalesReportsGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def test_branch_user_report_center_scoping(self):
        """Verify that when a branch user accesses the Report Center, it detects and displays their branch."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('STM', html)
        self.assertIn('Assigned Branch', html)
        self.assertIn('Sales Reports', html)

    def test_branch_user_sales_order_profit_report(self):
        """Verify that branch user generating Sales Order Profit report only gets their branch's sales."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports/view/sales-order-profit?date_range=All&status=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Sales Order Profit Report', html)
        self.assertIn('STM', html)
        self.assertIn('Assigned', html)

    def test_branch_user_sales_by_product_summary(self):
        """Verify that branch user generating Sales by Product Summary gets their branch's product sales."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports/view/sales-by-product-summary?date_range=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Sales by Product Summary', html)
        self.assertIn('STM', html)

    def test_branch_user_sales_order_summary(self):
        """Verify that branch user generating Sales Order Summary gets only their branch's orders."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports/view/sales-order-summary?date_range=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Sales Order Summary', html)
        self.assertIn('STM', html)

    def test_branch_user_customer_list_isolation(self):
        """Verify that branch user customer list is scoped to branch customers."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports/view/customer-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Customer List', html)
        self.assertIn('STM', html)

    def test_hq_admin_can_generate_branch_report(self):
        """Verify that HQ admin can select branch 1 to view and generate that branch's sales report."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        resp = self.client.get('/reports/view/sales-order-profit?branch=1&date_range=All&status=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Sales Order Profit Report', html)
        self.assertIn('STM', html)

    def test_branch_export_csv_isolation(self):
        """Verify CSV export respects branch scope."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/reports/export/sales-order-profit?date_range=All&status=All')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.mimetype)

        resp_cust = self.client.get('/reports/export/customer-list')
        self.assertEqual(resp_cust.status_code, 200)
        self.assertIn('text/csv', resp_cust.mimetype)

    def test_branch_dashboard_has_sales_reports_links(self):
        """Verify branch dashboard has direct links to Sales Order Profit and Sales by Product reports."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'branch_stm'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        resp = self.client.get('/branches/1/dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Sales Order Profit', html)
        self.assertIn('Sales by Product', html)
        self.assertIn('All Sales Reports', html)

if __name__ == '__main__':
    unittest.main()
