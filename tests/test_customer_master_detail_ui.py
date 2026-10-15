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

        # Verify ALL active customers are listed in the sidebar (not truncated to 50)
        import re
        cards = re.findall(r'id=.custCard_\d+.', html)
        total_in_db = query_one("SELECT count(*) as cnt FROM customers WHERE is_active = TRUE")['cnt']
        self.assertEqual(len(cards), total_in_db)
        self.assertGreater(len(cards), 50)

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

    def test_05_search_customers_json_api(self):
        """Test GET /customers?format=json&ajax=1&search=... searches across all customers"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        # Search using test customer name
        search_term = self.test_cust_name[:4]
        resp = self.client.get(f'/customers?format=json&ajax=1&search={search_term}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('customers', data)
        self.assertGreaterEqual(len(data['customers']), 1)
        found_ids = [c['id'] for c in data['customers']]
        self.assertIn(self.test_cust_id, found_ids)

    def test_06_customer_contact_fields_and_persistence(self):
        """Test that customer details include phone, contact_name, remarks, and saving persists them"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        # 1. Update contact person, phone, and remarks
        update_payload = {
            'name': self.test_cust_name,
            'contact_name': 'Sokha Chan (Director)',
            'phone': '+855 12 999 888',
            'email': 'sokha.chan@example.com',
            'remarks': 'VIP Customer - Priority Delivery',
            'tax_number': 'TAX-KH-2026-99',
            'address1': 'Building 12, Street 271, Phnom Penh',
            'city': 'Phnom Penh',
            'country': 'Cambodia'
        }
        save_resp = self.client.post(f'/customers/{self.test_cust_id}/save',
                                     json=update_payload,
                                     headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(save_resp.status_code, 200)
        save_data = save_resp.get_json()
        self.assertTrue(save_data.get('success'))
        self.assertEqual(save_data['customer']['contact_name'], 'Sokha Chan (Director)')
        self.assertEqual(save_data['customer']['phone'], '+855 12 999 888')

        # 2. Fetch details via /api/customers/<id>/details and verify all fields are returned
        detail_resp = self.client.get(f'/api/customers/{self.test_cust_id}/details')
        self.assertEqual(detail_resp.status_code, 200)
        detail_data = detail_resp.get_json()
        self.assertTrue(detail_data.get('success'))
        cust = detail_data['customer']
        self.assertEqual(cust['contact_name'], 'Sokha Chan (Director)')
        self.assertEqual(cust['phone'], '+855 12 999 888')
        self.assertEqual(cust['remarks'], 'VIP Customer - Priority Delivery')
        self.assertEqual(cust['tax_number'], 'TAX-KH-2026-99')
        self.assertEqual(cust['address1'], 'Building 12, Street 271, Phnom Penh')

if __name__ == '__main__':
    unittest.main()
