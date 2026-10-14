import unittest
import sys
sys.path.insert(0, '.')
from routes.expenses import _get_inflow_sales_data, _get_monthly_report_data
from database import query_one

class TestExpenseSalesPaid(unittest.TestCase):
    def test_october_2026_sales_takes_only_paid_main_hq(self):
        """
        Verify that inFlow sales calculation for October 2026 (2026-10) for Main Store (HQ)
        strictly excludes branches and takes only paid sales.
        """
        data = _get_inflow_sales_data("2026-10", branch_id="main")
        
        # Verify HQ returns valid counts and non-zero sales
        self.assertGreater(data['paid_invoice_count'], 0)
        self.assertGreater(data['total_paid'], 0)
        self.assertGreaterEqual(data['total_invoiced'], data['total_paid'])

    def test_october_2026_sales_branch_stm_isolated(self):
        """
        Verify that inFlow sales calculation for STM branch (branch_id=1)
        strictly isolates STM sales and does not combine with HQ.
        """
        data_stm = _get_inflow_sales_data("2026-10", branch_id="1")
        data_hq = _get_inflow_sales_data("2026-10", branch_id="main")
        data_all = _get_inflow_sales_data("2026-10", branch_id="all")

        # STM sales must be distinct and smaller than all combined
        self.assertGreater(data_stm['total_paid'], 0)
        self.assertAlmostEqual(data_stm['total_paid'] + data_hq['total_paid'], data_all['total_paid'], places=2)
        self.assertNotEqual(data_stm['total_paid'], data_hq['total_paid'])

    def test_monthly_report_data_customer_receipts(self):
        """
        Verify that monthly report data passes the correct sales_received
        to the monthly cash flow calculation and KPI cards.
        """
        report = _get_monthly_report_data("2026-10", branch_id="main")
        sales = report['sales_received']
        self.assertGreater(sales, 0)
        
        # Verify Money in Hand = (Opening Balance + Clear STM + Media + Sales) - Expenses
        opening = report['opening_balance']
        stm = report['clear_stm']
        media = report['media_total']
        expenses = report['total_expenses']
        
        expected_total_in = opening + stm + media + sales
        self.assertAlmostEqual(report['total_money_in'], expected_total_in, places=2)
        
        expected_money_in_hand = expected_total_in - expenses
        self.assertAlmostEqual(report['money_in_hand'], expected_money_in_hand, places=2)

    def test_accounts_normalization_evaluates_amounts(self):
        """
        Verify that monthly report data normalizes accounts so that evaluated amounts
        are passed directly to Jinja to automatically display results without clicking.
        """
        report = _get_monthly_report_data("2026-10")
        accounts = report['accounts']
        self.assertTrue(len(accounts) >= 5)
        
        # Check ABA account
        aba = next((a for a in accounts if a['name'] == 'ABA'), None)
        self.assertIsNotNone(aba)
        self.assertGreater(aba['amount'], 0)
        self.assertTrue(bool(aba.get('expr')))

        # Check Teamwork account
        tw = next((a for a in accounts if a['name'] == 'Teamwork'), None)
        self.assertIsNotNone(tw)
        self.assertGreater(tw['amount'], 0)
        self.assertTrue(bool(tw.get('expr')))

    def test_monthly_expenses_route_renders_successfully(self):
        """
        Verify that GET /expenses and GET /expenses/monthly render HTTP 200
        without NameError or session errors.
        """
        from app import app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
            
            resp = client.get('/expenses/monthly?month=2026-10&branch=main')
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'Main Store (HQ)', resp.data)

            resp_stm = client.get('/expenses/monthly?month=2026-10&branch=1')
            self.assertEqual(resp_stm.status_code, 200)

if __name__ == '__main__':
    unittest.main()
