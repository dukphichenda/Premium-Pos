import unittest
import os
import re
from app import app

class TestCustomerOrderHistoryReport(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.index_path = os.path.join(self.base_dir, 'templates', 'reports', 'index.html')
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')

        with open(self.index_path, 'r', encoding='utf-8') as f:
            self.index_content = f.read()

        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

        self.client = app.test_client()

    def test_deleted_cards_not_in_index(self):
        # 1. Abandoned showroom carts and Sales tax must be deleted
        self.assertNotIn('Abandoned showroom carts', self.index_content)
        self.assertNotIn('View a list of customers who did not complete their showroom orders', self.index_content)
        self.assertNotIn('sales-tax-report', self.index_content)
        self.assertNotIn('Total sales tax amounts collected from customers', self.index_content)

        # Active reports must remain
        self.assertIn('customer-order-history', self.index_content)
        self.assertIn('sales-by-product-summary', self.index_content)
        self.assertIn('sales-order-profit', self.index_content)

    def test_customer_order_history_table_structure_in_viewer(self):
        # 2. Viewer template must have Customer Order History specific table headers and classes
        self.assertIn('report_key == \'customer-order-history\'', self.viewer_content)
        self.assertIn('inflow-crys-table', self.viewer_content)
        self.assertIn('inflow-crys-th-row', self.viewer_content)
        self.assertIn('>ITEM<', self.viewer_content)
        self.assertIn('>ORDER DATE<', self.viewer_content)
        self.assertIn('>STATUS<', self.viewer_content)
        self.assertIn('>QUANTITY<', self.viewer_content)
        self.assertIn('>AMOUNT<', self.viewer_content)
        self.assertIn('inflow-crys-cust-name', self.viewer_content)
        self.assertIn('inflow-crys-order-num', self.viewer_content)
        self.assertIn('inflow-crys-subtotal-val', self.viewer_content)
        self.assertIn('inflow-crys-total-val', self.viewer_content)

    def test_customer_order_history_view_endpoint(self):
        # 3. Test GET /reports/view/customer-order-history endpoint rendering with real data
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/customer-order-history?customer_id=1709&date_from=2026-10-01&date_to=2026-10-31')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Header details
        self.assertIn('Customer Order History', html)
        self.assertIn('For the period', html)
        self.assertIn('Report Printed:', html)
        self.assertIn('page', html)

        # Park Cafe Airport order details matching user screenshot
        self.assertIn('Park Cafe Airport', html)
        self.assertIn('SO-022765', html)
        self.assertIn('SO-022843', html)
        self.assertIn('800.00', html)
        self.assertIn('93.75', html)
        self.assertIn('650.00', html)
        self.assertIn('55.00', html)
        self.assertIn('1,450.00', html)
        self.assertIn('148.75', html)
        self.assertIn('#D0E4F7', html) # Alternating blue row highlight

    def test_print_styles_defined(self):
        # 4. Media print rules must be defined to preserve print fidelity
        self.assertIn('@media print', self.viewer_content)
        self.assertIn('inflow-rep-pager', self.viewer_content)

if __name__ == '__main__':
    unittest.main()
