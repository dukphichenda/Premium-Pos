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
        Verify that the modern sales order sidebar matches the updated UI requirements:
        1. Date preset toggle button on top [ 📅 ] and floating date dropdown
        2. Status pill button [ Open (count) ∨ ] and floating dropdown (Open, Paid, All Orders)
        3. Add new order button [ + ]
        4. Wider search bar directly visible
        5. 'Order number' column header
        6. Cards with order #, Open/Paid status badge, price pill, customer name, and delivery person tag
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. Master sidebar container
        self.assertIn('so-master-sidebar', html)
        self.assertIn('id="soMasterSidebar"', html)

        # 2. Toolbar buttons: Date button, Status pill, New order (+)
        self.assertIn('id="btnToggleSoDate"', html)
        self.assertIn('id="soDateDropdownMenu"', html)
        self.assertIn('id="btnSoStatusPill"', html)
        self.assertIn('id="soStatusPillLabel"', html)
        self.assertIn('id="soStatusPillCount"', html)
        self.assertIn('id="soStatusDropdownMenu"', html)
        self.assertIn('title="Create New Sales Order (+)"', html)

        # 3. Wider search bar directly visible
        self.assertIn('id="soSidebarSearchInput"', html)
        self.assertIn('id="btnClearSoSearch"', html)
        self.assertIn('Order number', html)

        # 4. Status badges: Open and Paid (no Unfulfilled, no Fulfilled)
        self.assertIn('badge-open', html)
        self.assertNotIn('Unfulfilled', html)
        self.assertNotIn('Fulfilled', html)

        # 5. Card elements
        self.assertIn('so-sidebar-card', html)
        self.assertIn('so-card-order-num', html)
        self.assertIn('so-status-pill', html)
        self.assertIn('so-card-price-pill', html)
        self.assertIn('so-card-cust-name', html)

    def test_status_filter_open_returns_orders(self):
        """Verify that choosing 'Open' returns all open orders without zero orders bug"""
        resp = self.client.get('/sales/new?status_filter=Open')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        # Verify cards are present and not 0 orders
        self.assertNotIn('0 orders', html)
        self.assertIn('badge-open', html)
        card_count = html.count('class="so-sidebar-card')
        self.assertGreater(card_count, 0, "Choosing Open must return matching open orders")

    def test_status_filter_paid(self):
        """Verify Paid status filtering"""
        resp = self.client.get('/sales/new?status_filter=Paid')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Paid', html)
        self.assertIn('badge-paid', html)

    def test_sales_route_redirects_to_workspace(self):
        """Verify /sales redirects directly to sales order workspace instead of old table page"""
        resp = self.client.get('/sales')
        self.assertEqual(resp.status_code, 302)
        location = resp.headers.get('Location') or ''
        self.assertTrue('/sales/' in location)

    def test_cancelled_above_all_orders_in_dropdown(self):
        """Verify Cancelled is displayed directly above All Orders in the status dropdown"""
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        self.assertIn('selectSoStatusFilter(\'Cancelled\')', html)
        self.assertIn('selectSoStatusFilter(\'All\')', html)
        # Cancelled must appear before All Orders
        cancelled_idx = html.find('selectSoStatusFilter(\'Cancelled\')')
        all_idx = html.find('selectSoStatusFilter(\'All\')')
        self.assertGreater(cancelled_idx, -1)
        self.assertGreater(all_idx, -1)
        self.assertLess(cancelled_idx, all_idx, "Cancelled should be placed directly above All Orders")

    def test_all_status_returns_all_orders(self):
        """Verify status_filter=All returns orders across statuses"""
        resp = self.client.get('/sales/new?status_filter=All')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        card_count = html.count('class="so-sidebar-card')
        self.assertGreater(card_count, 0)

    def test_photo_column_in_sales_order_not_in_invoice_print(self):
        """Verify photo column in sales order grid, but NOT in final invoice to print"""
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if order:
            # Sales order detail view
            resp_detail = self.client.get(f'/sales/{order["id"]}')
            self.assertEqual(resp_detail.status_code, 200)
            html_detail = resp_detail.data.decode('utf-8')
            self.assertIn('>Photo</th>', html_detail)
            self.assertIn('class="line-pic-cell"', html_detail)

            # Invoice print view
            resp_print = self.client.get(f'/sales/{order["id"]}/print?type=invoice')
            self.assertEqual(resp_print.status_code, 200)
            html_print = resp_print.data.decode('utf-8')
            self.assertNotIn('>Photo</th>', html_print)
            self.assertNotIn('line-pic-cell', html_print)

if __name__ == '__main__':
    unittest.main()
