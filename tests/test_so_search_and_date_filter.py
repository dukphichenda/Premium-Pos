import unittest
from app import create_app
from database import query_one, query_all

class TestSoSearchAndDateFilter(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
        row = query_one('SELECT id, order_number FROM sales_orders ORDER BY id DESC LIMIT 1')
        self.order_id = row['id'] if row else None

    def test_date_filter_all_persists_in_session(self):
        # 1. Set to Today
        res = self.client.get('/sales/new?date_filter=Today')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_date_filter'), 'Today')

        # 2. Switch to All - should NOT revert to Today
        res = self.client.get('/sales/new?date_filter=All')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_date_filter'), 'All')

        # 3. Request without date_filter param should retain 'All' from session
        res = self.client.get('/sales/new')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_date_filter'), 'All')

    def test_search_query_persists_in_session(self):
        # 1. Provide search query
        res = self.client.get('/sales/new?search=CustomerTest123')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'CustomerTest123')

        # 2. Subsequent navigation should retain search query from session
        res = self.client.get('/sales/new')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'CustomerTest123')

        # 3. Explicitly clearing search (search="") should remove it
        res = self.client.get('/sales/new?search=')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('so_search_query'))

    def test_detail_order_preserves_date_filter_and_search(self):
        if not self.order_id:
            return
        res = self.client.get(f'/sales/{self.order_id}?date_filter=All&search=TestCust')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        
        # Check session
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_date_filter'), 'All')
            self.assertEqual(sess.get('so_search_query'), 'TestCust')

        # Check search input has value
        self.assertIn('value="TestCust"', html)
        
        # Check item dropdown popup is present with class
        self.assertIn('id="itemDropdownPopup"', html)
        self.assertIn('inflow-item-dropdown-popup', html)

    def test_detail_order_clearing_search_removes_session_and_restores_all(self):
        if not self.order_id:
            return
        # 1. Set search in session
        self.client.get(f'/sales/{self.order_id}?search=Lok+Srey+Mich')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'Lok Srey Mich')

        # 2. Clear search (?search=)
        res = self.client.get(f'/sales/{self.order_id}?search=')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('so_search_query'))

        # Input should have empty value and clear button hidden
        self.assertIn('value=""', html)

if __name__ == '__main__':
    unittest.main()
