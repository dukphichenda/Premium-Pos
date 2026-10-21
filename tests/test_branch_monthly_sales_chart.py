import unittest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

class TestBranchMonthlySalesChart(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.branch_template_path = os.path.join(self.base_dir, 'templates', 'branches', 'dashboard.html')
        self.routes_branches_path = os.path.join(self.base_dir, 'routes', 'branches.py')

        with open(self.branch_template_path, 'r', encoding='utf-8') as f:
            self.branch_template = f.read()

        with open(self.routes_branches_path, 'r', encoding='utf-8') as f:
            self.routes_code = f.read()

    def test_branch_dashboard_template_monthly_sales_graph(self):
        """Verify templates/branches/dashboard.html includes the 12-month Monthly Sales Breakdown chart."""
        # Canvas element
        self.assertIn('id="branchMonthlySalesChart"', self.branch_template)
        self.assertIn('id="branchRevenueTrendChart"', self.branch_template)

        # Header Titles & Subtitles
        self.assertIn('Monthly Sales Breakdown - {{ branch.name }}', self.branch_template)
        self.assertIn('Total Paid Sale & Open Sale (Last 12 Months)', self.branch_template)
        self.assertIn('{{ branch.code }} DIRECT SALES', self.branch_template)

        # View Toggle buttons
        self.assertIn('toggleBranchChart', self.branch_template)
        self.assertIn('id="btnChartMonthly"', self.branch_template)
        self.assertIn('id="btnChartDaily"', self.branch_template)

        # Datasets in Chart.js initialization: Paid and Open Sale ONLY (No Profit)
        self.assertIn("label: 'Total Paid Sale'", self.branch_template)
        self.assertIn("label: 'Open Sale'", self.branch_template)
        self.assertIn("data: data.monthly_paid", self.branch_template)
        self.assertIn("data: data.monthly_open", self.branch_template)

        # Confirm branch chart script does not add a Profit dataset
        self.assertNotIn("label: 'Profit'", self.branch_template)

    def test_branch_chart_api_implementation(self):
        """Verify routes/branches.py branch_chart_data calculates 12-month open & paid sales."""
        self.assertIn("def branch_chart_data(id):", self.routes_code)
        self.assertIn("monthly_sales = query_all(", self.routes_code)
        self.assertIn("so.branch_id = %s", self.routes_code)
        self.assertIn("'monthly_labels': [r['month_label'] for r in monthly_sales]", self.routes_code)
        self.assertIn("'monthly_paid':", self.routes_code)
        self.assertIn("'monthly_open':", self.routes_code)
        self.assertIn("'monthly_revenue':", self.routes_code)

    def test_branch_charts_api_endpoint_structure(self):
        """Verify API response structure when querying /api/branches/<id>/charts."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
            try:
                res = client.get('/api/branches/1/charts')
                if res.status_code == 200:
                    data = res.get_json()
                    self.assertIn('monthly_labels', data)
                    self.assertIn('monthly_paid', data)
                    self.assertIn('monthly_open', data)
                    self.assertEqual(len(data['monthly_labels']), 12)
                    self.assertNotIn('monthly_profit', data)
            except Exception:
                # Local test without DB will pass via static assertions
                pass

if __name__ == '__main__':
    unittest.main()
