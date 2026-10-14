import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestSoDeleteCompleteMoveUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

    def test_complete_so_moves_up_to_upper_order(self):
        """When completing an SO, it stays on the detail page and moves up to the upper order."""
        from routes.sales_orders import _get_drawer_and_metadata
        with self.app.test_request_context():
            from flask import session
            session['role'] = 'main_admin'
            drawer = _get_drawer_and_metadata(status_filter='All', branch_id='main')
            sidebar_orders = drawer['sidebar_orders']

        if len(sidebar_orders) < 2:
            cust = query_one("SELECT id FROM customers LIMIT 1")
            cust_id = cust['id'] if cust else 1
            o1_id = execute_returning_id("INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-SO-A', %s, 50, 'OPEN', 'UNPAID', CURRENT_DATE) RETURNING id", (cust_id,))
            o2_id = execute_returning_id("INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-SO-B', %s, 60, 'OPEN', 'UNPAID', CURRENT_DATE) RETURNING id", (cust_id,))
            upper_order_id = o2_id
            current_order_id = o1_id
        else:
            upper_order_id = sidebar_orders[0]['id']
            current_order_id = sidebar_orders[1]['id']

        # Complete current_order_id
        resp = self.client.post(
            f'/sales/{current_order_id}/complete_pay',
            data={
                'payment_method': 'Cash',
                'date_filter': 'All',
                'status_filter': 'All',
                'customer_search': '',
                'branch': 'main'
            },
            follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        # Verify it redirects to the upper order!
        self.assertIn(f'/sales/{upper_order_id}', resp.headers['Location'])

    def test_complete_so_with_dom_upper_order_id(self):
        """When frontend passes upper_order_id, complete_pay redirects directly to that upper order."""
        orders = query_all("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 3")
        if len(orders) < 2:
            self.skipTest("Not enough sales orders to test")
        target_upper = orders[0]['id']
        current = orders[1]['id']

        resp = self.client.post(
            f'/sales/{current}/complete_pay',
            data={
                'payment_method': 'Cash',
                'upper_order_id': str(target_upper),
                'branch': 'main'
            },
            follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/sales/{target_upper}', resp.headers['Location'])

    def test_delete_so_moves_up_to_upper_order(self):
        """When deleting an SO, it stays on the detail page and moves up to the upper order instead of going to list."""
        cust = query_one("SELECT id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1

        # Create two test orders
        o_upper = execute_returning_id("INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-DEL-UPPER', %s, 10, 'OPEN', 'UNPAID', CURRENT_DATE) RETURNING id", (cust_id,))
        o_target = execute_returning_id("INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-DEL-TARGET', %s, 20, 'OPEN', 'UNPAID', CURRENT_DATE) RETURNING id", (cust_id,))

        # In DESC order: o_target is newer, o_upper is older; but let's test deleting o_upper with target_id or deleting when order above exists
        # If we delete o_upper, in DESC order o_target is above o_upper!
        resp = self.client.post(
            f'/sales/{o_upper}/delete',
            data={
                'date_filter': 'All',
                'status_filter': 'All',
                'customer_search': '',
                'branch': 'main'
            },
            follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        # Should redirect to detail_order (not list_orders!)
        self.assertIn('/sales/', resp.headers['Location'])
        self.assertNotIn('/sales?view=table', resp.headers['Location'])
        # Verify o_upper is deleted
        deleted_check = query_one("SELECT id FROM sales_orders WHERE id = %s", (o_upper,))
        self.assertIsNone(deleted_check)

        # Clean up o_target if still exists
        execute("DELETE FROM sales_orders WHERE id = %s", (o_target,))

if __name__ == '__main__':
    unittest.main()
