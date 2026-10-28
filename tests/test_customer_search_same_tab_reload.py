import unittest
import os

class TestCustomerSearchSameTabReload(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.routes_path = os.path.join(self.base_dir, 'routes', 'sales_orders.py')
        self.detail_path = os.path.join(self.base_dir, 'templates', 'sales', 'detail.html')
        self.customers_path = os.path.join(self.base_dir, 'templates', 'contacts', 'customers.html')
        self.tabs_path = os.path.join(self.base_dir, 'static', 'js', 'inflow_tabs.js')

        with open(self.routes_path, 'r', encoding='utf-8') as f:
            self.routes_content = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_content = f.read()
        with open(self.customers_path, 'r', encoding='utf-8') as f:
            self.customers_content = f.read()
        with open(self.tabs_path, 'r', encoding='utf-8') as f:
            self.tabs_content = f.read()

    def test_routes_sales_orders_detail_order_has_search_guard(self):
        """Verify detail_order does not kick user out of mismatched status orders during customer search"""
        self.assertIn("has_search = bool((request.args.get('search') or request.args.get('q') or session.get('so_search_query') or '').strip())", self.routes_content)
        self.assertIn("if not has_search and status_filter and status_filter.lower() not in ('all', 'all orders'):", self.routes_content)

    def test_detail_html_does_not_force_status_filter_during_active_search(self):
        """Verify executeAnimatedOrderNavigation avoids forcing old status_filter when actively searching"""
        self.assertIn("if (!liveSearchVal && !url.searchParams.has('status_filter')) {", self.detail_content)

    def test_detail_html_fallback_navigates_in_place(self):
        """Verify fallback on missing canvas uses in-place navigation to stay in the current tab"""
        self.assertIn("window.location.href = finalUrl;", self.detail_content)

    def test_customers_html_open_order_does_not_force_new_tab(self):
        """Verify customer order history links reload in existing tab without forcing new tab"""
        self.assertIn("window.top.inflowMdi.navigateOrOpenTab(url, title || 'Sales Order', 'sales', false, true);", self.customers_content)

    def test_inflow_tabs_routes_sales_to_existing_sales_tab(self):
        """Verify inflow_tabs.js reloads existing sales tab rather than creating duplicate tabs"""
        self.assertIn("if (targetBase === 'sales') {", self.tabs_content)
        self.assertIn("const existingSalesTab = this.tabs.find(t => getBaseCategory(t.type) === 'sales');", self.tabs_content)
        self.assertIn("displayTitle = tab.title;", self.tabs_content)

    def test_customer_suggestion_selection_and_same_tab_status_filter(self):
        """Verify selectSoCustomerSuggestion passes id and executeSoSearch navigates in-place preserving status"""
        self.assertIn("executeSoSearch(name || '', id);", self.detail_content)
        self.assertIn("const targetUrl = '/sales' + url.search;", self.detail_content)
        self.assertIn("url.searchParams.set('status_filter', curStatus);", self.detail_content)
        self.assertIn("window.location.href = targetUrl;", self.detail_content)

    def test_routes_find_latest_matching_so_and_drawer_search(self):
        """Verify _find_latest_matching_so filters by customer_id and search, and drawer guards single_order"""
        self.assertIn("def _find_latest_matching_so(is_main, user_bid, branch_filter, status_filter, search=None, customer_id=None):", self.routes_content)
        self.assertIn("def _order_matches_search(order, query):", self.routes_content)
        self.assertIn("if not search_query or _order_matches_search(single_order, search_query):", self.routes_content)

    def test_clear_so_live_search_reloads_all_customers(self):
        """Verify clearSoLiveSearch sets search='' and reloads /sales to restore all customers"""
        self.assertIn("url.searchParams.set('search', '');", self.detail_content)
        self.assertIn("session.pop('so_search_query', None)", self.routes_content)

if __name__ == '__main__':
    unittest.main()
