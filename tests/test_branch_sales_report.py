import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one

class TestBranchSalesReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def test_reports_center_includes_branch_reports(self):
        """Verify Reports Center lists the new 'Branch Reports' category and 'Branch Sales Summary'."""
        resp = self.client.get('/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Branch Reports', html)
        self.assertIn('Branch Sales Summary', html)
        self.assertIn('cat-branch', html)

    def test_reports_center_preview_branch_sales_summary(self):
        """Verify selecting Branch Sales Summary shows watermarked preview with Branch Cost."""
        resp = self.client.get('/reports?cat=branch&report=branch-sales-summary')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Branch Sales Summary', html)
        self.assertIn('BRANCH COST', html)
        self.assertIn('SAMPLE', html)

    def test_view_branch_sales_summary_default_parameters(self):
        """Verify the report viewer defaults to Branch Costing (107) and USD, and renders KPI cards."""
        resp = self.client.get('/reports/view/branch-sales-summary')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check title & metadata
        self.assertIn('Branch Sales Summary', html)
        self.assertIn('Branch Costing', html)
        self.assertIn('USD ($)', html)

        # Check Filter By parameters exist
        self.assertIn('name="branch"', html)
        self.assertIn('name="costing_scheme_id"', html)
        self.assertIn('name="currency"', html)

        # Check KPI summary cards
        self.assertIn('Total Quantity Sold', html)
        self.assertIn('Total Sales Money', html)
        self.assertIn('Total Branch Cost (Qty × Cost)', html)
        self.assertIn('Branch Gross Profit', html)

        # Check table columns
        self.assertIn('QTY SOLD', html)
        self.assertIn('TOTAL SALES', html)
        self.assertIn('BRANCH COST', html)
        self.assertIn('TOTAL COST (QTY×COST)', html)

    def test_view_branch_sales_summary_khr_currency(self):
        """Verify switching currency to KHR displays Khmer Riel symbol and exchange rate."""
        resp = self.client.get('/reports/view/branch-sales-summary?currency=KHR')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('៛', html)
        self.assertIn('KHR', html)

    def test_view_branch_sales_summary_branch_scope(self):
        """Verify scoping to specific branches or main store works."""
        # Test branch_scope=main
        resp_main = self.client.get('/reports/view/branch-sales-summary?branch=main')
        self.assertEqual(resp_main.status_code, 200)

        # Test branch_scope=all
        resp_all = self.client.get('/reports/view/branch-sales-summary?branch=all')
        self.assertEqual(resp_all.status_code, 200)

        # Test branch_scope with STM branch (id 1)
        resp_b1 = self.client.get('/reports/view/branch-sales-summary?branch=1')
        self.assertEqual(resp_b1.status_code, 200)

    def test_export_branch_sales_summary_csv(self):
        """Verify CSV export for Branch Sales Summary outputs correct headers and data."""
        resp = self.client.get('/reports/export/branch-sales-summary?date_range=All&currency=USD')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.mimetype)
        csv_text = resp.get_data(as_text=True)
        self.assertIn('Category', csv_text)
        self.assertIn('Item SKU', csv_text)
        self.assertIn('Item Name', csv_text)
        self.assertIn('Quantity Sold', csv_text)
        self.assertIn('Total Sales ($)', csv_text)
        self.assertIn('Branch Unit Cost ($)', csv_text)
        self.assertIn('Total Branch Cost ($)', csv_text)
        self.assertIn('Branch Profit ($)', csv_text)

    def test_export_branch_sales_summary_khr_csv(self):
        """Verify KHR CSV export reflects KHR headers and currency formatting."""
        resp = self.client.get('/reports/export/branch-sales-summary?date_range=All&currency=KHR')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.mimetype)
        csv_text = resp.get_data(as_text=True)
        self.assertIn('Total Sales (៛)', csv_text)
        self.assertIn('Branch Unit Cost (៛)', csv_text)
        self.assertIn('Total Branch Cost (៛)', csv_text)
        self.assertIn('Branch Profit (៛)', csv_text)

if __name__ == '__main__':
    unittest.main()
