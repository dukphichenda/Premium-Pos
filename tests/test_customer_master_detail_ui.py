import unittest
from app import create_app
from database import query_one, query_all, execute

class TestCustomerMasterDetailUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

        # Find or create a test customer
        cust = query_one("SELECT id, name FROM customers WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        if cust:
            cls.test_cust_id = cust['id']
            cls.test_cust_name = cust['name']
        else:
            cls.test_cust_id = 1
            cls.test_cust_name = "Test Customer"

    def test_01_customer_master_detail_page_loads(self):
        """Test GET /customers renders 200 with modern split master-detail UI"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        resp = self.client.get('/customers')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        # Verify master sidebar elements matching screenshot
        self.assertIn('cust-master-sidebar', html)
        self.assertIn('btnToggleSearch', html)
        self.assertIn('custLiveSearchInput', html)
        self.assertIn('btnStatusFilter', html)
        self.assertIn('cust-list-card', html)
        self.assertIn('cust-balance-pill', html)

        # Verify detail canvas elements matching screenshot
        self.assertIn('cust-detail-canvas', html)
        self.assertIn('detailCustomerName', html)
        self.assertIn('detailBalanceLargeBadge', html)
        self.assertIn('cust-mid-progress-bar', html)
        self.assertIn('custOrdersTable', html)
        self.assertIn('bottomSummaryBalance', html)
        self.assertIn('btnSaveCustomer', html)

    def test_02_customer_details_json_api(self):
        """Test GET /api/customers/<id>/details returns JSON with customer and orders"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        resp = self.client.get(f'/api/customers/{self.test_cust_id}/details')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('customer', data)
        self.assertIn('orders', data)
        self.assertIn('stats', data)
        self.assertEqual(data['customer']['id'], self.test_cust_id)

    def test_03_customer_save_ajax(self):
        """Test POST /customers/<id>/save via AJAX updates customer and returns JSON"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        payload = {
            'name': self.test_cust_name,
            'payment_terms': 'Net 30',
            'discount_percent': 5.0,
            'remarks': 'Master-detail test note'
        }
        resp = self.client.post(f'/customers/{self.test_cust_id}/save',
                                json=payload,
                                headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('saved successfully', data.get('message', '').lower())

    def test_04_direct_customer_url_split_view(self):
        """Test GET /customers/<id> opens split view with selected customer"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        resp = self.client.get(f'/customers/{self.test_cust_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('cust-master-sidebar', html)
        self.assertIn('cust-detail-canvas', html)
        self.assertIn(f'custCard_{self.test_cust_id}', html)

if __name__ == '__main__':
    unittest.main()
