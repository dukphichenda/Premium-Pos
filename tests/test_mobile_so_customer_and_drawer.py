import unittest
import os
import re

class TestMobileSoCustomerAndDrawer(unittest.TestCase):
    def setUp(self):
        self.canvas_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', '_detail_canvas.html')
        self.detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', 'detail.html')
        self.settings_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'settings', 'general.html')
        self.base_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'base.html')

        with open(self.canvas_path, 'r', encoding='utf-8') as f:
            self.canvas_html = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_html = f.read()
        with open(self.settings_path, 'r', encoding='utf-8') as f:
            self.settings_html = f.read()
        with open(self.base_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()

    def test_so_mobile_sidebar_bar_opens_drawer(self):
        """Verify the mobile green bar directly calls openSoMobileDrawer unconditionally."""
        self.assertIn('id="soMobileSidebarBar"', self.canvas_html)
        self.assertIn('onclick="openSoMobileDrawer()"', self.canvas_html)
        self.assertIn('ontouchend="openSoMobileDrawer()"', self.canvas_html)

    def test_open_so_mobile_drawer_implementation(self):
        """Verify openSoMobileDrawer displays the sidebar overlay and backdrop without early exit."""
        self.assertIn('window.openSoMobileDrawer = function()', self.detail_html)
        self.assertIn('mobile-drawer-open', self.detail_html)
        self.assertIn('soMobileDrawerBackdrop', self.detail_html)

    def test_mobile_customer_selection_and_attributes(self):
        """Verify mobile customer sheet rows include all data attributes and handlers."""
        self.assertIn('id="mobileCustomerSheet"', self.canvas_html)
        self.assertIn('data-customer-id=', self.canvas_html)
        self.assertIn('data-customer-name=', self.canvas_html)
        self.assertIn('handleMobileCustomerPick', self.canvas_html)
        self.assertIn('selectMobileCustomer', self.canvas_html)

    def test_quick_add_customer_modal_z_index_and_mobile_sync(self):
        """Verify quick add customer modal appears above mobile sheet and updates mobile card."""
        self.assertIn('id="modalQuickAddCustomer"', self.detail_html)
        self.assertIn('z-index: 100020', self.detail_html)
        self.assertIn('mobileDisplayCustName', self.detail_html)
        self.assertIn('mobileDisplayCustPhone', self.detail_html)
        self.assertIn('mobileDisplayCustAddr', self.detail_html)

    def test_sim_device_iframe_and_base_mode_detection(self):
        """Verify simulator iframe specifies sim_mobile=1 and base detection handles mobile iframes."""
        self.assertIn('src="/sales/new?embed=1&sim_mobile=1"', self.settings_html)
        self.assertIn('if (window.innerWidth <= 768) {', self.base_html)
        self.assertIn('return \'mobile\';', self.base_html)

if __name__ == '__main__':
    unittest.main()
