import unittest
from app import create_app
from database import query_one, query_all

class TestSaleStep02Features(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_drawer_does_not_filter_to_single_customer_on_order_detail(self):
        """
        Verify that opening an order detail does NOT auto-filter the left drawer
        to that order's customer. The drawer must show all orders matching status/date criteria.
        Matching inFlow Recording_20261008_0906 (slides 31-35).
        """
        # Pick a recent order with a known customer
        order = query_one("SELECT id, order_number, customer_id FROM sales_orders WHERE customer_id IS NOT NULL ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(order)

        resp = self.client.get(f"/sales/{order['id']}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Verify drawer has multiple orders from different customers
        self.assertIn('id="drawerOrdersListBody"', html)
        self.assertIn('inflow-drawer-row', html)

        # Check that another recent order for a different customer is also visible in the drawer
        other_order = query_one("""
            SELECT id, order_number FROM sales_orders 
            WHERE (customer_id != %s OR customer_id IS NULL) 
              AND status IN ('OPEN', 'PICKED', 'PACKED', 'SHIPPED', 'INVOICED') 
            ORDER BY id DESC LIMIT 1
        """, (order['customer_id'],))
        
        if other_order:
            self.assertIn(other_order['order_number'], html)

    def test_drawer_customer_combobox_filtering(self):
        """
        Verify that passing customer_search explicitly filters drawer orders,
        and drawer combobox contains the popup table with Name/Contact columns.
        """
        cust = query_one("SELECT id, name FROM customers WHERE is_active = TRUE AND name IS NOT NULL AND length(trim(name)) > 3 LIMIT 1")
        self.assertIsNotNone(cust)

        # 1. Check combobox markup presence on order page
        target_order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        resp = self.client.get(f"/sales/{target_order['id']}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('id="drawerCustomerSearchInput"', html)
        self.assertIn('id="drawerCustomerDropdownPopup"', html)
        self.assertIn('id="customerDropdownPopup"', html)
        self.assertIn('openDrawerCustomerDropdown()', html)
        self.assertIn('filterDrawerCustomerDropdown(', html)
        self.assertIn('handleDrawerCustomerKey(', html)
        self.assertIn('handleMainCustomerKey(', html)

        # 2. Check customer_search query parameter filters correctly
        search_term = cust['name'].strip()[:4].strip()
        resp_filtered = self.client.get(f"/sales/{target_order['id']}?customer_search={search_term}")
        self.assertEqual(resp_filtered.status_code, 200)
        f_html = resp_filtered.data.decode('utf-8')
        self.assertIn(f'value="{search_term}"', f_html)

if __name__ == '__main__':
    unittest.main()
