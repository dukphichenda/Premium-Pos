import unittest
import json
from app import app
from database import query_one, execute
from routes.expenses import _get_monthly_report_data, _calculate_month_money_in_hand

class TestClearSKFeature(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
        self.test_month = "2031-07"
        execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s", (self.test_month,))

    def tearDown(self):
        execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s", (self.test_month,))

    def test_clear_sk_hq_saving_and_calculation(self):
        # 1. Update HQ Summary with clear_sk = 350.00 and clear_stm = 200.00
        resp = self.client.post('/expenses/summary/update', json={
            'month_key': self.test_month,
            'branch_id': 'main',
            'manual_opening_balance': 1000.00,
            'clear_stm': 200.00,
            'clear_sk': 350.00,
            'manual_media_income': 50.00,
            'custom_sales_income': 500.00,
            'accounts_json': [{"name": "Cash Drawer", "expr": "1000", "amount": 1000.0}]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertAlmostEqual(data.get('clear_sk'), 350.00, places=2)
        self.assertAlmostEqual(data.get('clear_stm'), 200.00, places=2)

        # 2. Check database persistence
        row = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)",
            (self.test_month,)
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row['clear_sk']), 350.00, places=2)
        self.assertAlmostEqual(float(row['clear_stm']), 200.00, places=2)

        # 3. Verify _get_monthly_report_data includes clear_sk in total_money_in and net_operating_income
        report = _get_monthly_report_data(self.test_month, branch_id='main')
        self.assertAlmostEqual(report['clear_sk'], 350.00, places=2)
        self.assertAlmostEqual(report['clear_stm'], 200.00, places=2)
        
        expected_total_in = 1000.00 + 200.00 + 350.00 + 50.00 + 500.00
        self.assertAlmostEqual(report['total_money_in'], expected_total_in, places=2)

        expected_net = (500.00 + 200.00 + 350.00 + 50.00) - report['total_expenses']
        self.assertAlmostEqual(report['net_operating_income'], expected_net, places=2)

        expected_money_in_hand = expected_total_in - report['total_expenses']
        self.assertAlmostEqual(report['money_in_hand'], expected_money_in_hand, places=2)

    def test_clear_sk_branch_is_zero(self):
        # 1. Update Branch Summary with clear_sk = 999.00 (should be zeroed)
        resp = self.client.post('/expenses/summary/update', json={
            'month_key': self.test_month,
            'branch_id': '1',
            'manual_opening_balance': 300.00,
            'clear_stm': 888.00,
            'clear_sk': 777.00,
            'custom_sales_income': 200.00,
            'accounts_json': [{"name": "Cash Drawer", "expr": "300", "amount": 300.0}]
        })
        self.assertEqual(resp.status_code, 200)

        row = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = 1",
            (self.test_month,)
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row['clear_sk']), 0.00, places=2)
        self.assertAlmostEqual(float(row['clear_stm']), 0.00, places=2)

        report = _get_monthly_report_data(self.test_month, branch_id='1')
        self.assertAlmostEqual(report['clear_sk'], 0.00, places=2)
        self.assertAlmostEqual(report['clear_stm'], 0.00, places=2)

if __name__ == '__main__':
    unittest.main()

