import unittest
import os
import re

class TestMobileProductAndSettingsRedesign(unittest.TestCase):
    """
    Verifies that Product tab and Settings tab have dedicated mobile view redesigns
    matching Screenshot 1 (Product list & detail) and Screenshot 2 (Settings warm coffee theme),
    while desktop views remain 100% intact and functional.
    """

    def setUp(self):
        self.catalog_template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        self.settings_template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'settings', 'general.html')

        with open(self.catalog_template_path, 'r', encoding='utf-8') as f:
            self.catalog_html = f.read()

        with open(self.settings_template_path, 'r', encoding='utf-8') as f:
            self.settings_html = f.read()

    # =========================================================================
    # 1. Product Mobile View (Screenshot 1)
    # =========================================================================
    def test_product_mobile_container_exists(self):
        self.assertIn('id="productMobileAppContainer"', self.catalog_html)
        self.assertIn('class="product-mobile-app-container"', self.catalog_html)

    def test_product_mobile_list_and_detail_views_exist(self):
        self.assertIn('id="prodMobListView"', self.catalog_html)
        self.assertIn('id="prodMobDetailView"', self.catalog_html)

    def test_product_mobile_header_elements(self):
        # Header has title Products, hamburger menu, filter icon, more icon
        self.assertIn('class="prod-mob-title">Products</h1>', self.catalog_html)
        self.assertIn('class="prod-mob-btn-icon"', self.catalog_html)
        self.assertIn('toggleProdMobCategorySheet()', self.catalog_html)

    def test_product_mobile_search_bar(self):
        self.assertIn('id="prodMobSearchInput"', self.catalog_html)
        self.assertIn('placeholder="Search product, SKU, barcode..."', self.catalog_html)
        self.assertIn('filterProdMobList()', self.catalog_html)

    def test_product_mobile_category_and_view_toggles(self):
        self.assertIn('id="prodMobCatBtn"', self.catalog_html)
        self.assertIn('All Categories', self.catalog_html)
        self.assertIn('id="prodMobViewGrid"', self.catalog_html)
        self.assertIn('id="prodMobViewList"', self.catalog_html)

    def test_product_mobile_cards_and_badges(self):
        self.assertIn('class="prod-mob-item-card"', self.catalog_html)
        self.assertIn('class="prod-mob-card-thumb"', self.catalog_html)
        self.assertIn('class="prod-mob-card-sku"', self.catalog_html)
        self.assertIn('class="prod-mob-card-price"', self.catalog_html)
        self.assertIn('class="prod-mob-stock-pill in-stock"', self.catalog_html)
        self.assertIn('In Stock', self.catalog_html)

    def test_product_mobile_bottom_summary_bar(self):
        self.assertIn('class="prod-mob-bottom-summary"', self.catalog_html)
        self.assertIn('id="prodMobTotalCount"', self.catalog_html)
        self.assertIn('class="prod-mob-filter-pill-btn"', self.catalog_html)

    def test_product_mobile_detail_view_structure(self):
        # Detail header
        self.assertIn('closeProductMobileDetail()', self.catalog_html)
        self.assertIn('Product Detail', self.catalog_html)
        self.assertIn('id="prodMobDetailSubSku"', self.catalog_html)
        self.assertIn('id="prodMobDetailStockBadge"', self.catalog_html)

        # Hero card
        self.assertIn('class="prod-mob-hero-card"', self.catalog_html)
        self.assertIn('class="prod-mob-hero-img-badge">1/4</span>', self.catalog_html)
        self.assertIn('class="prod-mob-cat-pill"', self.catalog_html)

        # 3-column KPI cards
        self.assertIn('class="prod-mob-kpi-grid"', self.catalog_html)
        self.assertIn('On Hand', self.catalog_html)
        self.assertIn('Reorder Point', self.catalog_html)
        self.assertIn('Reorder Quantity', self.catalog_html)

        # Accordion navigation links
        self.assertIn('Product Information', self.catalog_html)
        self.assertIn('Storage Info', self.catalog_html)
        self.assertIn('Unit of Measure', self.catalog_html)
        self.assertIn('Dimensions & Packaging', self.catalog_html)

        # Detail pills
        self.assertIn('class="prod-mob-pills-nav"', self.catalog_html)
        self.assertIn('Overview', self.catalog_html)
        self.assertIn('Combined / Kit', self.catalog_html)
        self.assertIn('Vendors', self.catalog_html)
        self.assertIn('History', self.catalog_html)

        # Pricing & Cost card
        self.assertIn('class="prod-mob-pricing-card"', self.catalog_html)
        self.assertIn('Pricing & Cost', self.catalog_html)
        self.assertIn('Retail 1', self.catalog_html)
        self.assertIn('Price (per piece)', self.catalog_html)
        self.assertIn('Cost (per piece)', self.catalog_html)
        self.assertIn('Markup', self.catalog_html)
        self.assertIn('Retail 2', self.catalog_html)
        self.assertIn('Retail 3', self.catalog_html)

    # =========================================================================
    # 2. Settings Mobile View (Screenshot 2 - Coffee & Sand Theme)
    # =========================================================================
    def test_settings_mobile_container_exists(self):
        self.assertIn('id="settingsMobileAppContainer"', self.settings_html)
        self.assertIn('class="settings-mobile-app-container"', self.settings_html)
        self.assertIn('id="settingsDesktopLayout"', self.settings_html)

    def test_settings_mobile_header(self):
        self.assertIn('class="set-mob-header"', self.settings_html)
        self.assertIn('class="set-mob-title">System & Company Settings</h1>', self.settings_html)
        self.assertIn('class="set-mob-back-btn"', self.settings_html)

    def test_settings_mobile_company_profile_card(self):
        self.assertIn('id="setMobCompanyCard"', self.settings_html)
        self.assertIn('id="setMobCompanyForm"', self.settings_html)
        self.assertIn('Company Legal Name *', self.settings_html)
        self.assertIn('Phone Number', self.settings_html)
        self.assertIn('Email Address', self.settings_html)
        self.assertIn('Website', self.settings_html)
        self.assertIn('Address', self.settings_html)
        self.assertIn('City', self.settings_html)
        self.assertIn('Country', self.settings_html)
        self.assertIn('VAT / Tax Number', self.settings_html)
        self.assertIn('Currency Code', self.settings_html)
        self.assertIn('Currency Symbol', self.settings_html)

    def test_settings_mobile_eight_navigation_cards(self):
        # 1. Pricing & Currency
        self.assertIn('Pricing & Currency', self.settings_html)
        # 2. Decimal Precision
        self.assertIn('Decimal Precision', self.settings_html)
        # 3. Invoice Customization
        self.assertIn('Invoice Customization', self.settings_html)
        # 4. Users & Permissions
        self.assertIn('Users & Permissions', self.settings_html)
        # 5. Backup & Restore
        self.assertIn('Backup & Restore', self.settings_html)
        # 6. Import & Export Data
        self.assertIn('Import & Export Data', self.settings_html)
        # 7. Android App & Mobile UI
        self.assertIn('Android App & Mobile UI', self.settings_html)
        # 8. Mobile View Simulation
        self.assertIn('Mobile View Simulation', self.settings_html)

    def test_settings_mobile_application_logo_card(self):
        self.assertIn('id="setMobLogoCard"', self.settings_html)
        self.assertIn('id="mobAppLogoForm"', self.settings_html)
        self.assertIn('class="set-mob-logo-circle"', self.settings_html)
        self.assertIn('Sidebar Preview', self.settings_html)
        self.assertIn('Choose Logo File', self.settings_html)
        self.assertIn('Reset Default', self.settings_html)
        self.assertIn('Save App Logo', self.settings_html)

    def test_settings_mobile_system_architecture_card(self):
        self.assertIn('id="setMobArchCard"', self.settings_html)
        self.assertIn('PostgreSQL 16', self.settings_html)
        self.assertIn('UTF-8 Unicode (Khmer OK)', self.settings_html)

    def test_settings_mobile_legacy_data_sync_card(self):
        self.assertIn('id="setMobSyncCard"', self.settings_html)
        self.assertIn('Open inFlow SQL Sync Hub →', self.settings_html)

    def test_settings_mobile_database_backup_card(self):
        self.assertIn('id="setMobBackupCard"', self.settings_html)
        self.assertIn('Database Backup (.sql)', self.settings_html)
        self.assertIn('class="set-mob-badge-btn"', self.settings_html)

    def test_settings_mobile_sticky_save_button(self):
        self.assertIn('class="set-mob-sticky-bottom"', self.settings_html)
        self.assertIn('class="set-mob-save-btn"', self.settings_html)
        self.assertIn('submitMobCompanyForm()', self.settings_html)
        self.assertIn('Save Settings', self.settings_html)

    # =========================================================================
    # 3. Responsive Scoping (Only for Mobile View)
    # =========================================================================
    def test_css_desktop_hides_mobile_containers(self):
        # Product mobile container hidden on desktop
        self.assertIn('.product-mobile-app-container {', self.catalog_html)
        self.assertIn('display: none !important;', self.catalog_html)
        self.assertIn('html.is-desktop-view .product-mobile-app-container', self.catalog_html)

        # Settings mobile container hidden on desktop
        self.assertIn('.settings-mobile-app-container {', self.settings_html)
        self.assertIn('html.is-desktop-view .settings-mobile-app-container', self.settings_html)

    def test_css_mobile_hides_desktop_layouts(self):
        # Product desktop layout hidden on mobile
        self.assertIn('html.is-mobile-view .inflow-catalog-layout', self.catalog_html)
        # Settings desktop layout hidden on mobile
        self.assertIn('html.is-mobile-view #settingsDesktopLayout', self.settings_html)


if __name__ == '__main__':
    unittest.main()
