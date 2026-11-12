import unittest
import os
import re
from app import create_app
from database import query_all, query_one

class StockAdjustmentTabAndNewRowTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

    def test_inflow_tabs_switching_does_not_guard_switch_or_create(self):
        """Verify inflow_tabs.js no longer guards switchTab or createTab with handleTabCloseAttempt."""
        tabs_path = os.path.join(self.app.root_path, 'static', 'js', 'inflow_tabs.js')
        with open(tabs_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check createTab definition does not contain handleTabCloseAttempt
        create_tab_match = re.search(r'createTab:\s*function\s*\([^)]*\)\s*\{(.*?)\n\s*const newId', content, re.DOTALL)
        self.assertTrue(create_tab_match, "createTab method should be present in inflow_tabs.js")
        self.assertNotIn('handleTabCloseAttempt', create_tab_match.group(1))

        # Check switchTab definition does not contain handleTabCloseAttempt
        switch_tab_match = re.search(r'switchTab:\s*function\s*\([^)]*\)\s*\{(.*?)\n\s*this\.activeTabId = tabId;', content, re.DOTALL)
        self.assertTrue(switch_tab_match, "switchTab method should be present in inflow_tabs.js")
        self.assertNotIn('handleTabCloseAttempt', switch_tab_match.group(1))

        # closeTab should still guard with handleTabCloseAttempt
        self.assertIn("handleTabCloseAttempt('__CLOSE__', tabId)", content)

    def test_adjustment_form_only_guards_own_tab_close(self):
        """Verify adjustment_form.html handleTabCloseAttempt returns true for non-__CLOSE__ targets."""
        res = self.client.get('/inventory/adjustments/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check guard check
        self.assertIn("window.handleTabCloseAttempt", html)
        self.assertIn("targetUrl !== '__CLOSE__'", html)

    def test_add_product_moved_to_bottom_table_matching_sales_order(self):
        """Verify product search box moved from top toolbar to bottom of table."""
        res = self.client.get('/inventory/adjustments/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # 1. Top toolbar should NOT have inflow-adj-mode-search
        self.assertNotIn('inflow-adj-mode-search', html)

        # 2. Table should have bottom row #adjNewRowEntry
        self.assertIn('id="adjNewRowEntry"', html)
        self.assertIn('class="inflow-adj-new-row"', html)
        self.assertIn('id="adjProductLiveSearch"', html)
        self.assertIn('placeholder="Type to add item..."', html)
        self.assertIn('Add one by one', html)  # Satisfies compatibility requirement

        # 3. Footer bar with + Add Row and shortcuts
        self.assertIn('class="so-table-footer-bar"', html)
        self.assertIn('+ Add Row', html)
        self.assertIn('Shortcuts: Press <kbd', html)
        self.assertIn('F2', html)

        # 4. JavaScript functions for keyboard and row insertion
        self.assertIn('function focusAdjSearchInput()', html)
        self.assertIn('function onLiveProductSearchKeyDown(e)', html)
        self.assertIn('tbody.insertBefore(tr, newRow)', html)
        self.assertIn('focusAdjSearchInput()', html)

    def test_zero_test_sales_orders_in_db(self):
        """Strict rule: 0 test sales orders exist in DB."""
        test_orders = query_all("SELECT id, order_number FROM sales_orders WHERE order_number ILIKE %s OR order_number ILIKE %s", ('%TEST%', '%TEMP%'))
        self.assertEqual(len(test_orders), 0, f"Found lingering test sales orders: {test_orders}")

if __name__ == '__main__':
    unittest.main()

