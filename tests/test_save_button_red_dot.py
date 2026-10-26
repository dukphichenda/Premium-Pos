import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one

class TestSaveButtonRedDot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def test_css_defines_red_unsaved_dot(self):
        """Verify styles.css defines .inflow-unsaved-dot with vibrant red #EF4444 and pulse animation"""
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'styles.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()

        self.assertIn('.inflow-unsaved-dot', css_content)
        self.assertIn('#EF4444', css_content)
        self.assertIn('inflowPulseRedDot', css_content)

    def test_app_js_includes_global_watcher(self):
        """Verify app.js provides initGlobalSaveButtonDirtyWatcher and setSaveButtonDirty"""
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        self.assertIn('initGlobalSaveButtonDirtyWatcher', js_content)
        self.assertIn('setSaveButtonDirty', js_content)
        self.assertIn('ensureSaveButtonDot', js_content)

    def test_product_catalog_save_button_has_dot(self):
        """Product Catalog workspace must include .inflow-unsaved-dot inside btnSaveProduct"""
        prod = query_one("SELECT id FROM products WHERE is_active = TRUE LIMIT 1")
        if not prod:
            self.skipTest("No active product found")

        resp = self.client.get(f'/products/{prod["id"]}', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="btnSaveProduct"', html)
        self.assertIn('class="inflow-unsaved-dot"', html)

    def test_sales_order_save_button_has_dot(self):
        """Sales Order detail page must include .inflow-unsaved-dot inside btn-so-save"""
        resp = self.client.get('/sales/new', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('btn-so-save', html)
        self.assertIn('id="btnSoSaveDot"', html)
        self.assertIn('class="inflow-unsaved-dot"', html)

    def test_purchase_order_save_button_has_dot(self):
        """Purchase Order detail page must include .inflow-unsaved-dot inside poSaveBtn"""
        resp = self.client.get('/purchases/new', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="poSaveBtn"', html)
        self.assertIn('id="poSaveDot"', html)
        self.assertIn('class="inflow-unsaved-dot"', html)

    def test_customer_detail_save_button_has_dot(self):
        """Customer detail page must include .inflow-unsaved-dot inside btnSaveCustomer"""
        cust = query_one("SELECT id FROM customers LIMIT 1")
        url = f'/customers/{cust["id"]}' if cust else '/customers/new'

        resp = self.client.get(url, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="btnSaveCustomer"', html)
        self.assertIn('id="btnCustomerSaveDot"', html)
        self.assertIn('class="inflow-unsaved-dot"', html)

    def test_stock_adjustment_save_button_has_dot(self):
        """Stock adjustment form must include .inflow-unsaved-dot on draft save buttons"""
        resp = self.client.get('/inventory/adjustments/new', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="topBtnSaveDraftDot"', html)
        self.assertIn('id="bottomBtnSaveDraftDot"', html)

if __name__ == '__main__':
    unittest.main()
