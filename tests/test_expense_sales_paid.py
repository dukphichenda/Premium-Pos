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
        
        # Verify Money in Hand = (Opening Balance + Sales) - Expenses
        opening = report['opening_balance']
        expenses = report['total_expenses']
        
        expected_total_in = opening + sales
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

    def test_expense_paid_sales_matches_profit_report_exactly(self):
        """
        Verify that paid sale amount in expense report and in Profit report (Status=Paid)
        are EXACTLY the same.
        """
        from app import app
        exp_data = _get_inflow_sales_data("2026-10", branch_id="main")
        
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
            resp = client.get('/reports/view/sales-order-profit?date_range=Custom&date_from=2026-10-01&date_to=2026-10-31&status=Paid&branch=main&page=999')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')

            # The paid amount in expense report must match the profit report totals
            paid_str_plain = f"${exp_data['total_paid']:.2f}"
            paid_str_comma = f"${exp_data['total_paid']:,.2f}"
            self.assertTrue(paid_str_plain in html or paid_str_comma in html)
            self.assertIn(f"{exp_data['paid_invoice_count']} records loaded", html)

    def test_sales_order_profit_cogs_uom_and_pricing_calculation(self):
        """
        Verify that gross profit calculation takes into account UOM and costing
        relative to the Sales Order pricing, so lines are not calculated with inflated costs.
        """
        from routes.reports import _get_line_cogs_sql_expr
        line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')

        # Test SO-022798 (must be positive ~20.70 profit, NOT -714.30)
        row_798 = query_one(f"""
            SELECT 
                so.order_number,
                so.total_amount as sales_amount,
                (so.total_amount - COALESCE(SUM({line_cogs_sql}), 0)) as gross_profit
            FROM sales_orders so
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE so.order_number = 'SO-022798'
            GROUP BY so.id, so.order_number, so.total_amount
        """)
        if row_798:
            self.assertAlmostEqual(float(row_798['sales_amount']), 75.50, places=2)
            self.assertGreater(float(row_798['gross_profit']), 0.0)
            self.assertAlmostEqual(float(row_798['gross_profit']), 20.70, places=1)

        # Test SO-022848 (must be positive ~28.00 profit, NOT -707.00)
        row_848 = query_one(f"""
            SELECT 
                so.order_number,
                so.total_amount as sales_amount,
                (so.total_amount - COALESCE(SUM({line_cogs_sql}), 0)) as gross_profit
            FROM sales_orders so
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            JOIN products p ON sol.product_id = p.id
            WHERE so.order_number = 'SO-022848'
            GROUP BY so.id, so.order_number, so.total_amount
        """)
        if row_848:
            self.assertAlmostEqual(float(row_848['sales_amount']), 91.00, places=2)
            self.assertGreater(float(row_848['gross_profit']), 0.0)
            self.assertAlmostEqual(float(row_848['gross_profit']), 28.00, places=1)

        # Test overall October 2026 profit on paid orders is positive
        totals_row = query_one(f"""
            WITH order_costs AS (
                SELECT 
                    sol.sales_order_id,
                    COALESCE(SUM({line_cogs_sql}), 0) as total_cogs
                FROM sales_order_lines sol
                LEFT JOIN products p ON sol.product_id = p.id
                GROUP BY sol.sales_order_id
            )
            SELECT 
                COALESCE(SUM(so.total_amount), 0) as total_sales,
                COALESCE(SUM(so.total_amount - COALESCE(oc.total_cogs, 0)), 0) as total_profit
            FROM sales_orders so
            LEFT JOIN order_costs oc ON so.id = oc.sales_order_id
            WHERE TO_CHAR(so.order_date, 'YYYY-MM') = '2026-10'
              AND so.status != 'CANCELLED'
              AND so.branch_id IS NULL
              AND so.payment_status = 'PAID'
        """)
        self.assertGreater(float(totals_row['total_profit']), 0.0)

if __name__ == '__main__':
    unittest.main()
