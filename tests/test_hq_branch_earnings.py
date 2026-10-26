import unittest
import os
import sys
from pathlib import Path

# Auto-load .env if needed
env_path = Path(__file__).resolve().parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

from app import create_app
from database import query_one, query_all

class TestHQBranchEarnings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        # Set session as HQ main admin
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None
            sess['is_branch_mode'] = False

    def test_report_catalog_and_flyout_contain_hq_branch_earnings(self):
        """Verify Reports Center and base flyout menu contain HQ Branch Earnings for HQ users."""
        resp = self.client.get('/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('HQ Branch Earnings', html)
        self.assertIn('HQ branch earnings', html)

    def test_view_hq_branch_earnings_default_view(self):
        """Verify HQ user can access /reports/view/hq-branch-earnings and see KPI cards & table."""
        resp = self.client.get('/reports/view/hq-branch-earnings')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Tab Navigation
        self.assertIn('Branch Sales & Profit', html)
        self.assertIn('HQ Earnings from Branches', html)
        self.assertIn('HQ Only', html)

        # KPI Summary Cards
        self.assertIn('Total Quantity Sold', html)
        self.assertIn('Total Billed to Branch', html)
        self.assertIn('Total HQ Costing', html)
        self.assertIn('HQ Net Earnings', html)

        # Table Headers
        self.assertIn('BRANCH COST', html)
        self.assertIn('HQ COSTING', html)
        self.assertIn('TOTAL BILLED', html)
        self.assertIn('HQ NET EARNINGS', html)

    def test_tab_switcher_present_on_branch_sales_summary(self):
        """Verify the tab switcher also appears on branch-sales-summary for HQ users."""
        resp = self.client.get('/reports/view/branch-sales-summary')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Branch Sales & Profit', html)
        self.assertIn('HQ Earnings from Branches', html)

    def test_branch_user_blocked_from_hq_branch_earnings(self):
        """Verify branch cashier/admin cannot access HQ branch earnings."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'cashier1'
            sess['role'] = 'branch_cashier'
            sess['branch_id'] = 1
            sess['is_branch_mode'] = True

        resp = self.client.get('/reports/view/hq-branch-earnings')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/reports/view/branch-sales-summary', resp.headers['Location'])

        # Export also protected
        resp_export = self.client.get('/reports/export/hq-branch-earnings')
        self.assertEqual(resp_export.status_code, 302)

    def test_export_hq_branch_earnings_csv(self):
        """Verify CSV export for HQ Branch Earnings contains expected headers."""
        resp = self.client.get('/reports/export/hq-branch-earnings?date_range=All&currency=USD')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.mimetype)
        csv_text = resp.get_data(as_text=True)

        self.assertIn('Category', csv_text)
        self.assertIn('Item SKU', csv_text)
        self.assertIn('Item Name', csv_text)
        self.assertIn('Quantity Sold', csv_text)
        self.assertIn('Branch Cost / Pc ($)', csv_text)
        self.assertIn('HQ Costing / Pc ($)', csv_text)
        self.assertIn('HQ Earning / Pc ($)', csv_text)
        self.assertIn('Total Billed to Branch ($)', csv_text)
        self.assertIn('Total HQ Cost ($)', csv_text)
        self.assertIn('HQ Net Earnings ($)', csv_text)
        self.assertIn('HQ Margin %', csv_text)

    def test_export_hq_branch_earnings_khr_csv(self):
        """Verify KHR export headers reflect Riel symbol."""
        resp = self.client.get('/reports/export/hq-branch-earnings?date_range=All&currency=KHR')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.mimetype)
        csv_text = resp.get_data(as_text=True)
        self.assertIn('Branch Cost / Pc (៛)', csv_text)
        self.assertIn('HQ Net Earnings (៛)', csv_text)

if __name__ == '__main__':
    unittest.main()
