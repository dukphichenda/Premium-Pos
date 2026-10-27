import unittest
import os
import re
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

from app import create_app
from database import query_one, query_all

class TestDeliveryPersonAssignReport(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with open(os.path.join(self.base_dir, 'routes', 'reports.py'), 'r', encoding='utf-8') as f:
            self.reports_py = f.read()

        with open(os.path.join(self.base_dir, 'templates', 'base.html'), 'r', encoding='utf-8') as f:
            self.base_html = f.read()

        with open(os.path.join(self.base_dir, 'templates', 'reports', 'index.html'), 'r', encoding='utf-8') as f:
            self.index_html = f.read()

        with open(os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html'), 'r', encoding='utf-8') as f:
            self.viewer_html = f.read()

    def test_report_catalog_entry(self):
        """Ensure delivery-person-assign is registered in REPORT_CATALOG with correct metadata."""
        self.assertIn("'key': 'delivery-person-assign'", self.reports_py)
        self.assertIn("'title': 'Delivery Person Assign'", self.reports_py)

    def test_sidebar_flyout_and_translations(self):
        """Ensure Delivery Person Assign is in Reports flyout menu and has Khmer translations."""
        self.assertIn("report_key='delivery-person-assign'", self.base_html)
        self.assertIn("Delivery Person Assign", self.base_html)
        self.assertIn("'Delivery Person Assign': 'ចាត់តាំងអ្នកដឹកជញ្ជូន'", self.base_html)

    def test_report_hub_card(self):
        """Ensure report hub index has a card for Delivery Person Assign."""
        self.assertIn("report_key='delivery-person-assign'", self.index_html)
        self.assertIn("Delivery Person Assign", self.index_html)

    def test_viewer_template_structure(self):
        """Ensure viewer template has delivery filter chip, table without cost/profit, and modals."""
        # 1. Filter chip
        self.assertIn('chipWrapDeliveryMan', self.viewer_html)
        self.assertIn('formDeliveryManFilterInput', self.viewer_html)

        # 2. Table definition for delivery-person-assign
        self.assertIn("report_key == 'delivery-person-assign'", self.viewer_html)
        self.assertIn('repDeliverySelectAll', self.viewer_html)
        self.assertIn('DELIVERY PERSON ASSIGN', self.viewer_html)

        # 3. Strictly NO Costing / Profit in the delivery-person-assign table header or columns
        table_snippet_match = re.search(r"{% elif report_key == 'delivery-person-assign' %}(.*?)(?:{% elif|{% endif %})", self.viewer_html, re.DOTALL)
        self.assertTrue(table_snippet_match, "delivery-person-assign table block must exist")
        table_snippet = table_snippet_match.group(1)
        self.assertNotIn('COSTING', table_snippet)
        self.assertNotIn('BRANCH COST', table_snippet)
        self.assertNotIn('GROSS PROFIT', table_snippet)
        self.assertNotIn('PROFIT', table_snippet)
        self.assertNotIn('total_cogs', table_snippet)

        # 4. Modals and batch bar
        self.assertIn('repRowDeliveryModal', self.viewer_html)
        self.assertIn('newDeliveryManReportModal', self.viewer_html)
        self.assertIn('repDeliveryBatchBar', self.viewer_html)

        # 5. JavaScript functions
        self.assertIn('function openRowDeliveryPicker', self.viewer_html)
        self.assertIn('function saveRowDeliveryLogistics', self.viewer_html)
        self.assertIn('function submitNewDeliveryManReport', self.viewer_html)
        self.assertIn('function applyBatchDeliveryAssign', self.viewer_html)

    def test_view_report_live_route(self):
        """Ensure /reports/delivery-person-assign renders 200 without costing or profit."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

        res = self.client.get('/reports/view/delivery-person-assign')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('Delivery Person Assign', html)
        self.assertIn('repDeliverySelectAll', html)

    def test_export_report_csv_no_cost_or_profit(self):
        """Ensure CSV export for delivery-person-assign has delivery headers and NO cost/profit."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

        res = self.client.get('/reports/export/delivery-person-assign')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.headers.get('Content-Type', ''))
        csv_text = res.data.decode('utf-8')
        header_line = csv_text.splitlines()[0]
        self.assertIn('Order Number', header_line)
        self.assertIn('Delivery Person', header_line)
        self.assertIn('Delivery Fee (KHR)', header_line)
        self.assertNotIn('Cost', header_line)
        self.assertNotIn('Profit', header_line)

if __name__ == '__main__':
    unittest.main()
