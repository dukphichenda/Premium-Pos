import unittest
import os
from app import create_app
from database import query_one

class TestSameUomPriceTable(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_templates_contain_same_uom_logic(self):
        """Verify templates contain is_same_uom and updatePricingTableUomColumns logic."""
        workspace_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', '_catalog_workspace_main.html')
        with open(workspace_path, 'r', encoding='utf-8') as f:
            ws_content = f.read()

        self.assertIn('is_same_uom', ws_content)
        self.assertIn('id="thCasePrice"', ws_content)
        self.assertIn('id="thPcsPrice"', ws_content)
        self.assertIn('class="col-case-price"', ws_content)
        self.assertIn('class="col-pcs-price"', ws_content)

        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(catalog_path, 'r', encoding='utf-8') as f:
            cat_content = f.read()

        self.assertIn('function isSameUom()', cat_content)
        self.assertIn('function updatePricingTableUomColumns()', cat_content)
        self.assertIn('if (typeof isSameUom === \'function\' && isSameUom()) return 1;', cat_content)

    def test_product_workspace_renders_correctly(self):
        """Verify rendering product catalog workspace correctly applies is_same_uom."""
        with self.app.test_request_context():
            # Find an existing product to test
            prod = query_one("SELECT id, uom, sales_uom FROM products ORDER BY id DESC LIMIT 1")
            if not prod:
                self.skipTest("No product found in database")
            pid = prod['id']

            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            res = self.client.get(f'/products/{pid}')
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)

            self.assertIn('id="catPricingTable"', html)
            self.assertIn('id="thCasePrice"', html)
            self.assertIn('id="thPcsPrice"', html)

if __name__ == '__main__':
    unittest.main()
