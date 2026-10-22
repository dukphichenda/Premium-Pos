import unittest
from app import app

class TestCatalogFilterProductSelection(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user_id'] = 1
            sess['username'] = 'admin'

    def test_full_catalog_renders_early_pre_paint_filter(self):
        """Test that full catalog load contains early pre-paint CSS injection to prevent showing first product."""
        res = self.client.get('/products/416')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Early filter script must be present before the DOM elements
        self.assertIn('earlyCatFilterStyle', html)
        self.assertIn('inflow_catalog_filters_v3', html)

        # Sidebar elements present
        self.assertIn('id="catProductsList"', html)

        # Sidebar script must execute right after #catProductsList
        self.assertIn('selectCatalogProduct(e, id, url)', html)
        self.assertIn('restoreFilterState();', html)

        # Main workspace and modals container must be present
        self.assertIn('id="catalogMainWorkspace"', html)
        self.assertIn('id="catProductModalsContainer"', html)

    def test_partial_workspace_fast_spa_fetch(self):
        """Test that clicking a product requests partial=workspace, returning only the workspace and modals."""
        res = self.client.get('/products/416?partial=workspace', headers={'X-Inflow-Partial': 'workspace'})
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Must contain new product's workspace
        self.assertIn('id="catalogMainWorkspace"', html)
        self.assertIn('id="catProductModalsContainer"', html)
        self.assertIn('id="catProductActiveMeta"', html)

        # Must NOT contain sidebar (avoids re-querying and re-rendering 500+ items)
        self.assertNotIn('id="catProductsList"', html)

if __name__ == '__main__':
    unittest.main()
