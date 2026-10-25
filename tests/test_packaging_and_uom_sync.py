import unittest
import os
import re
from app import create_app
from database import query_one, get_db_cursor

class TestPackagingAndUomSync(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_frontend_template_catalog_has_auto_sync_and_calc(self):
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        workspace_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', '_catalog_workspace_main.html')
        content = ""
        with open(catalog_path, 'r', encoding='utf-8') as f:
            content += f.read()
        if os.path.exists(workspace_path):
            with open(workspace_path, 'r', encoding='utf-8') as f:
                content += f.read()

        # Check Purchasing UOM is locked / auto-synced
        self.assertIn('id="purchasingUomSelect"', content)
        self.assertIn('disabled', content)
        self.assertIn('= Sales UoM', content)
        self.assertIn('id="purchasingConvRow" style="display: none;"', content)

        # Check syncPurchasingUomWithSales function exists
        self.assertIn('function syncPurchasingUomWithSales', content)

        # Check recalcPacksPerCase function exists and calculates pcsPerCase / pcsPack
        self.assertIn('function recalcPacksPerCase(source)', content)
        self.assertIn('pcsPerCase / pcsPack', content)

    def test_frontend_template_detail_has_auto_sync_and_calc(self):
        detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'detail.html')
        with open(detail_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check Purchasing UOM is locked and hidden input provided
        self.assertIn('id="purchasingUomSelect"', content)
        self.assertIn('disabled', content)
        self.assertIn('name="purchasing_uom"', content)
        self.assertIn('= Sales UoM', content)

        # Check onDetailPackagingChange calculates pcsPerCase / pcs
        self.assertIn('function onDetailPackagingChange(source)', content)
        self.assertIn('pcsPerCase / pcs', content)

    def test_backend_update_ajax_auto_syncs_purchasing_uom_and_calcs_packs(self):
        with self.app.test_request_context():
            # Get an existing product or insert a test one
            test_prod = query_one("SELECT id, sales_uom, sales_uom_ratio_std, pcs_per_pack FROM products LIMIT 1")
            self.assertIsNotNone(test_prod, "Should find at least one product")
            pid = test_prod['id']

            # Simulate updating sales_uom_ratio_std to 500 and pcs_per_pack to 50 (like user screenshot)
            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            res = self.client.post(
                f'/products/{pid}/update_ajax',
                json={
                    'sales_uom': 'cases',
                    'sales_uom_ratio': 1.0,
                    'sales_uom_ratio_std': 500.0,
                    'pcs_per_pack': 50.0
                }
            )
            self.assertEqual(res.status_code, 200)

            # Verify in DB: purchasing_uom == sales_uom, and packs_per_case == 500 / 50 = 10
            updated = query_one("""
                SELECT sales_uom, purchasing_uom, sales_uom_ratio, purchasing_uom_ratio,
                       sales_uom_ratio_std, purchasing_uom_ratio_std,
                       pcs_per_pack, packs_per_case
                FROM products WHERE id = %s
            """, (pid,))

            self.assertEqual(updated['purchasing_uom'], updated['sales_uom'])
            self.assertEqual(float(updated['purchasing_uom_ratio']), float(updated['sales_uom_ratio']))
            self.assertEqual(float(updated['purchasing_uom_ratio_std']), 500.0)
            self.assertEqual(float(updated['sales_uom_ratio_std']), 500.0)
            self.assertEqual(float(updated['pcs_per_pack']), 50.0)
            self.assertEqual(float(updated['packs_per_case']), 10.0)

    def test_viewing_product_does_not_trigger_unsaved_dirty_state(self):
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(catalog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. DOMContentLoaded must not invoke sync/recalc which marks fields dirty
        dom_loaded_match = re.search(r"document\.addEventListener\('DOMContentLoaded', \(\) => \{(.*?)\}\);", content, re.DOTALL)
        self.assertIsNotNone(dom_loaded_match, "DOMContentLoaded listener should exist")
        dom_body = dom_loaded_match.group(1)
        self.assertNotIn('syncPurchasingUomWithSales()', dom_body)
        self.assertNotIn("recalcPacksPerCase('init')", dom_body)

        # 2. saveProductChanges must check !isDirty before mutating pendingChanges
        idx_check = content.find("if (!isDirty && Object.keys(pendingChanges).length === 0")
        idx_purch = content.find("pendingChanges['purchasing_uom'] = sUom;")
        self.assertTrue(idx_check != -1 and idx_purch != -1, "Both check and purchasing assignment should exist")
        self.assertLess(idx_check, idx_purch, "The !isDirty check must come BEFORE pendingChanges['purchasing_uom'] is assigned")

        # 3. syncPurchasingUomWithSales must default markDirty to false
        self.assertIn("function syncPurchasingUomWithSales(markDirty = false)", content)
        self.assertIn("if (markDirty) {", content)

        # 4. recalcPacksPerCase must only mark dirty for explicit user actions
        self.assertIn("else if (source === 'sales_conv' || source === 'pcs_pack')", content)

if __name__ == '__main__':
    unittest.main()
