import unittest
import sys
sys.path.insert(0, '.')
from routes.expenses import _get_inflow_sales_data, _get_monthly_report_data
from database import query_one

class TestExpenseSalesPaid(unittest.TestCase):
    def test_october_2026_sales_takes_only_paid(self):
        """
        Verify that inFlow sales calculation for October 2026 (2026-10)
        takes strictly only paid sales money ($12,888.75) and not PO payments or invoiced totals.
        """
        data = _get_inflow_sales_data("2026-10")
        
        # October 2026 sales orders:
        # 136 total orders ($17,240.95 total invoiced)
        # 97 paid orders ($12,888.75 total paid)
        # 39 open orders ($4,352.20 balance due, $0 paid)
        self.assertEqual(data['invoice_count'], 136)
        self.assertEqual(data['paid_invoice_count'], 97)
        self.assertAlmostEqual(data['total_invoiced'], 17240.95, places=2)
        self.assertAlmostEqual(data['total_paid'], 12888.75, places=2)

    def test_monthly_report_data_customer_receipts(self):
        """
        Verify that monthly report data passes the correct sales_received ($12,888.75)
        to the monthly cash flow calculation and KPI cards.
        """
        report = _get_monthly_report_data("2026-10")
        self.assertAlmostEqual(report['sales_received'], 12888.75, places=2)
        
        # Verify Money in Hand = (Opening Balance + Clear STM + Media + Sales) - Expenses
        opening = report['opening_balance']
        stm = report['clear_stm']
        media = report['media_total']
        sales = report['sales_received']
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
        self.assertAlmostEqual(aba['amount'], 6533.025, places=2)
        self.assertEqual(aba['expr'], '=5592+3764100/4000')

        # Check Teamwork account
        tw = next((a for a in accounts if a['name'] == 'Teamwork'), None)
        self.assertIsNotNone(tw)
        self.assertAlmostEqual(tw['amount'], 109.66, places=2)
        self.assertEqual(tw['expr'], '=9.66+100')

if __name__ == '__main__':
    unittest.main()

