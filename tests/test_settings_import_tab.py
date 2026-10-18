import unittest
from app import app

class TestSettingsImportTab(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
            sess['is_admin'] = True

    def test_settings_page_contains_import_nav_tab(self):
        resp = self.client.get('/settings')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('btnTabImport', html)
        self.assertIn('Import & Export Data', html)
        self.assertIn('inFlow CSV: Products, Stock & Customers', html)
        self.assertIn('id="tabImport"', html)

    def test_settings_page_with_tab_import_active(self):
        resp = self.client.get('/settings?tab=tabImport')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        # Check active class on tab
        self.assertIn('id="btnTabImport"', html)
        self.assertIn('Data Import & Export Center', html)
        self.assertIn('/data/import', html)
        self.assertIn('/data/export', html)
        # Check 4 main import categories
        self.assertIn('Products & Price Schemes', html)
        self.assertIn('Stock on Hand / Inventory', html)
        self.assertIn('Customer Directory', html)
        self.assertIn('Sales Orders & Lines', html)
        # Check quick template downloads and direct exports
        self.assertIn('/data/template/product', html)
        self.assertIn('/data/template/inventory', html)
        self.assertIn('/data/template/customer', html)
        self.assertIn('/data/template/sales_order', html)

if __name__ == '__main__':
    unittest.main()
