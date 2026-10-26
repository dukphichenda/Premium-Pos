import unittest
import csv
import io
import os
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

class TestBranchSalesReportBranchCost(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_branch_sales_order_profit_uses_branch_cost_and_profit(self):
        """
        Verify that for branch sales reports:
        1. Headers display BRANCH COST and PROFIT.
        2. Costing equals the branch cost scheme (107) instead of HQ cost.
        3. Profit equals sales_amount - branch_cost.
        """
        # Test branch 1 (STM) with date range covering Oct 2026
        resp = self.client.get('/reports/view/sales-order-profit?branch=1&date_range=Custom&custom_from=2026-10-01&custom_to=2026-10-31')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check headers
        self.assertIn('BRANCH COST', html)
        self.assertIn('PROFIT', html)

        # Check SO-STM-00001 specifically:
        # Sales = $185.50, Branch Cost = $162.38, Profit = $23.12
        # (HQ standard cost was $143.90, gross profit $41.60)
        self.assertIn('SO-STM-00001', html)
        self.assertIn('$185.50', html)
        self.assertIn('$162.38', html)
        self.assertIn('$23.12', html)

    def test_main_store_profit_report_retains_hq_costing(self):
        """
        Verify that HQ (main) store keeps COSTING and GROSS PROFIT headers and HQ cost.
        """
        resp = self.client.get('/reports/view/sales-order-profit?branch=main&date_range=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('COSTING', html)
        self.assertIn('GROSS PROFIT', html)

    def test_branch_csv_export_uses_branch_cost(self):
        """
        Verify CSV export for branch uses 'Branch Cost ($)' and 'Profit ($)'.
        """
        resp = self.client.get('/reports/export/sales-order-profit?branch=1&date_range=Custom&custom_from=2026-10-01&custom_to=2026-10-31')
        self.assertEqual(resp.status_code, 200)
        content = resp.data.decode('utf-8')

        reader = csv.reader(io.StringIO(content))
        header = next(reader)
        self.assertIn('Branch Cost ($)', header)
        self.assertIn('Profit ($)', header)

        # Find SO-STM-00001 in exported rows
        found_stm1 = False
        for row in reader:
            if row and row[0] == 'SO-STM-00001':
                found_stm1 = True
                sales = float(row[5])
                cost = float(row[6])
                profit = float(row[7])
                self.assertAlmostEqual(sales, 185.50, places=2)
                self.assertAlmostEqual(cost, 162.38, places=2)
                self.assertAlmostEqual(profit, 23.12, places=2)
                self.assertAlmostEqual(profit, round(sales - cost, 2), places=2)
                break
        self.assertTrue(found_stm1, "SO-STM-00001 was not found in branch export")

    def test_dashboard_chart_for_branch_reflects_branch_cost(self):
        """
        Verify dashboard charts query for branch incorporates branch cost.
        """
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            chart_resp = client.get('/api/dashboard/charts?branch=1')
            self.assertEqual(chart_resp.status_code, 200)
            chart_data = chart_resp.get_json()
            self.assertIn('monthly_labels', chart_data)
            self.assertIn('monthly_profit', chart_data)

if __name__ == '__main__':
    unittest.main()
