import unittest
import os
import re

class TestReportUiAndInPlaceNavigation(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.index_path = os.path.join(self.base_dir, 'templates', 'reports', 'index.html')
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')

        with open(self.index_path, 'r', encoding='utf-8') as f:
            self.index_content = f.read()

        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

    def test_trial_pill_and_avatar_removed(self):
        # 1663 days left, Subscribe now, and (K) avatar must not be in headers
        self.assertNotIn('1663 days left', self.index_content)
        self.assertNotIn('Subscribe now', self.index_content)
        self.assertNotIn('1663 days left', self.viewer_content)
        self.assertNotIn('Subscribe now', self.viewer_content)
        self.assertNotIn('header-avatar', self.viewer_content)

    def test_unused_sidebar_categories_removed(self):
        # Unused categories from user screenshot 1 must not be in active sidebar
        sidebar_match = re.search(r'<aside class="inflow-hub-sidebar">(.*?)</aside>', self.index_content, re.DOTALL)
        self.assertTrue(sidebar_match, "Sidebar must exist")
        sidebar_html = sidebar_match.group(1)

        self.assertNotIn('Reordering and forecasting', sidebar_html)
        self.assertNotIn('Payment and accounting', sidebar_html)
        self.assertNotIn('Manufacturing', sidebar_html)
        self.assertNotIn('Stockroom scans', sidebar_html)
        self.assertNotIn('Audit log', sidebar_html)

        # Active categories must remain
        self.assertIn('Recent & saved', sidebar_html)
        self.assertIn('Sales', sidebar_html)
        self.assertIn('Stock levels', sidebar_html)
        self.assertIn('Purchasing', sidebar_html)
        self.assertIn('Branch Reports', sidebar_html)

    def test_report_cards_have_data_no_tab(self):
        # All report cards must have data-no-tab="true"
        card_tags = re.findall(r'<a [^>]*class="[^"]*inflow-web-card[^"]*"[^>]*>', self.index_content)
        self.assertGreater(len(card_tags), 10, "Should have multiple report cards")
        for tag in card_tags:
            self.assertIn('data-no-tab="true"', tag, f"Tag missing data-no-tab: {tag}")

    def test_open_report_tab_navigates_in_place(self):
        # openReportTab must not call inflowMdi.navigateOrOpenTab which spawns tabs
        self.assertNotIn('navigateOrOpenTab', self.index_content)
        self.assertIn('window.location.href = url;', self.index_content)

    def test_viewer_back_button_supports_browser_history(self):
        # Viewer back button must have data-no-tab="true" and use window.history.back
        self.assertIn('class="inflow-back-btn" title="Back to Reports list" data-no-tab="true"', self.viewer_content)
        self.assertIn('window.history.back()', self.viewer_content)

if __name__ == '__main__':
    unittest.main()
