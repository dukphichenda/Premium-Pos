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

    def test_csv_import_sales_order_address_and_customer_sync(self):
        """Verify sales order CSV import extracts address, sets destination_province, and updates customer"""
        from services.csv_exchange import preview_import_data, execute_import_data

        test_order_num = "TEST-SO-CSV-ADDR-01"
        test_cust_name = "CSV Import Test Customer"

        # Multi-row CSV: row 1 has item 1 without address, row 2 has item 2 WITH address (testing multi-row backfill)
        csv_text = (
            "OrderNumber,Customer,ShippingAddress1,ShippingCity,ShippingState,ItemName,ItemQuantity,ItemUnitPrice\n"
            f"{test_order_num},{test_cust_name},,,,\"Widget A\",2,15.00\n"
            f"{test_order_num},{test_cust_name},\"Street 2004\",\"Phnom Penh\",\"Phnom Penh\",\"Widget B\",1,25.00\n"
        )

        try:
            # 1. Test Preview
            preview_res = preview_import_data('sales_order', csv_text, has_headers=True)
            self.assertIn('orders_summary', preview_res)
            self.assertEqual(len(preview_res['orders_summary']), 1)
            so_summary = preview_res['orders_summary'][0]
            self.assertEqual(so_summary['order_number'], test_order_num)
            self.assertEqual(so_summary['address'], 'Street 2004, Phnom Penh')

            # 2. Test Execution
            import_res = execute_import_data('sales_order', csv_text, has_headers=True)
            self.assertTrue(import_res.get('success', False) or import_res.get('imported', 0) > 0)

            # Check database for sales order
            saved_so = query_one("""
                SELECT id, order_number, customer_address, destination_province, customer_id
                FROM sales_orders
                WHERE order_number = %s;
            """, (test_order_num,))
            self.assertIsNotNone(saved_so)
            self.assertEqual(saved_so['customer_address'], 'Street 2004, Phnom Penh')
            self.assertEqual(saved_so['destination_province'], 'Phnom Penh')

            # Check customer table
            saved_cust = query_one("""
                SELECT id, name, address1, shipping_address
                FROM customers
                WHERE id = %s;
            """, (saved_so['customer_id'],))
            self.assertIsNotNone(saved_cust)
            self.assertEqual(saved_cust['address1'], 'Street 2004, Phnom Penh')
            self.assertEqual(saved_cust['shipping_address'], 'Street 2004, Phnom Penh')

        finally:
            execute("DELETE FROM sales_order_lines WHERE sales_order_id IN (SELECT id FROM sales_orders WHERE order_number = %s)", (test_order_num,))
            execute("DELETE FROM sales_orders WHERE order_number = %s", (test_order_num,))
            execute("DELETE FROM customers WHERE name = %s", (test_cust_name,))

if __name__ == '__main__':
    unittest.main()

