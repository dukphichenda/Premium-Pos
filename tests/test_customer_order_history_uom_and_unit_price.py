import unittest
import os
from app import app
from database import query_one, query_all

class TestCustomerOrderHistoryUomAndUnitPrice(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_sidebar_flyout_has_customer_order_history(self):
        """Verify Customer order history is below Sales reports in base.html flyout-reports."""
        base_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # In flyout-reports: Sales reports followed by Customer order history
        reports_idx = content.find('id="flyout-reports"')
        self.assertGreater(reports_idx, 0)
        sales_rep_idx = content.find('Sales reports', reports_idx)
        cust_hist_idx = content.find('Customer order history', sales_rep_idx)
        self.assertGreater(cust_hist_idx, sales_rep_idx, "Customer order history must be below Sales reports in Reports flyout")

        # In flyout-sales: Sale Order followed by Customer order history
        sales_flyout_idx = content.find('id="flyout-sales"')
        self.assertGreater(sales_flyout_idx, 0)
        sale_order_idx = content.find('Sale Order', sales_flyout_idx)
        cust_hist_sales_idx = content.find('Customer order history', sale_order_idx)
        self.assertGreater(cust_hist_sales_idx, sale_order_idx, "Customer order history must be below Sale Order in Sales flyout")

    def test_customer_order_history_rendered_uom_and_unit_price(self):
        """Verify report renders UNIT PRICE, exact billed UOM, and no quantity totals."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Check order SO-022914 for Ly Heng Chhun'y (from user's screenshot)
        so = query_one("SELECT customer_id FROM sales_orders WHERE order_number = 'SO-022914'")
        if so:
            cid = so['customer_id']
            res = self.client.get(f'/reports/view/customer-order-history?customer_id={cid}&date_from=2026-10-01&date_to=2026-10-31')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')

            # Headers
            self.assertIn('>UNIT PRICE<', html)
            self.assertIn('>QUANTITY<', html)
            self.assertIn('>AMOUNT<', html)

            # Order & Line details
            self.assertIn('SO-022914', html)
            self.assertIn('$0.24', html)
            self.assertIn('$30.00', html)
            self.assertIn('pcs.', html)

            # Amounts present
            self.assertIn('$103.75', html)

            # Verify no quantity totals (subtotal quantity 625.00 was removed)
            self.assertNotIn('>625.00<', html)

    def test_case_uom_preservation_in_customer_order_history(self):
        """Verify an order billed in cases shows 'cases' and display quantity, not pcs base units."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Find active order with 'cases' UOM
        case_line = query_one("""
            SELECT so.order_number, so.customer_id, so.order_date, sol.quantity_display, sol.uom, sol.unit_price, sol.subtotal
            FROM sales_orders so
            JOIN sales_order_lines sol ON sol.sales_order_id = so.id
            WHERE sol.uom = 'cases' AND sol.quantity_display IS NOT NULL AND so.status != 'CANCELLED'
            LIMIT 1
        """)
        if case_line:
            cid = case_line['customer_id']
            odate = str(case_line['order_date'])
            res = self.client.get(f'/reports/view/customer-order-history?customer_id={cid}&branch=all&date_range=Custom&date_from={odate}&date_to={odate}')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')

            # Must show 'cases' and display quantity
            self.assertIn(case_line['order_number'], html)
            self.assertIn('cases', html)
            qty_disp_str = f"{float(case_line['quantity_display']):,.0f}" if float(case_line['quantity_display']) % 1 == 0 else f"{float(case_line['quantity_display']):,.2f}"
            self.assertIn(qty_disp_str, html)

    def test_calculate_date_range_presets(self):
        """Verify calculate_date_range correctly computes all 21 presets matching Screenshot 2."""
        from routes.reports import calculate_date_range
        from datetime import datetime, date, timedelta

        now = datetime.now().date()
        presets = [
            'All', 'Today', 'This Week', 'This Month', 'This Quarter', 'This Year',
            'Yesterday', 'Last Week', 'Last Month', 'Last Quarter', 'Last Year',
            'Last 7 Days', 'Last 30 Days', 'Last 90 Days', 'Last 365 Days',
            'Tomorrow', 'Next Week', 'Next Month', 'Next Quarter', 'Next Year',
            'Custom'
        ]
        for p in presets:
            s, e = calculate_date_range(p, '2026-05-01', '2026-05-20')
            self.assertIsInstance(s, date, f"{p} start date must be a date")
            self.assertIsInstance(e, date, f"{p} end date must be a date")
            self.assertLessEqual(s, e, f"{p} start {s} must be <= end {e}")

        # Specific tests
        s_today, e_today = calculate_date_range('Today')
        self.assertEqual(s_today, now)
        self.assertEqual(e_today, now)

        s_yest, e_yest = calculate_date_range('Yesterday')
        self.assertEqual(s_yest, now - timedelta(days=1))
        self.assertEqual(e_yest, now - timedelta(days=1))

        s_7d, e_7d = calculate_date_range('Last 7 Days')
        self.assertEqual(s_7d, now - timedelta(days=7))
        self.assertEqual(e_7d, now)

        s_cust, e_cust = calculate_date_range('Custom', '2026-07-04', '2026-07-10')
        self.assertEqual(s_cust, date(2026, 7, 4))
        self.assertEqual(e_cust, date(2026, 7, 10))

    def test_viewer_date_dropdown_structure_and_presets(self):
        """Verify the report viewer date popover includes all Screenshot 2 options and custom range inputs."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/customer-order-history?date_range=This+Month')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Dropdown container and search input
        self.assertIn('popover-date-dropdown', html)
        self.assertIn('id="reportDateSearchInput"', html)

        # All 21 presets
        expected_presets = [
            'All', 'Today', 'This Week', 'This Month', 'This Quarter', 'This Year',
            'Yesterday', 'Last Week', 'Last Month', 'Last Quarter', 'Last Year',
            'Last 7 Days', 'Last 30 Days', 'Last 90 Days', 'Last 365 Days',
            'Tomorrow', 'Next Week', 'Next Month', 'Next Quarter', 'Next Year'
        ]
        for p in expected_presets:
            self.assertIn(f'data-name="{p}"', html, f"Preset {p} must be present in popover list")

        # Custom date range section
        self.assertIn('Custom Date Range', html)
        self.assertIn('id="reportDateFrom"', html)
        self.assertIn('id="reportDateTo"', html)
        self.assertIn('applyReportCustomDate()', html)
        self.assertIn('resetDatePopoverList', html)
        self.assertIn('filterDatePopoverList', html)

if __name__ == '__main__':
    unittest.main()
