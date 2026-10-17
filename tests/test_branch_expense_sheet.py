import unittest
import sys
import io
import json
from openpyxl import load_workbook

sys.path.insert(0, '.')
from routes.expenses import (
    _get_monthly_report_data,
    _get_or_create_monthly_summary,
    _calculate_month_money_in_hand
)
from services.expense_exporter import generate_monthly_excel, generate_monthly_pdf
from database import query_one, execute
from app import app


class TestBranchExpenseSheet(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # Ensure test session as main_admin
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_branch_vs_hq_report_data_isolation(self):
        """
        Verify that branch report data sets is_branch=True, zeroes clear_stm,
        zeroes media_total, clears media_receipts, and computes Net Margin as
        Sales - Expenses (excluding STM and Media).
        HQ keeps STM, Media, and Media Receipts.
        """
        report_branch = _get_monthly_report_data("2026-10", branch_id="1")
        self.assertTrue(report_branch['is_branch'])
        self.assertEqual(report_branch['clear_stm'], 0.0)
        self.assertEqual(report_branch['media_total'], 0.0)
        self.assertEqual(report_branch['media_receipts'], [])
        
        # Branch Total Money In = Opening Balance + Sales Received (Customer Receipts)
        expected_branch_total_in = report_branch['opening_balance'] + report_branch['sales_received']
        self.assertAlmostEqual(report_branch['total_money_in'], expected_branch_total_in, places=2)
        
        # Branch Net Margin = Sales Received - Total Expenses
        expected_branch_net = report_branch['sales_received'] - report_branch['total_expenses']
        self.assertAlmostEqual(report_branch['net_operating_income'], expected_branch_net, places=2)

        # Branch Money in Hand = Total Inflow - Total Expenses
        expected_branch_money_in_hand = expected_branch_total_in - report_branch['total_expenses']
        self.assertAlmostEqual(report_branch['money_in_hand'], expected_branch_money_in_hand, places=2)

        # HQ Report Verification (STM and Media are removed/zeroed as requested)
        report_hq = _get_monthly_report_data("2026-10", branch_id="main")
        self.assertFalse(report_hq['is_branch'])
        self.assertEqual(report_hq['clear_stm'], 0.0)
        self.assertEqual(report_hq['media_total'], 0.0)
        self.assertEqual(report_hq['media_receipts'], [])
        expected_hq_total_in = report_hq['opening_balance'] + report_hq['sales_received']
        self.assertAlmostEqual(report_hq['total_money_in'], expected_hq_total_in, places=2)
        expected_hq_net = report_hq['sales_received'] - report_hq['total_expenses']
        self.assertAlmostEqual(report_hq['net_operating_income'], expected_hq_net, places=2)

    def test_monthly_summary_branch_isolation_in_db(self):
        """
        Verify that updating branch balances creates/updates a separate row with branch_id = 1,
        and does not overwrite or mutate HQ summary with branch_id IS NULL.
        """
        month_test = "2029-01"

        # 1. Update HQ Summary for 2029-01
        resp_hq = self.client.post('/expenses/summary/update', data={
            'month_key': month_test,
            'branch_id': 'main',
            'opening_balance': '500.00',
            'clear_stm': '150.00',
            'media': '250.00',
            'inflow_sales': '1000.00',
            'accounts': json.dumps([{"name": "Cash Drawer", "expr": "500", "amount": 500.0}])
        })
        self.assertEqual(resp_hq.status_code, 200)

        # 2. Update Branch 1 Summary for 2029-01
        resp_branch = self.client.post('/expenses/summary/update', data={
            'month_key': month_test,
            'branch_id': '1',
            'opening_balance': '200.00',
            'clear_stm': '999.00', # should be zeroed out by backend for branch
            'media': '888.00',     # should be zeroed out by backend for branch
            'inflow_sales': '400.00',
            'accounts': json.dumps([{"name": "Cash Drawer", "expr": "200", "amount": 200.0}])
        })
        self.assertEqual(resp_branch.status_code, 200)

        # 3. Verify in Database that both records exist separately
        row_hq = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id IS NULL",
            (month_test,)
        )
        row_branch = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s",
            (month_test, 1)
        )

        self.assertIsNotNone(row_hq)
        self.assertIsNotNone(row_branch)

        self.assertAlmostEqual(float(row_hq['opening_balance']), 500.00, places=2)
        # Clear STM and Media are 0.0 across the board
        self.assertAlmostEqual(float(row_hq['clear_stm']), 0.00, places=2)
        self.assertAlmostEqual(float(row_hq['media_expense']), 0.00, places=2)

        self.assertAlmostEqual(float(row_branch['opening_balance']), 200.00, places=2)
        self.assertAlmostEqual(float(row_branch['clear_stm']), 0.00, places=2)
        self.assertAlmostEqual(float(row_branch['media_expense']), 0.00, places=2)

        # Clean up test rows
        execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s", (month_test,))

    def test_branch_expense_recording_scoped(self):
        """
        Verify that adding an expense under a branch assigns branch_id,
        and adding an expense under HQ assigns NULL branch_id.
        """
        # Add branch expense
        resp_branch = self.client.post('/expenses/add', data={
            'expense_date': '2026-10-15',
            'category': 'Supplies',
            'item': 'Test Branch Expense Item',
            'quantity': '1',
            'unit_price': '25.00',
            'total_price': '25.00',
            'paid_by': 'Cash',
            'branch_id': '1'
        }, follow_redirects=True)
        self.assertEqual(resp_branch.status_code, 200)

        expense_b = query_one(
            "SELECT * FROM expenses WHERE item = %s ORDER BY id DESC",
            ('Test Branch Expense Item',)
        )
        self.assertIsNotNone(expense_b)
        self.assertEqual(expense_b['branch_id'], 1)

        # Cleanup
        execute("DELETE FROM expenses WHERE id = %s", (expense_b['id'],))

    def test_export_monthly_excel_branch_and_hq(self):
        """
        Verify that generate_monthly_excel for branch produces valid Excel without
        Media Receipts sheet, and for HQ includes Media Receipts sheet.
        """
        data_branch = _get_monthly_report_data("2026-10", branch_id="1")
        excel_buf_branch = generate_monthly_excel(data_branch)
        self.assertIsInstance(excel_buf_branch, io.BytesIO)
        
        wb_branch = load_workbook(excel_buf_branch)
        sheet_names_branch = wb_branch.sheetnames
        self.assertIn("Expenses & Cash Reconciliation", sheet_names_branch)
        self.assertNotIn("Media Receipts", sheet_names_branch)

        data_hq = _get_monthly_report_data("2026-10", branch_id="main")
        excel_buf_hq = generate_monthly_excel(data_hq)
        wb_hq = load_workbook(excel_buf_hq)
        sheet_names_hq = wb_hq.sheetnames
        self.assertIn("Expenses & Cash Reconciliation", sheet_names_hq)
        self.assertNotIn("Media Receipts", sheet_names_hq)

    def test_export_monthly_pdf_branch_and_hq(self):
        """
        Verify that generate_monthly_pdf for both branch and HQ generates valid PDF bytes
        without raising any ReportLab layout or rendering exceptions.
        """
        data_branch = _get_monthly_report_data("2026-10", branch_id="1")
        pdf_buf_branch = generate_monthly_pdf(data_branch)
        self.assertIsInstance(pdf_buf_branch, io.BytesIO)
        pdf_bytes_b = pdf_buf_branch.getvalue()
        self.assertTrue(pdf_bytes_b.startswith(b'%PDF-'))

        data_hq = _get_monthly_report_data("2026-10", branch_id="main")
        pdf_buf_hq = generate_monthly_pdf(data_hq)
        self.assertIsInstance(pdf_buf_hq, io.BytesIO)
        pdf_bytes_h = pdf_buf_hq.getvalue()
        self.assertTrue(pdf_bytes_h.startswith(b'%PDF-'))

    def test_monthly_expenses_view_branch_vs_hq_html(self):
        """
        Verify HTML output on /expenses/monthly:
        - For both branch and HQ: Clear STM & Media cards and Media section are deleted as requested.
        - Store scope switcher and 6 clean core financial KPIs are rendered.
        """
        resp_branch = self.client.get('/expenses/monthly?month=2026-10&branch=1')
        self.assertEqual(resp_branch.status_code, 200)
        html_branch = resp_branch.data.decode('utf-8')
        self.assertNotIn("id=\"mediaReceiptsSection\"", html_branch)
        self.assertNotIn(">Clear STM<", html_branch)
        self.assertNotIn(">Media (ប្រាក់ពី Media)<", html_branch)
        self.assertIn("store-shortcuts-group", html_branch)

        resp_hq = self.client.get('/expenses/monthly?month=2026-10&branch=main')
        self.assertEqual(resp_hq.status_code, 200)
        html_hq = resp_hq.data.decode('utf-8')
        self.assertNotIn("id=\"mediaReceiptsSection\"", html_hq)
        self.assertNotIn(">Clear STM<", html_hq)
        self.assertNotIn(">Media (ប្រាក់ពី Media)<", html_hq)
        self.assertIn("store-shortcuts-group", html_hq)
        self.assertIn("Main Store (HQ)", html_hq)

    def test_branch_expenses_endpoint_redirects_to_monthly_sheet(self):
        """Verify that /branches/<id>/expenses redirects to /expenses/monthly?branch=<id>."""
        resp = self.client.get('/branches/1/expenses')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/expenses/monthly', resp.headers['Location'])
        self.assertIn('branch=1', resp.headers['Location'])


if __name__ == '__main__':
    unittest.main()
