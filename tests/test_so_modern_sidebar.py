import unittest
import re
from app import create_app
from database import query_one, query_all

class TestSoModernSidebar(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_sidebar_structure_and_components(self):
        """
        Verify that the modern sales order sidebar matches the UI requirements:
        1. Search toggle button [ 🔍 ]
        2. Status pill button [ Open (count) ∨ ] and floating dropdown
        3. Add new order button [ + ]
        4. Filters toggle button and collapsible advanced panel
        5. 'Order number' column header
        6. Cards with order #, status badge, price pill, customer name, and delivery person tag
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. Master sidebar container
        self.assertIn('so-master-sidebar', html)
        self.assertIn('id="soMasterSidebar"', html)

        # 2. Toolbar buttons
        self.assertIn('id="btnToggleSoSearch"', html)
        self.assertIn('id="btnSoStatusPill"', html)
        self.assertIn('id="soStatusPillLabel"', html)
        self.assertIn('id="soStatusPillCount"', html)
        self.assertIn('id="soStatusDropdownMenu"', html)
        self.assertIn('title="Create New Sales Order (+)"', html)

        # 3. Filters row & column header
        self.assertIn('toggleSoAdvancedFilters()', html)
        self.assertIn('id="soAdvancedFiltersPanel"', html)
        self.assertIn('id="soDateFilterSelect"', html)
        self.assertIn('id="soDeliveryManFilterSelect"', html)
        self.assertIn('Order number', html)

        # 4. Card elements
        self.assertIn('so-sidebar-card', html)
        self.assertIn('so-card-order-num', html)
        self.assertIn('so-status-pill', html)
        self.assertIn('so-card-price-pill', html)
        self.assertIn('so-card-cust-name', html)
        self.assertTrue('so-card-delivery-tag' in html or 'so-card-delivery-unassigned' in html)

    def test_status_filtering_options(self):
        """Verify status filtering routes and active labels"""
        # Test Unfulfilled
        resp = self.client.get('/sales/new?status_filter=Unfulfilled')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Unfulfilled', html)

        # Test Fulfilled
        resp_ful = self.client.get('/sales/new?status_filter=Fulfilled')
        self.assertEqual(resp_ful.status_code, 200)
        html_ful = resp_ful.data.decode('utf-8')
        self.assertIn('Fulfilled', html_ful)

        # Test Paid
        resp_paid = self.client.get('/sales/new?status_filter=Paid')
        self.assertEqual(resp_paid.status_code, 200)

        # Test All Orders
        resp_all = self.client.get('/sales/new?status_filter=All')
        self.assertEqual(resp_all.status_code, 200)

    def test_delivery_man_filter(self):
        """Verify delivery man filter parameter"""
        # All
        resp = self.client.get('/sales/new?delivery_man=All')
        self.assertEqual(resp.status_code, 200)

        # Unassigned
        resp_un = self.client.get('/sales/new?delivery_man=Unassigned')
        self.assertEqual(resp_un.status_code, 200)

    def test_search_query(self):
        """Verify order search by query parameter"""
        order = query_one("SELECT order_number FROM sales_orders WHERE order_number IS NOT NULL LIMIT 1")
        if order:
            num = order['order_number']
            resp = self.client.get(f'/sales/new?search={num}')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')
            self.assertIn(num, html)

if __name__ == '__main__':
    unittest.main()
