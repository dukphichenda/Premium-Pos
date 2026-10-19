import unittest
from app import app
from routes.reports import _get_line_cogs_sql_expr
from database import query_one

class TestDashboardChartProfitMatch(unittest.TestCase):
    def test_dashboard_chart_paid_profit_matches_profit_report(self):
        """
        Verify that the monthly financial breakdown chart's Profit metric
        uses canonical COGS and matches the Sales Order Profit report exactly.
        """
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            chart_resp = client.get('/api/dashboard/charts?branch=main')
            self.assertEqual(chart_resp.status_code, 200)
            chart_data = chart_resp.get_json()

            self.assertIn('monthly_labels', chart_data)
            self.assertIn('monthly_paid', chart_data)
            self.assertIn('monthly_profit', chart_data)
            self.assertIn('monthly_total_profit', chart_data)

            # If Oct 2026 is present, verify against canonical query
            if 'Oct 2026' in chart_data['monthly_labels']:
                idx = chart_data['monthly_labels'].index('Oct 2026')
                chart_paid = chart_data['monthly_paid'][idx]
                chart_profit = chart_data['monthly_profit'][idx]

                line_cogs_sql = _get_line_cogs_sql_expr('sol', 'p')
                rep_sql = f"""
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
                    WHERE so.status != 'CANCELLED' 
                      AND (so.branch_id IS NULL OR so.branch_id = 0)
                      AND (so.payment_status = 'PAID' OR so.status = 'PAID')
                      AND so.order_date >= '2026-10-01' AND so.order_date <= '2026-10-31'
                """
                db_row = query_one(rep_sql)
                expected_sales = round(float(db_row['total_sales']), 2)
                expected_profit = round(float(db_row['total_profit']), 2)

                self.assertEqual(chart_paid, expected_sales)
                self.assertEqual(chart_profit, expected_profit)

if __name__ == '__main__':
    unittest.main()
