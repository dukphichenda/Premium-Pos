import unittest
import json
from app import app
from database import query_one, execute

class TestSoStoreScopeAndProductDecimals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_sales_order_drawer_no_store_scope(self):
        """
        Verify that Store Scope dropdown is removed from Sales Order search drawer.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        # Verify drawerBranchSelect is completely removed from the drawer filters
        self.assertNotIn('id="drawerBranchSelect"', html)
        self.assertNotIn('<span class="inflow-filter-label" style="font-weight: 700; color: #334155; white-space: nowrap; font-size: 11px;">Store Scope</span>', html)
        
        # Verify Order Date and Status filters are still intact
        self.assertIn('id="drawerDateFilterSelect"', html)
        self.assertIn('id="drawerStatusFilterInput"', html)

    def test_product_detail_decimal_settings_ajax(self):
        """
        Verify that product price_decimals and cost_decimals can be saved via update_product_ajax
        and are properly persisted and reflected in the product detail catalog view.
        """
        prod = query_one("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        self.assertIsNotNone(prod)
        pid = prod['id']

        # 1. Update price_decimals=3 and cost_decimals=4
        resp = self.client.post(f'/products/{pid}/update_ajax',
                                data=json.dumps({'price_decimals': 3, 'cost_decimals': 4}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data.get('price_decimals'), 3)
        self.assertEqual(data.get('cost_decimals'), 4)

        # 2. Verify database values
        db_prod = query_one("SELECT price_decimals, cost_decimals FROM products WHERE id = %s", (pid,))
        self.assertEqual(db_prod['price_decimals'], 3)
        self.assertEqual(db_prod['cost_decimals'], 4)

        # 3. Verify catalog view renders decimal precision selects
        cat_resp = self.client.get(f'/products/{pid}')
        self.assertEqual(cat_resp.status_code, 200)
        cat_html = cat_resp.data.decode('utf-8')
        self.assertIn('id="catPriceDecimalsSelect"', cat_html)
        self.assertIn('id="catCostDecimalsSelect"', cat_html)

        # 4. Clean up / reset to None (System Default)
        resp_reset = self.client.post(f'/products/{pid}/update_ajax',
                                      data=json.dumps({'price_decimals': None, 'cost_decimals': None}),
                                      content_type='application/json')
        self.assertEqual(resp_reset.status_code, 200)

if __name__ == '__main__':
    unittest.main()
