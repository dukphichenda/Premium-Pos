import unittest
from app import app

class TestDashboardChartNullSafety(unittest.TestCase):
    def test_dashboard_template_chart_null_guards(self):
        """
        Verify that dashboard.html guards both canvas lookups before calling getContext('2d')
        and skips execution in the host shell when canvas elements are not present.
        """
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            resp = client.get('/dashboard')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)

            # Ensure null guards exist for both canvases
            self.assertIn("const trendCanvas = document.getElementById('revenueTrendChart');", html)
            self.assertIn("const catCanvas = document.getElementById('categoryShareChart');", html)
            self.assertIn("if (!trendCanvas && !catCanvas)", html)
            self.assertIn("currentTrendCanvas && typeof Chart !== 'undefined'", html)
            self.assertIn("currentCatCanvas && typeof Chart !== 'undefined'", html)

            # Ensure getContext is only called on guarded canvas
            self.assertNotIn("document.getElementById('revenueTrendChart').getContext('2d')", html)
            self.assertNotIn("document.getElementById('categoryShareChart').getContext('2d')", html)

if __name__ == '__main__':
    unittest.main()
