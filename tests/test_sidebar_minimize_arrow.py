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

        # Mobile view controls (show bar, drawer header, backdrop, floating button)
        self.assertIn('id="soMobileSidebarBar"', html)
        self.assertIn('id="soMobileDrawerHeader"', html)
        self.assertIn('id="soMobileDrawerBackdrop"', html)
        self.assertIn('onclick="closeSoMobileDrawer()"', html)
        self.assertIn('ontouchend="closeSoMobileDrawer()"', html)
        self.assertIn('id="soMobileFloatingBtn"', html)

        # JS function and shortcut
        self.assertIn('function toggleSoSidebarCollapse', html)
        self.assertIn('function closeSoMobileDrawer', html)
        self.assertIn('function openSoMobileDrawer', html)
        self.assertIn('inflow_so_sidebar_collapsed', html)
        self.assertIn('.inflow-so-workspace.mobile-drawer-open .so-mobile-drawer-backdrop', html)
        self.assertIn('_soDrawerJustClosedAt', html)
        self.assertIn('soFastNavProgressBar', html)
        self.assertIn('handleSelectOrder(event', html)

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

        # Mobile view controls (show bar, drawer header, backdrop, floating button)
        self.assertIn('id="poMobileSidebarBar"', html)
        self.assertIn('id="poMobileDrawerHeader"', html)
        self.assertIn('id="poMobileDrawerBackdrop"', html)
        self.assertIn('id="poMobileFloatingBtn"', html)

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

        # Mobile view controls (show bar, drawer header, backdrop, floating button)
        self.assertIn('id="productMobileSidebarBar"', html)
        self.assertIn('id="productMobileDrawerHeader"', html)
        self.assertIn('id="productMobileDrawerBackdrop"', html)
        self.assertIn('id="productMobileFloatingBtn"', html)

        # JS function and shortcut
        self.assertIn('function toggleProductSidebarCollapse', html)
        self.assertIn('inflow_product_sidebar_collapsed', html)

    def test_customer_sidebar_minimize_and_teal_theme(self):
        """Verify Customer master-detail view has minimize arrow button, expand tab, and teal green theme."""
        resp = self.client.get('/customers')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Minimize arrow button on sidebar toolbar
        self.assertIn('id="btnMinimizeCustomerSidebar"', html)
        self.assertIn('toggleCustomerSidebarCollapse()', html)
        self.assertIn('customer-minimize-btn', html)

        # Expand tab on left edge when collapsed
        self.assertIn('id="customerSidebarExpandTab"', html)
        self.assertIn('class="inflow-sidebar-edge-tab customer-edge-tab"', html)

        # Topbar expand button
        self.assertIn('id="customerExpandTbBtn"', html)

        # Mobile view controls (show bar, drawer header, backdrop, floating button)
        self.assertIn('id="customerMobileSidebarBar"', html)
        self.assertIn('id="customerMobileDrawerHeader"', html)
        self.assertIn('id="customerMobileDrawerBackdrop"', html)
        self.assertIn('id="customerMobileFloatingBtn"', html)

        # JS function and shortcut
        self.assertIn('function toggleCustomerSidebarCollapse', html)
        self.assertIn('inflow_customer_sidebar_collapsed', html)

        # Verify teal green theme color palette
        self.assertIn('#0D9488', html)
        self.assertIn('#0F766E', html)
        self.assertIn('#F0FDFA', html)
        self.assertIn('#CCFBF1', html)

        # Ensure old caramel brown colors are completely eliminated
        self.assertNotIn('#8C6541', html)
        self.assertNotIn('#795238', html)
        self.assertNotIn('#FAF7F2', html)

if __name__ == '__main__':
    unittest.main()
