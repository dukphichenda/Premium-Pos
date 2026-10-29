import unittest
import os

class TestCopySoSameTabAndNoExternalCdn(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.detail_path = os.path.join(self.base_dir, 'templates', 'sales', 'detail.html')
        self.base_path = os.path.join(self.base_dir, 'templates', 'base.html')
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_content = f.read()
        with open(self.base_path, 'r', encoding='utf-8') as f:
            self.base_content = f.read()

    def test_copy_so_stays_in_old_tab_no_new_tab(self):
        """Verify Copy SO stays in the current (old) tab and does not call navigateOrOpenTab or openTab"""
        self.assertIn("if (action === 'copy-so') {", self.detail_content)
        
        # Must navigate current window/iframe directly
        self.assertIn("window.location.href = targetUrl;", self.detail_content)
        
        # Must update active tab metadata in-place
        self.assertIn("window.top.inflowMdi.updateActiveTabMeta(targetUrl, 'Sales Order');", self.detail_content)
        
        # Copy action must NOT call navigateOrOpenTab which could spawn/switch tabs
        copy_block_start = self.detail_content.find("if (action === 'copy-so') {")
        self.assertNotEqual(copy_block_start, -1)
        copy_block_end = self.detail_content.find("if (action === 'create-po')", copy_block_start)
        self.assertNotEqual(copy_block_end, -1)
        copy_block = self.detail_content[copy_block_start:copy_block_end]
        
        self.assertNotIn("navigateOrOpenTab", copy_block)
        self.assertNotIn("openTab", copy_block)
        self.assertIn("window.location.href = targetUrl;", copy_block)

    def test_chart_js_hosted_locally_no_tracking_prevention_warnings(self):
        """Verify Chart.js is served locally from static/vendor to prevent browser Tracking Prevention warnings"""
        self.assertNotIn("cdn.jsdelivr.net", self.base_content)
        self.assertIn("vendor/chart.umd.min.js", self.base_content)
        
        # Confirm the file actually exists locally
        vendor_chart_path = os.path.join(self.base_dir, 'static', 'vendor', 'chart.umd.min.js')
        self.assertTrue(os.path.isfile(vendor_chart_path), "static/vendor/chart.umd.min.js must exist")
        self.assertGreater(os.path.getsize(vendor_chart_path), 50000, "chart.umd.min.js must not be empty")

if __name__ == '__main__':
    unittest.main()
