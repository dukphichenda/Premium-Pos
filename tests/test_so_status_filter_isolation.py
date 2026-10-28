import unittest
import os
import re

class TestSalesOrderStatusFilterIsolation(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.routes_path = os.path.join(self.base_dir, 'routes', 'sales_orders.py')
        self.detail_path = os.path.join(self.base_dir, 'templates', 'sales', 'detail.html')

        with open(self.routes_path, 'r', encoding='utf-8') as f:
            self.routes_content = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_content = f.read()

    def test_order_matches_status_filter_helper_exists(self):
        """Verify _order_matches_status_filter helper exists in routes/sales_orders.py"""
        self.assertIn("def _order_matches_status_filter(order, status_filter):", self.routes_content)

    def test_drawer_status_clauses_do_not_inject_mismatched_current_order(self):
        """Verify _get_drawer_and_metadata only injects current_order_id if just_saved or matches filter"""
        self.assertIn("if current_order_id and request.args.get('just_saved') == '1':", self.routes_content)
        self.assertIn("if single_order and (_order_matches_status_filter(single_order, status_filter) or request.args.get('just_saved') == '1'):", self.routes_content)

    def test_detail_order_redirects_when_viewing_mismatched_status(self):
        """Verify detail_order redirects to list_orders if order does not match requested status_filter"""
        self.assertIn("if not request.args.get('just_saved') and not _order_matches_status_filter(order, status_filter):", self.routes_content)
        self.assertIn("return redirect(url_for('sales_orders.list_orders',", self.routes_content)

    def test_frontend_selectSoStatusFilter_navigates_to_sales_when_status_changes(self):
        """Verify selectSoStatusFilter in detail.html navigates to /sales when current order does not match new status"""
        self.assertIn("const targetPath = orderMatchesFilter ? url.pathname : '/sales';", self.detail_content)
        self.assertIn("const targetUrl = targetPath + url.search;", self.detail_content)

    def test_find_latest_matching_so_supports_cancelled_and_loop_prevention(self):
        """Verify _find_latest_matching_so exists and handles CANCELLED without infinite redirect loops"""
        self.assertIn("def _find_latest_matching_so(is_main, user_bid, branch_filter, status_filter):", self.routes_content)
        self.assertIn("elif st in ('CANCELLED', 'CANCELED'):", self.routes_content)
        self.assertIn("latest = _find_latest_matching_so(is_main, user_bid, branch_filter, status_filter)", self.routes_content)
        self.assertIn("not request.args.get('_from_list')", self.routes_content)

if __name__ == '__main__':
    unittest.main()
