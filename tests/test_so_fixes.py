import unittest
from app import create_app
from database import query_one, query_all

class TestSoFixes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'main_admin'

    def test_sidebar_customer_matches_and_all_customers_in_page(self):
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check customer matches container in sidebar
        self.assertIn('id="soSidebarCustomerMatches"', html)

        # Check window.allCustomersList is defined and has customers
        self.assertIn('window.allCustomersList = [', html)
        self.assertIn('startNewOrderForCustomer', html)
        self.assertIn('previewImageModal', html)

    def test_order_with_many_items_rendering(self):
        # Find order 34386 or an order with multiple lines
        ord_row = query_one("SELECT id, order_number FROM sales_orders WHERE order_number = 'SO-00034386'") or query_one("SELECT sales_order_id as id FROM sales_order_lines GROUP BY sales_order_id HAVING count(*) > 10 LIMIT 1")
        if ord_row:
            resp = self.client.get(f'/sales/{ord_row["id"]}')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')
            # Check items table exists
            self.assertTrue('lineItemsTable' in html or 'inflow-grid-container' in html)
            self.assertIn('line-pic-cell', html)

    def test_date_filter_options_and_custom_range(self):
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check date filter options matching Screenshot 1
        self.assertIn("applySoDateFilter('Today')", html)
        self.assertIn("applySoDateFilter('This Week')", html)
        self.assertIn("applySoDateFilter('This Month')", html)
        self.assertIn("applySoDateFilter('Last 90 Days')", html)
        self.assertIn("applySoDateFilter('Last 365 Days')", html)
        self.assertIn("applySoDateFilter('Tomorrow')", html)
        self.assertIn("applySoDateFilter('Next Month')", html)
        self.assertIn('id="soDateFrom"', html)
        self.assertIn('id="soDateTo"', html)
        self.assertIn('applyCustomDateFilter()', html)

    def test_product_search_shows_photo(self):
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check itemDropdownPopup has Photo column and image thumbnails
        self.assertIn('id="itemDropdownPopup"', html)
        self.assertIn('<th style="width: 38px; text-align: center;">Photo</th>', html)

if __name__ == '__main__':
    unittest.main()

