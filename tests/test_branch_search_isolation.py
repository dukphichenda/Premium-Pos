import unittest
import os

class TestBranchSearchIsolation(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.branches_routes_path = os.path.join(self.base_dir, 'routes', 'branches.py')
        self.so_routes_path = os.path.join(self.base_dir, 'routes', 'sales_orders.py')
        self.detail_path = os.path.join(self.base_dir, 'templates', 'sales', 'detail.html')
        self.tabs_path = os.path.join(self.base_dir, 'static', 'js', 'inflow_tabs.js')
        self.base_tpl_path = os.path.join(self.base_dir, 'templates', 'base.html')

        with open(self.branches_routes_path, 'r', encoding='utf-8') as f:
            self.branches_content = f.read()
        with open(self.so_routes_path, 'r', encoding='utf-8') as f:
            self.so_content = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_content = f.read()
        with open(self.tabs_path, 'r', encoding='utf-8') as f:
            self.tabs_content = f.read()
        with open(self.base_tpl_path, 'r', encoding='utf-8') as f:
            self.base_tpl_content = f.read()

    def test_branches_switch_clears_so_search_query(self):
        """Verify switch_branch in routes/branches.py clears search query on store switch"""
        self.assertIn("session.pop('so_search_query', None)", self.branches_content)
        self.assertIn("session.pop('so_customer_search', None)", self.branches_content)
        self.assertIn("session.pop('so_search_branch', None)", self.branches_content)

    def test_sales_orders_routes_scope_search_by_branch(self):
        """Verify sales orders routes track and isolate search query per branch"""
        self.assertIn("session['so_search_branch']", self.so_content)
        self.assertIn("saved_search_branch and saved_search_branch != current_b_str", self.so_content)
        self.assertIn("saved_branch and saved_branch != current_scope_str", self.so_content)
        self.assertIn("saved_branch and saved_branch != order_branch_str", self.so_content)

    def test_inflow_tabs_switch_store_clears_session_storage(self):
        """Verify switchStoreContext in static/js/inflow_tabs.js removes search keys from sessionStorage"""
        self.assertIn("sessionStorage.removeItem('inflow_so_search_query')", self.tabs_content)
        self.assertIn("sessionStorage.removeItem('inflow_so_drawer_customer_search')", self.tabs_content)
        self.assertIn("sessionStorage.removeItem('inflow_so_search_branch')", self.tabs_content)

    def test_base_html_store_switch_clears_session_storage(self):
        """Verify store switch links in base.html clear sessionStorage search keys"""
        self.assertIn("sessionStorage.removeItem('inflow_so_search_query')", self.base_tpl_content)
        self.assertIn("sessionStorage.removeItem('inflow_so_drawer_customer_search')", self.base_tpl_content)
        self.assertIn("sessionStorage.removeItem('inflow_so_search_branch')", self.base_tpl_content)

    def test_detail_html_resets_search_when_branch_changes(self):
        """Verify detail.html detects branch scope change and discards previous branch search"""
        self.assertIn("lastSearchBranch && lastSearchBranch !== currentBranchScope", self.detail_content)
        self.assertIn("sessionStorage.setItem('inflow_so_search_branch', currentBranchScope)", self.detail_content)
        self.assertIn("window.CURRENT_BRANCH_SCOPE", self.detail_content)

if __name__ == '__main__':
    unittest.main()
