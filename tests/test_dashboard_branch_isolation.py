import unittest
import sys
sys.path.insert(0, '.')
from app import app
from database import query_one

class TestDashboardBranchIsolation(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_dashboard_default_is_main_hq(self):
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn('Main Store (HQ)', content)
        self.assertIn('HQ DIRECT SALES', content)
        self.assertIn('Separate Store & Branch Performance', content)

    def test_dashboard_scoped_to_stm_branch(self):
        res = self.client.get('/dashboard?branch=1')
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn('STM', content)
        self.assertIn('STM DIRECT SALES', content)
        self.assertIn('Premium Ecopack STM', content)

    def test_dashboard_scoped_to_all_combined(self):
        res = self.client.get('/dashboard?branch=all')
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn('All Outlets Combined', content)
        self.assertIn('ALL DIRECT SALES', content)

    def test_chart_api_isolation(self):
        # 1. Main Store (HQ)
        res_hq = self.client.get('/api/dashboard/charts?branch=main')
        self.assertEqual(res_hq.status_code, 200)
        data_hq = res_hq.get_json()
        total_hq_revenue = sum(data_hq.get('monthly_revenue', []))

        # 2. STM Branch
        res_stm = self.client.get('/api/dashboard/charts?branch=1')
        self.assertEqual(res_stm.status_code, 200)
        data_stm = res_stm.get_json()
        total_stm_revenue = sum(data_stm.get('monthly_revenue', []))

        # 3. All Combined
        res_all = self.client.get('/api/dashboard/charts?branch=all')
        self.assertEqual(res_all.status_code, 200)
        data_all = res_all.get_json()
        total_all_revenue = sum(data_all.get('monthly_revenue', []))

        # Verify separation: STM and HQ revenue must be isolated and both sum up to approx All Combined
        self.assertGreater(total_hq_revenue, 0)
        self.assertGreater(total_stm_revenue, 0)
        self.assertNotEqual(total_hq_revenue, total_stm_revenue)
        self.assertAlmostEqual(total_hq_revenue + total_stm_revenue, total_all_revenue, places=1)

if __name__ == '__main__':
    unittest.main()
