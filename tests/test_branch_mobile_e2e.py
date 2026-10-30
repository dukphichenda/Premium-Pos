import unittest
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app

class TestBranchMobileE2E(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'admin'
            sess['username'] = 'admin'

    def test_branch_workspace_mobile_view(self):
        """Verify accessing branch workspace in mobile mode renders full mobile dashboard."""
        res = self.client.get('/branches/1/workspace?view=mobile')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8', errors='ignore')

        # Check mobile dashboard components
        self.assertIn('so-mobile-dashboard-view', html)
        self.assertIn('so-mob-dash-header', html)
        self.assertIn('so-mob-logistics-grid', html)
        self.assertIn('so-mob-quick-actions-grid', html)
        self.assertIn('so-mob-workflow-grid', html)
        self.assertIn('so-mob-kpi-grid', html)
        self.assertIn('mobileRevenueTrendChart', html)
        self.assertIn('mobileCategoryShareChart', html)
        self.assertIn('mobileCategoryLegend', html)
        self.assertIn('so-mobile-nav-bar', html)
        # Verify the top bar in the red rectangle is deleted
        self.assertNotIn('branch-context-indicator-bar', html)
        self.assertNotIn('Branch Mode Active:', html)

    def test_branch_workspace_desktop_view(self):
        """Verify accessing branch workspace in desktop mode preserves classic workflow card."""
        res = self.client.get('/branches/1/workspace?view=desktop')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8', errors='ignore')

        self.assertIn('so-desktop-dashboard-wrap', html)
        self.assertIn('inflow-workflow-card', html)

    def test_branch_charts_api(self):
        """Verify /api/dashboard/charts?branch=1 returns valid JSON chart series."""
        res = self.client.get('/api/dashboard/charts?branch=1')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('monthly_labels', data)
        self.assertIn('monthly_revenue', data)
        self.assertIn('category_labels', data)
        self.assertIn('category_values', data)

    def test_branch_switching(self):
        """Verify switching context between HQ (0) and Branch (1) redirects cleanly."""
        res1 = self.client.get('/branches/switch/1', follow_redirects=False)
        self.assertEqual(res1.status_code, 302)
        loc1 = res1.headers.get('Location', '')
        self.assertTrue('/branches/1/dashboard' in loc1 or '/branches/1/workspace' in loc1, f"Unexpected location: {loc1}")

        res0 = self.client.get('/branches/switch/0', follow_redirects=False)
        self.assertEqual(res0.status_code, 302)
        self.assertIn('/dashboard', res0.headers.get('Location'))

if __name__ == '__main__':
    unittest.main()
