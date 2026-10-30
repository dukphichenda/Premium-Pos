import unittest
import os
import re

class TestMobileSaleOrderOptimization(unittest.TestCase):
    def setUp(self):
        self.canvas_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', '_detail_canvas.html')
        self.detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', 'detail.html')
        self.dashboard_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'dashboard.html')
        self.list_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', 'list.html')
        self.settings_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'settings', 'general.html')
        self.base_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'base.html')
        self.styles_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'styles.css')
        
        with open(self.canvas_path, 'r', encoding='utf-8') as f:
            self.canvas_html = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_html = f.read()
        with open(self.dashboard_path, 'r', encoding='utf-8') as f:
            self.dashboard_html = f.read()
        with open(self.list_path, 'r', encoding='utf-8') as f:
            self.list_html = f.read()
        with open(self.settings_path, 'r', encoding='utf-8') as f:
            self.settings_html = f.read()
        with open(self.base_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()
        with open(self.styles_path, 'r', encoding='utf-8') as f:
            self.styles_css = f.read()

    def test_emerald_mint_palette_styling(self):
        """Verify Forest Emerald and Mint Green palette colors (#1E6B52, #5BB78B, #EAF7EF, #A7D7C5) are defined in CSS."""
        self.assertIn('#1E6B52', self.canvas_html)
        self.assertIn('#5BB78B', self.canvas_html)
        self.assertIn('#EAF7EF', self.canvas_html)
        self.assertIn('#A7D7C5', self.canvas_html)

    def test_screen_1_home_dashboard(self):
        """Verify Screen 1: Mobile Dashboard with Header, Logistics, Quick Actions, Workflow, KPI grid, and Nav Bar."""
        self.assertIn('so-mobile-dashboard-view', self.dashboard_html)
        self.assertIn('so-mob-dash-header', self.dashboard_html)
        self.assertIn('New Sales', self.dashboard_html)
        self.assertIn('so-mob-logistics-grid', self.dashboard_html)
        self.assertIn('so-mob-quick-actions-grid', self.dashboard_html)
        self.assertIn('so-mob-workflow-grid', self.dashboard_html)
        self.assertIn('so-mob-kpi-grid', self.dashboard_html)
        self.assertIn('Monthly Sales &amp; Profit Breakdown', self.dashboard_html)
        self.assertIn('Stock Value by Category', self.dashboard_html)
        self.assertIn('so-mobile-nav-bar', self.dashboard_html)

    def test_screen_2_sales_order_list(self):
        """Verify Screen 2: Sale Order List with header, search, filter pills, order cards, and nav bar."""
        self.assertIn('so-mobile-sales-list-view', self.list_html)
        self.assertIn('so-mob-filter-pills', self.list_html)
        self.assertIn('so-mob-orders-container', self.list_html)
        self.assertIn('filterMobileOrders', self.list_html)
        self.assertIn('so-mobile-nav-bar', self.list_html)

    def test_screen_3_sale_order_detail_main_view(self):
        """Verify Screen 3: Sale Order Detail main view components."""
        self.assertIn('so-mobile-cust-select-card', self.canvas_html)
        self.assertIn('so-mobile-settings-card-btn', self.canvas_html)
        self.assertIn('so-mobile-search-add-bar', self.canvas_html)
        self.assertIn('mobileItemsHeadingTitle', self.canvas_html)
        self.assertIn('mobileStickyBottomBar', self.canvas_html)
        self.assertIn('Complete & Pay', self.canvas_html)

    def test_screen_4_customer_selection_bottom_sheet(self):
        """Verify Screen 4: Customer Selection Bottom Sheet."""
        self.assertIn('id="mobileCustomerSheet"', self.canvas_html)
        self.assertIn('id="mobileCustomerSearchInput"', self.canvas_html)
        self.assertIn('id="mobileCustomerItemsList"', self.canvas_html)
        self.assertIn('+ Add New Customer', self.canvas_html)
        self.assertIn('openMobileCustomerSheet', self.canvas_html)

    def test_screen_5_order_settings_bottom_sheet(self):
        """Verify Screen 5: Order Settings Bottom Sheet & Delivery Fee Quick Chips."""
        self.assertIn('id="mobileOrderSettingsSheet"', self.canvas_html)
        self.assertIn('so-mobile-fee-chips', self.canvas_html)
        self.assertIn('setMobileDeliveryFee(1000)', self.canvas_html)
        self.assertIn('setMobileDeliveryFee(2000)', self.canvas_html)
        self.assertIn('openMobileOrderSettingsSheet', self.canvas_html)

    def test_screen_6_add_product_picker_modal(self):
        """Verify Screen 6: Add Product Picker Full Screen Modal with category pills and search."""
        self.assertIn('id="mobileAddProductModal"', self.canvas_html)
        self.assertIn('id="mobileProductSearchInput"', self.canvas_html)
        self.assertIn('id="mobileProductCatPills"', self.canvas_html)
        self.assertIn('openMobileAddProductModal', self.canvas_html)
        self.assertIn('addProductFromMobilePicker', self.canvas_html)

    def test_screen_7_payment_bottom_sheet(self):
        """Verify Screen 7: Dedicated mobile payment bottom sheet with ABA, Cash, ACLEDA, KB PRASAC, Other Payment."""
        self.assertIn('id="mobilePaymentModal"', self.canvas_html)
        self.assertIn('ABA Bank', self.canvas_html)
        self.assertIn('Cash', self.canvas_html)
        self.assertIn('ACLEDA', self.canvas_html)
        self.assertIn('KB PRASAC', self.canvas_html)
        self.assertIn('Other Payment', self.canvas_html)
        self.assertIn('openMobilePaymentModal', self.canvas_html)

    def test_screen_8_order_summary_bottom_sheet(self):
        """Verify Screen 8: Order Summary Bottom Sheet."""
        self.assertIn('id="mobileOrderSummarySheet"', self.canvas_html)
        self.assertIn('mobileSummarySubtotal', self.canvas_html)
        self.assertIn('mobileSummaryTotal', self.canvas_html)
        self.assertIn('openMobileOrderSummarySheet', self.canvas_html)

    def test_screen_9_more_actions_bottom_sheet(self):
        """Verify Screen 9: More Actions Bottom Sheet with full actions list."""
        self.assertIn('id="mobileMoreActionsSheet"', self.canvas_html)
        self.assertIn('openMobileMoreActionsSheet', self.canvas_html)
        self.assertIn('Copy Order', self.canvas_html)
        self.assertIn('Version History', self.canvas_html)
        self.assertIn('Export PDF', self.canvas_html)
        self.assertIn('Export JPG', self.canvas_html)
        self.assertIn('Share Telegram', self.canvas_html)

    def test_screen_10_empty_state_box(self):
        """Verify Screen 10: Empty State Box with illustration and + Add Product button."""
        self.assertIn('so-mobile-empty-state-box', self.canvas_html)
        self.assertIn('No products added yet', self.canvas_html)
        self.assertIn('Search and add products to create your sale order.', self.canvas_html)

    def test_screen_11_universal_bottom_navigation_bar(self):
        """Verify Screen 11: Universal 5-button bottom nav bar with elevated center Home bubble."""
        self.assertIn('so-mobile-nav-bar', self.canvas_html)
        self.assertIn('so-nav-center-home', self.canvas_html)
        self.assertIn('so-nav-home-bubble', self.canvas_html)
        self.assertIn('Settings', self.canvas_html)
        self.assertIn('Report', self.canvas_html)
        self.assertIn('Home', self.canvas_html)
        self.assertIn('SO', self.canvas_html)
        self.assertIn('Product', self.canvas_html)

    def test_all_12_mobile_slots_exist(self):
        """Verify that all 12 mobile slots defined in SO_MOBILE_SLOT_MAP exist in canvas DOM."""
        slots = [
            'slotMobileCustomer',
            'slotMobileDate',
            'slotMobileOrderNumber',
            'slotMobileStatus',
            'slotMobilePhone',
            'slotMobileSalesRep',
            'slotMobileAddress',
            'slotMobileBranch',
            'slotMobileLocation',
            'slotMobileDeliveryBy',
            'slotMobileDeliveryFee',
            'slotMobileDeliveryNotes'
        ]
        for slot in slots:
            self.assertIn(f'id="{slot}"', self.canvas_html, f"Missing slot: {slot}")

    def test_quantity_stepper_controls(self):
        """Verify stepper buttons [-] and [+] exist in canvas template."""
        self.assertIn('so-qty-btn-minus', self.canvas_html)
        self.assertIn('so-qty-btn-plus', self.canvas_html)
        self.assertIn('stepLineQty(this, -1)', self.canvas_html)
        self.assertIn('stepLineQty(this, 1)', self.canvas_html)

    def test_item_adding_box_full_width_stretch(self):
        """Verify that the item adding box and .so-main-left stretch 100% without 268px squishing."""
        self.assertIn('html.is-mobile-view .so-main-left', self.canvas_html)
        self.assertIn('html.is-mobile-view .so-card-items', self.canvas_html)
        self.assertIn('@media (max-width: 1024px)', self.canvas_html)
        self.assertIn('@media (max-width: 1024px)', self.detail_html)

    def test_bottom_bar_customizer_settings_button_and_api(self):
        """Verify Customize Bottom Bar button, modal, and API endpoint exist."""
        self.assertIn('Customize Bottom Bar', self.settings_html)
        self.assertIn('openBottomBarCustomizerModal', self.settings_html)
        self.assertIn('modalCustomizeBottomBar', self.settings_html)
        self.assertIn('saveCustomBottomBar', self.settings_html)
        self.assertIn('renderCustomBottomBar', self.base_html)

        from app import app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
            res = client.get('/api/settings/bottom-bar')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))
            self.assertEqual(len(data.get('items', [])), 5)

    def test_universal_bottom_bar_and_zero_left_margin(self):
        """Verify universal bottom bar always exists across all pages and left blank is completely deleted."""
        # 1. Base template universal bottom bar with all 5 tabs
        self.assertIn('id="universalMobileNavBar"', self.base_html)
        self.assertIn('data-tab-type="settings"', self.base_html)
        self.assertIn('data-tab-type="report"', self.base_html)
        self.assertIn('data-tab-type="home"', self.base_html)
        self.assertIn('data-tab-type="so"', self.base_html)
        self.assertIn('data-tab-type="product"', self.base_html)

        # 2. Strict desktop-only 56px rail wrapper in styles.css
        self.assertIn('@media (min-width: 1025px)', self.styles_css)
        self.assertIn('margin-left: 56px !important', self.styles_css)

        # 3. Mobile zero-margin reset across containers
        self.assertIn('@media (max-width: 1024px)', self.styles_css)
        self.assertIn('.so-main-left', self.styles_css)
        self.assertIn('.inflow-so-workspace', self.styles_css)

        # 4. Suppression of sidebar edge rail on mobile in detail.html and base.html
        self.assertIn('#soSidebarExpandTab', self.detail_html)
        self.assertIn('.inflow-sidebar-edge-tab', self.detail_html)
        self.assertIn('#soSidebarExpandTab', self.base_html)

        # 5. Desktop / PC mode strictly suppresses bottom navigation bar
        self.assertIn('html.is-desktop-view .so-mobile-nav-bar', self.styles_css)
        self.assertIn('#universalMobileNavBar', self.styles_css)
        self.assertIn('html.is-desktop-view #universalMobileNavBar', self.base_html)


    def test_early_sidebar_functions_definition(self):
        """Verify sidebar navigation functions (handleSelectOrder, clearSoLiveSearch) are defined early before sidebar HTML."""
        self.assertIn('window.handleSelectOrder = function', self.detail_html)
        self.assertIn('window.clearSoLiveSearch = function', self.detail_html)
        self.assertIn('window.toggleSoSidebarCollapse = function', self.detail_html)
        self.assertIn('window.openSoMobileDrawer = function', self.detail_html)
        self.assertIn('window.closeSoMobileDrawer = function', self.detail_html)
        
        # Verify early script appears before #soMasterSidebar
        early_idx = self.detail_html.find('window.handleSelectOrder = function')
        sidebar_idx = self.detail_html.find('id="soMasterSidebar"')
        self.assertTrue(early_idx != -1 and early_idx < sidebar_idx, "Early script must precede #soMasterSidebar")

    def test_pc_desktop_view_workspace_restoration(self):
        """Verify PC Desktop view guarantees full dual-column ERP interface and strictly hides mobile controls."""
        # 1. Desktop rules in detail.html
        self.assertIn('html.is-desktop-view .inflow-desktop-toolbar', self.detail_html)
        self.assertIn('html.is-desktop-view .inflow-so-workspace:not(.sidebar-collapsed) .so-master-sidebar', self.detail_html)
        self.assertIn('width: 280px !important', self.detail_html)

        # 2. Desktop dual-column canvas rules in _detail_canvas.html
        self.assertIn('html.is-desktop-view .so-main-right', self.canvas_html)
        self.assertIn('html.is-desktop-view .so-card-grid-top', self.canvas_html)
        self.assertIn('html.is-desktop-view .so-bottom-cards-grid', self.canvas_html)
        self.assertIn('html.is-desktop-view .so-modern-main-split', self.canvas_html)

        # 3. Base detection defaults PC screens to desktop mode
        self.assertIn('ALWAYS DEFAULT TO DESKTOP', self.base_html)

    def test_mobile_customer_sheet_selection_data_attr(self):
        """Verify customer sheet row uses data-customer-id and handleMobileCustomerPick to avoid quote parsing bugs."""
        self.assertIn('data-customer-id="', self.canvas_html)
        self.assertIn('handleMobileCustomerPick', self.canvas_html)
        self.assertIn('window.handleMobileCustomerPick = function', self.canvas_html)
        self.assertIn('window.selectMobileCustomer = function', self.canvas_html)

    def test_mobile_line_item_card_redesign(self):
        """Verify redesigned mobile line item card matching media_1793369282830_5994b064.jpg."""
        # 1. Structure in canvas template (existing rows)
        self.assertIn('so-item-sku-line', self.canvas_html)
        self.assertIn('so-item-sku-val', self.canvas_html)
        self.assertIn('so-mob-field-label', self.canvas_html)
        self.assertIn('so-qty-wrapper-split', self.canvas_html)
        self.assertIn('so-mob-col-qty', self.canvas_html)
        self.assertIn('so-mob-col-unit', self.canvas_html)
        self.assertIn('so-mob-stepper-box', self.canvas_html)
        self.assertIn('line-tier-cell', self.canvas_html)
        self.assertIn('line-price-cell', self.canvas_html)
        self.assertIn('line-disc-cell', self.canvas_html)
        self.assertIn('so-mob-input-with-addon', self.canvas_html)
        self.assertIn('so-mob-addon', self.canvas_html)
        self.assertIn('so-mob-subtotal-card', self.canvas_html)
        self.assertIn('so-mob-subtotal-label', self.canvas_html)
        self.assertIn('so-subtotal-amount', self.canvas_html)

        # 2. Dynamic row generation in detail.html
        self.assertIn('so-item-sku-line', self.detail_html)
        self.assertIn('so-qty-wrapper-split', self.detail_html)
        self.assertIn('so-mob-col-qty', self.detail_html)
        self.assertIn('so-mob-col-unit', self.detail_html)
        self.assertIn('so-mob-input-with-addon', self.detail_html)
        self.assertIn('so-mob-subtotal-card', self.detail_html)
        self.assertIn('so-subtotal-amount', self.detail_html)

        # 3. CSS Grid layout specification
        self.assertIn('"item-hdr item-hdr"', self.canvas_html)
        self.assertIn('"row-qty  row-qty"', self.canvas_html)
        self.assertIn('"col-tier col-price"', self.canvas_html)
        self.assertIn('"col-disc col-subtotal"', self.canvas_html)

        # 4. Desktop preservation
        self.assertIn('.so-mob-field-label {\n            display: none !important;', self.canvas_html)

if __name__ == '__main__':
    unittest.main()
