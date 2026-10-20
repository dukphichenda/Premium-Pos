import unittest
import os
import re
from app import app

class TestPriceCardsZipExport(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.price_list_path = os.path.join(self.base_dir, 'templates', 'products', 'price_list.html')
        self.catalog_path = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')
        self.detail_path = os.path.join(self.base_dir, 'templates', 'products', 'detail.html')

        with open(self.price_list_path, 'r', encoding='utf-8') as f:
            self.price_list_html = f.read()

        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            self.catalog_html = f.read()

        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_html = f.read()

    def test_price_list_has_zip_export_ui_and_dropdown(self):
        self.assertIn('btnExportZip', self.price_list_html)
        self.assertIn('plExportZipDropdownMenu', self.price_list_html)
        self.assertIn('All Products (Category Folders)', self.price_list_html)
        self.assertIn('Current View / Category', self.price_list_html)
        self.assertIn('Selected Products', self.price_list_html)
        self.assertIn('plBatchExportProgressModal', self.price_list_html)
        self.assertIn('plBatchExportStage', self.price_list_html)

    def test_price_list_quality_and_category_folder_logic(self):
        # Must contain category subfolder grouping logic
        self.assertIn('zip.folder(cleanFolder).file(cardFilename, blob)', self.price_list_html)
        # Must contain adaptive 700KB - 1MB exporter
        self.assertIn('exportCanvasToTargetJpegBlob', self.price_list_html)
        self.assertIn('padJpegBlobToTargetRange', self.price_list_html)
        self.assertIn('720 * 1024', self.price_list_html)
        self.assertIn('980 * 1024', self.price_list_html)

    def test_catalog_and_detail_have_category_folders_and_quality(self):
        # Catalog template
        self.assertIn('exportCanvasToTargetJpegBlob', self.catalog_html)
        self.assertIn('zip.folder(cleanFolder).file(cardFilename, blob)', self.catalog_html)
        self.assertIn('scale: 3.2', self.catalog_html)

        # Detail template
        self.assertIn('exportCanvasToTargetJpegBlob', self.detail_html)
        self.assertIn('zip.folder(cleanFolder).file(cardFilename, blob)', self.detail_html)
        self.assertIn('scale: 3.2', self.detail_html)

    def test_api_price_cards_data_returns_categories(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

        res = client.get('/api/products/price-cards-data?all=1')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        items = data.get('items', [])
        self.assertGreater(len(items), 0)
        first = items[0]
        self.assertIn('category_name', first)
        self.assertIn('card', first)
        self.assertIn('sku', first)

if __name__ == '__main__':
    unittest.main()
