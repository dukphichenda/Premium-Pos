import unittest
import json
from app import create_app
from database import query_one, execute, execute_returning_id

class TestSalesOrderAddress(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_quick_add_customer_returns_address(self):
        """Verify quick_add_customer_ajax returns 'address', 'shipping_address', and 'display_address'"""
        test_name = "Test Cust Addr " + str(unittest.TestCase().id())
        resp = self.client.post('/api/customers/quick-add', data={
            'name': test_name,
            'contact_name': 'Test Contact',
            'phone': '012999888',
            'address': 'Street 101, Phnom Penh',
            'city': 'Phnom Penh'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        cust = data.get('customer')
        self.assertEqual(cust.get('address'), 'Street 101, Phnom Penh')
        self.assertEqual(cust.get('address1'), 'Street 101, Phnom Penh')
        self.assertEqual(cust.get('shipping_address'), 'Street 101, Phnom Penh')
        self.assertEqual(cust.get('display_address'), 'Street 101, Phnom Penh')

        # Clean up
        if cust.get('id'):
            execute("DELETE FROM customers WHERE id = %s", (cust['id'],))

    def test_save_order_preserves_and_falls_back_to_customer_address(self):
        """Verify save_order auto-populates customer_address from customer if omitted or empty"""
        # Create a test customer with address
        cid = execute_returning_id("""
            INSERT INTO customers (name, contact_name, phone, address1, shipping_address, is_active)
            VALUES ('Test Address SO Customer', 'Sokha', '099112233', 'Boeung Keng Kang 1', 'Boeung Keng Kang 1', TRUE)
            RETURNING id;
        """)

        try:
            # 1. Create order with empty address in submission
            resp = self.client.post('/sales/new/save', data={
                'order_number': '',
                'customer_id': str(cid),
                'address': '',
                'contact': '',
                'phone': '',
                'lines_json': json.dumps([])
            }, follow_redirects=False)

            # Order should be created and address should be populated from customer
            saved_order = query_one("""
                SELECT id, order_number, customer_address, customer_contact, customer_phone 
                FROM sales_orders 
                WHERE customer_id = %s 
                ORDER BY id DESC LIMIT 1;
            """, (cid,))
            self.assertIsNotNone(saved_order)
            self.assertEqual(saved_order['customer_address'], 'Boeung Keng Kang 1')
            self.assertEqual(saved_order['customer_contact'], 'Sokha')
            self.assertEqual(saved_order['customer_phone'], '099112233')

            # 2. Update existing order with blank address submitted
            so_id = saved_order['id']
            resp2 = self.client.post(f'/sales/{so_id}/save', data={
                'customer_id': str(cid),
                'address': '',
                'contact': '',
                'phone': '',
                'lines_json': json.dumps([])
            }, follow_redirects=False)

            # Address should remain preserved!
            updated_order = query_one("SELECT customer_address, customer_contact, customer_phone FROM sales_orders WHERE id = %s", (so_id,))
            self.assertEqual(updated_order['customer_address'], 'Boeung Keng Kang 1')
            self.assertEqual(updated_order['customer_contact'], 'Sokha')
            self.assertEqual(updated_order['customer_phone'], '099112233')

        finally:
            execute("DELETE FROM sales_orders WHERE customer_id = %s", (cid,))
            execute("DELETE FROM customers WHERE id = %s", (cid,))

if __name__ == '__main__':
    unittest.main()
