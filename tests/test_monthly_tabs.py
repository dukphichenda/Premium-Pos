import unittest
from app import app

class TestMonthlyTabs(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_switch_month_tabs(self):
        for m in ['2026-10', '2026-09', '2026-08', '2025-10']:
            resp = self.client.get(f'/expenses/monthly?month={m}&branch=main')
            self.assertEqual(resp.status_code, 200, f"Failed for month {m}")
            html = resp.get_data(as_text=True)
            self.assertIn('sheet-tabs-container', html)
            self.assertIn(f'month={m}', html)
            self.assertIn('data-no-tab="true"', html)
            self.assertIn('handleMonthTabClick', html)

    def test_summary_dashboard_tabs(self):
        resp = self.client.get('/expenses/summary-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('sheet-tabs-container', html)
        self.assertIn('data-no-tab="true"', html)

if __name__ == '__main__':
    unittest.main()

