import unittest
from app import create_app
from database import query_one

class TestSidebarMinimizeArrow(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_sales_order_sidebar_minimize(self):
        """Verify Sales Order detail view has minimize arrow button and expand tab."""
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Minimize arrow button on sidebar header
        self.assertIn('id="btnMinimizeSoSidebar"', html)
        self.assertIn('toggleSoSidebarCollapse()', html)
        self.assertIn('so-minimize-btn', html)

        # Expand tab on left edge when collapsed
        self.assertIn('id="soSidebarExpandTab"', html)
        self.assertIn('class="inflow-sidebar-edge-tab"', html)

        # Ribbon toolbar expand button
        self.assertIn('id="soExpandTbBtn"', html)

        # JS function and shortcut
        self.assertIn('function toggleSoSidebarCollapse', html)
        self.assertIn('inflow_so_sidebar_collapsed', html)

    def test_purchase_order_sidebar_minimize(self):
        """Verify Purchase Order detail view has minimize arrow button and expand tab."""
        resp = self.client.get('/purchases/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Minimize arrow button on sidebar header
        self.assertIn('id="btnMinimizePoSidebar"', html)
        self.assertIn('togglePoSidebarCollapse()', html)
        self.assertIn('po-minimize-btn', html)

        # Expand tab on left edge when collapsed
        self.assertIn('id="poSidebarExpandTab"', html)
        self.assertIn('class="inflow-sidebar-edge-tab po-edge-tab"', html)

        # Topbar expand button
        self.assertIn('id="poExpandTbBtn"', html)

        # JS function and shortcut
        self.assertIn('function togglePoSidebarCollapse', html)
        self.assertIn('inflow_po_sidebar_collapsed', html)

    def test_product_catalog_sidebar_minimize(self):
        """Verify Product Catalog detail view has minimize arrow button and expand tab."""
        prod = query_one("SELECT id FROM products LIMIT 1")
        prod_id = prod['id'] if prod else 1
        resp = self.client.get(f'/products/{prod_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Minimize arrow button on sidebar toolbar
        self.assertIn('id="btnMinimizeProductSidebar"', html)
        self.assertIn('toggleProductSidebarCollapse()', html)
        self.assertIn('inflow-cat-minimize-btn', html)

        # Expand tab on left edge when collapsed
        self.assertIn('id="productSidebarExpandTab"', html)
        self.assertIn('class="inflow-sidebar-edge-tab product-edge-tab"', html)

        # Topbar expand button
        self.assertIn('id="productExpandTbBtn"', html)

        # JS function and shortcut
        self.assertIn('function toggleProductSidebarCollapse', html)
        self.assertIn('inflow_product_sidebar_collapsed', html)

if __name__ == '__main__':
    unittest.main()
