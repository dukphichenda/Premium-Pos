import unittest
from app import create_app

class TestPriceList(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_inventory_flyout_has_price_list(self):
        """Verify Inventory flyout menu in base.html has Price list row."""
        resp = self.client.get('/inventory')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Price list', html)
        self.assertTrue('/price-list' in html)

    def test_price_list_page_renders(self):
        """Verify /products/price-list and /inventory/price-list return 200 and contain required controls."""
        for path in ['/products/price-list', '/inventory/price-list']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed for {path}")
            html = resp.data.decode('utf-8')

            # Page title and Khmer translation
            self.assertIn('Product Price List', html)
            self.assertIn('តារាងតម្លៃទំនិញ', html)

            # Option to show: All Products, By Category, Selected Products
            self.assertIn('id="scopeAll"', html)
            self.assertIn('id="scopeCategory"', html)
            self.assertIn('id="scopeSelected"', html)
            self.assertIn('id="categoryFilter"', html)

            # Option to Group By
            self.assertIn('id="groupByFilter"', html)
            self.assertIn('Group by:', html)
            self.assertIn('value="category"', html)
            self.assertIn('value="uom"', html)

            # PDF export button & Print
            self.assertIn('id="btnExportPdf"', html)
            self.assertIn('exportPriceListPDF()', html)
            self.assertIn('html2pdf', html)

            # Multi-select products modal / drawer
            self.assertIn('id="productPickerModal"', html)
            self.assertIn('openProductPickerModal()', html)

            # Card structure (Image 2 exact match)
            self.assertIn('pl-price-card', html)
            self.assertIn('pl-card-header-grid', html)
            self.assertIn('pl-card-upper-grid', html)
            self.assertIn('pl-card-price-hdr-grid', html)
            self.assertIn('(UNIT PRICE)', html)
            self.assertIn('(Product Detail)', html)

if __name__ == '__main__':
    unittest.main()
