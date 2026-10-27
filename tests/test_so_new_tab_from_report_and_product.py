import unittest
import os
import re

class TestSalesOrderNewTabFromReportAndProduct(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')
        self.workspace_main_path = os.path.join(self.base_dir, 'templates', 'products', '_catalog_workspace_main.html')
        self.catalog_path = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')
        self.product_detail_path = os.path.join(self.base_dir, 'templates', 'products', 'detail.html')
        self.inflow_tabs_path = os.path.join(self.base_dir, 'static', 'js', 'inflow_tabs.js')

        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()
        with open(self.workspace_main_path, 'r', encoding='utf-8') as f:
            self.workspace_main_content = f.read()
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            self.catalog_content = f.read()
        with open(self.product_detail_path, 'r', encoding='utf-8') as f:
            self.product_detail_content = f.read()
        with open(self.inflow_tabs_path, 'r', encoding='utf-8') as f:
            self.inflow_tabs_content = f.read()

    def test_report_sales_order_links_open_new_tab(self):
        """Verify sales order links in report viewer call openTab with forceNew = true"""
        # In Sales Order Profit Report
        self.assertIn("window.top.inflowMdi.openTab('{{ url_for('sales_orders.detail_order', id=r.id) }}', 'Sales Order {{ r.order_number }}', 'sales', true);", self.viewer_content)
        # In Customer Order History
        self.assertIn("window.top.inflowMdi.openTab('{{ url_for('sales_orders.detail_order', id=ord.sales_order_id) }}', 'Sales Order {{ ord.order_number }}', 'sales', true);", self.viewer_content)

    def test_product_detail_sales_order_history_opens_new_tab(self):
        """Verify sales order links in Product Detail order history call openTab with forceNew = true"""
        self.assertIn("window.top.inflowMdi.openTab('{{ url_for('sales_orders.detail_order', id=ord.order_id) }}', 'Sales Order {{ ord.order_number }}', 'sales', true);", self.workspace_main_content)

    def test_product_catalog_nav_handlers_pass_force_new(self):
        """Verify catalog.html handleNavClick and proceedNavigation pass forceNew = true for sales orders"""
        self.assertIn("window.top.inflowMdi.openTab(url, 'Sales Order', 'sales', true);", self.catalog_content)

    def test_legacy_product_detail_opens_new_tab(self):
        """Verify legacy product detail order history table passes forceNew = true"""
        self.assertIn("openTab('{{ url_for('sales_orders.detail_order', id=ord.order_id) }}', 'Sales Order: {{ ord.order_number }}', 'sales', true);", self.product_detail_content)

    def test_inflow_tabs_detect_type_prioritizes_reports(self):
        """Verify detectTypeFromUrl checks reports before sales to avoid misidentifying sales reports as sales category"""
        reports_pos = self.inflow_tabs_content.find("if (clean.includes('/reports')) return 'reports';")
        sales_pos = self.inflow_tabs_content.find("if (clean.includes('/sales')")
        self.assertNotEqual(reports_pos, -1, "detectTypeFromUrl must check /reports")
        self.assertNotEqual(sales_pos, -1, "detectTypeFromUrl must check /sales")
        self.assertLess(reports_pos, sales_pos, "/reports check must come before /sales check")

    def test_inflow_tabs_title_preserves_hyphenated_order_numbers(self):
        """Verify title extraction does not truncate order numbers at hyphen (e.g. SO-022407)"""
        self.assertNotIn("docTitle.split('|')[0].split('-')[0].trim()", self.inflow_tabs_content)
        self.assertIn("pageTitle.split(' - inFlow')[0].trim()", self.inflow_tabs_content)

    def test_inflow_tabs_click_interceptor_forces_new_tab_for_orders(self):
        """Verify embedded click interceptor automatically forces new tab for orders from reports or product pages"""
        self.assertIn("const forceNewTab = (isFromReport || isFromProduct) && (isSalesOrder || isPurchaseOrder);", self.inflow_tabs_content)
        self.assertIn("window.top.inflowMdi.openTab(href, tabTitle, isSalesOrder ? 'sales' : 'purchase', true);", self.inflow_tabs_content)

if __name__ == '__main__':
    unittest.main()
