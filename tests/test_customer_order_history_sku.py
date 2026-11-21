import unittest
import os
from app import app
from database import query_one

class TestCustomerOrderHistorySku(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')
        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

    def test_viewer_template_includes_sku_in_item_cell(self):
        """Verify templates/reports/viewer.html renders SKU in Customer Order History item cell"""
        self.assertIn("set sku_val = (line.sku or '').strip()", self.viewer_content)
        self.assertIn("set item_val = (line.item_name or 'Item').strip()", self.viewer_content)
        self.assertIn("not item_val.lower().startswith(sku_val.lower())", self.viewer_content)
        self.assertIn("span style=\"font-weight: 700; color: #0F172A; margin-right: 4px;\">{{ sku_val }}</span>", self.viewer_content)

    def test_customer_order_history_renders_sku_on_page(self):
        """Verify Customer Order History endpoint renders SKU for product line items"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        row = query_one("""
            SELECT so.customer_id, so.order_number, so.order_date, p.sku, p.name
            FROM sales_orders so
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE p.sku IS NOT NULL AND p.sku != '' AND so.status != 'CANCELLED'
            LIMIT 1
        """)
        if row:
            cid = row['customer_id']
            odate = str(row['order_date'])
            res = self.client.get(f'/reports/view/customer-order-history?customer_id={cid}&branch=all&date_range=Custom&date_from={odate}&date_to={odate}')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            self.assertIn(row['sku'], html)

if __name__ == '__main__':
    unittest.main()
