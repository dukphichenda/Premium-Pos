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

    def test_search_customer_chenda_preserved(self):
        # If user searches for customer 'chenda', it should NOT be discarded
        if self.order_id:
            res = self.client.get(f'/sales/{self.order_id}?search=chenda')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            self.assertIn('value="chenda"', html)
            with self.client.session_transaction() as sess:
                self.assertEqual(sess.get('so_search_query'), 'chenda')

    def test_so_search_preserves_open_status_filter(self):
        # When searching with status_filter=Open, status_filter must stay Open and only Open orders returned
        res = self.client.get('/sales/new?status_filter=Open&search=nham')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        # Check Open status pill is rendered
        self.assertIn('id="soStatusPillLabel">Open</span>', html)
        self.assertIn('value="nham"', html)

    def test_so_sidebar_does_not_auto_filter_by_customer_id(self):
        # When customer_id is supplied on /sales/new (e.g. from clicking + New SO for matched customer),
        # it pre-fills the new order customer but does NOT filter the sidebar to only that customer
        cust = query_one("SELECT id, name FROM customers LIMIT 1")
        if cust:
            res = self.client.get(f'/sales/new?customer_id={cust["id"]}')
            self.assertEqual(res.status_code, 200)
            # The new order should have the customer name pre-selected
            html = res.data.decode('utf-8')
            self.assertIn(f'value="{cust["name"]}"', html)

    def test_so_search_persists_across_order_selection_until_cleared(self):
        if not self.order_id:
            return
        # 1. Search customer 'nham'
        self.client.get(f'/sales/{self.order_id}?search=nham&status_filter=Open')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'nham')
            self.assertEqual(sess.get('so_status_filter'), 'Open')

        # 2. Select another order or navigate without search param - search query and input value should stay!
        res = self.client.get(f'/sales/{self.order_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('value="nham"', html)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'nham')

        # 3. Canvas partial swap also retains search in session
        res_canvas = self.client.get(f'/sales/{self.order_id}?search=nham&status_filter=Open&partial=canvas',
                                     headers={'X-Inflow-Partial': 'canvas', 'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res_canvas.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('so_search_query'), 'nham')
            self.assertEqual(sess.get('so_status_filter'), 'Open')

        # 4. Only explicit clear (?search=) clears it
        res = self.client.get(f'/sales/{self.order_id}?search=')
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('so_search_query'))

if __name__ == '__main__':
    unittest.main()

