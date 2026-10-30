import unittest
import os
import re

class TestBranchMobileParity(unittest.TestCase):
    def setUp(self):
        self.branch_tpl_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'branches', 'dashboard.html')
        self.dash_tpl_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'dashboard.html')
        self.base_tpl_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'base.html')
        self.css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'mobile_dashboard.css')

        with open(self.branch_tpl_path, 'r', encoding='utf-8') as f:
            self.branch_html = f.read()
        with open(self.dash_tpl_path, 'r', encoding='utf-8') as f:
            self.dash_html = f.read()
        with open(self.base_tpl_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()
        with open(self.css_path, 'r', encoding='utf-8') as f:
            self.css = f.read()

    def test_mobile_css_linked_and_contains_rules(self):
        """Verify mobile_dashboard.css is linked in base.html and has required responsive classes."""
        self.assertIn('mobile_dashboard.css', self.base_html)
        self.assertIn('.so-mobile-dashboard-view', self.css)
        self.assertIn('.so-desktop-dashboard-wrap', self.css)
        self.assertIn('html.is-mobile-view .so-mobile-dashboard-view', self.css)
        self.assertIn('html.is-mobile-view .so-desktop-dashboard-wrap', self.css)

    def test_branch_dashboard_has_mobile_view(self):
        """Verify templates/branches/dashboard.html has full mobile dashboard markup matching HQ."""
        self.assertIn('class="so-mobile-dashboard-view"', self.branch_html)
        self.assertIn('class="so-desktop-dashboard-wrap"', self.branch_html)
        self.assertIn('class="so-mob-dash-header"', self.branch_html)
        self.assertIn('class="so-mob-logistics-grid"', self.branch_html)
        self.assertIn('class="so-mob-quick-actions-grid"', self.branch_html)
        self.assertIn('class="so-mob-workflow-grid"', self.branch_html)
        self.assertIn('class="so-mob-kpi-grid"', self.branch_html)
        self.assertIn('id="mobileRevenueTrendChart"', self.branch_html)
        self.assertIn('id="mobileCategoryShareChart"', self.branch_html)
        self.assertIn('id="mobileCategoryLegend"', self.branch_html)

    def test_branch_dashboard_has_quick_actions(self):
        """Verify branch mobile quick actions include branch_new_order, POS/PO, inventory, and transfers."""
        self.assertIn('branches.branch_new_order', self.branch_html)
        self.assertIn('branches.branch_inventory', self.branch_html)
        self.assertIn('branches.branch_transfers', self.branch_html)

    def test_branch_dashboard_has_chart_scripts(self):
        """Verify branch dashboard has Chart.js fetching charts for this branch."""
        self.assertIn('/api/dashboard/charts?branch=', self.branch_html)
        self.assertIn('mobileRevenueTrendChartInstance', self.branch_html)
        self.assertIn('mobileCategoryShareChartInstance', self.branch_html)

    def test_drawer_branch_switch_urls(self):
        """Verify base.html Mobile Profile Drawer links switch branches via switch_branch endpoint."""
        self.assertIn("branches.switch_branch", self.base_html)

    def test_top_branch_indicator_bar_removed(self):
        """Verify the legacy top branch indicator banner in the red rectangle is removed from base.html."""
        self.assertNotIn('class="branch-context-indicator-bar', self.base_html)
        self.assertNotIn('<strong>Branch Mode Active:</strong>', self.base_html)

if __name__ == '__main__':
    unittest.main()

