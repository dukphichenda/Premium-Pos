import unittest
import os
from app import create_app
from database import query_one, execute

class TestPcsPerCasePriceSync(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_frontend_recalc_packs_per_case_fixes_pcs_price(self):
        """Verify that catalog.html recalcPacksPerCase fixes price per pcs and multiplies by new pcs per case."""
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(catalog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check that recalcPacksPerCase fixes pcs price and updates case price
        self.assertIn('function recalcPacksPerCase(source)', content)
        self.assertIn('const newCaseP = pcsP * effectivePcsPerCase;', content)
        self.assertIn('caseInp.value = newCaseP.toFixed(currentPriceDec);', content)
        self.assertIn('markPriceDirty(sId, newCaseP);', content)
        self.assertIn('recalcSchemeMarkup(caseInp, sId);', content)

    def test_frontend_workspace_has_conversion_handlers(self):
        """Verify that _catalog_workspace_main.html has onConversionRatioChange on salesConvStd."""
        workspace_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', '_catalog_workspace_main.html')
        with open(workspace_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('id="salesConvStd"', content)
        self.assertIn('onConversionRatioChange()', content)
        self.assertIn("markFieldDirty('sales_uom_ratio_std', this.value)", content)

    def test_backend_update_ajax_saves_ratio_and_recalculated_prices(self):
        """Verify backend update_ajax cleanly saves new sales_uom_ratio_std and updated prices."""
        with self.app.test_request_context():
            test_prod = query_one("SELECT id, sales_uom_ratio_std FROM products WHERE is_active = TRUE LIMIT 1")
            self.assertIsNotNone(test_prod, "Should find at least one active product")
            pid = test_prod['id']

            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
                sess['branch_id'] = None

            # Simulate changing pcs per case to 600, Retail 1 (100) new case price 108.00 (from 0.180 * 600)
            res = self.client.post(
                f'/products/{pid}/update_ajax',
                json={
                    'sales_uom_ratio_std': 600.0,
                    'prices': {
                        100: 108.0
                    }
                }
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))

            # Verify database updated
            prod_row = query_one("SELECT sales_uom_ratio_std FROM products WHERE id = %s", (pid,))
            self.assertEqual(float(prod_row['sales_uom_ratio_std']), 600.0)

            price_row = query_one("SELECT unit_price FROM product_prices WHERE product_id = %s AND pricing_scheme_id = 100", (pid,))
            self.assertIsNotNone(price_row)
            self.assertAlmostEqual(float(price_row['unit_price']), 108.0, places=2)

            # Restore original ratio
            orig_ratio = float(test_prod['sales_uom_ratio_std'] or 500.0)
            orig_price = round(0.180 * orig_ratio, 2)
            self.client.post(
                f'/products/{pid}/update_ajax',
                json={
                    'sales_uom_ratio_std': orig_ratio,
                    'prices': {
                        100: orig_price
                    }
                }
            )

if __name__ == '__main__':
    unittest.main()
