import unittest
from app import app
from services.csv_exchange import export_data_to_csv, resolve_customer_phone_and_name, is_pure_phone, extract_phone

class TestCustomerPhoneExport(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pure_phone_detection(self):
        self.assertTrue(is_pure_phone('+855 10 546 979'))
        self.assertTrue(is_pure_phone('012653659'))
        self.assertTrue(is_pure_phone('096 3335483'))
        self.assertTrue(is_pure_phone('010 - 805 - 770/061 - 730 - 759'))
        self.assertFalse(is_pure_phone('Angkor Supermarket'))
        self.assertFalse(is_pure_phone('Paper Box 1600ML'))

    def test_resolve_customer_phone_from_contact(self):
        name, contact, phone = resolve_customer_phone_and_name(
            name='New',
            contact_name='012 708123',
            phone=''
        )
        self.assertEqual(name, 'New')
        self.assertEqual(phone, '012 708123')

    def test_resolve_customer_phone_from_name_and_swap_company(self):
        name, contact, phone = resolve_customer_phone_and_name(
            name='+855 10 546 979',
            contact_name='Sky Media Cambodia Co., Ltd',
            phone=''
        )
        self.assertEqual(name, 'Sky Media Cambodia Co., Ltd')
        self.assertEqual(phone, '+855 10 546 979')

    def test_customer_export_csv(self):
        csv_bytes, filename = export_data_to_csv('customer')
        self.assertEqual(filename, 'inFlow_Customer.csv')
        lines = csv_bytes.decode('utf-8-sig').splitlines()
        self.assertGreater(len(lines), 1)
        headers = lines[0].split(',')
        self.assertIn('Phone', headers)
        phone_idx = headers.index('Phone')
        # Check that top lines where name is numeric have phone populated
        for line in lines[1:15]:
            cols = [c.strip() for c in line.split(',')]
            if len(cols) > phone_idx:
                c_name = cols[0]
                if any(c_name.startswith(p) for p in ('0', '+855', '855')):
                    self.assertTrue(len(cols[phone_idx]) > 0, f"Phone should not be empty for {c_name}")

    def test_sales_order_export_csv_has_phone(self):
        csv_bytes, filename = export_data_to_csv('sales_order')
        self.assertEqual(filename, 'inFlow_SalesOrder.csv')
        lines = csv_bytes.decode('utf-8-sig').splitlines()
        self.assertGreater(len(lines), 1)
        headers = [h.strip() for h in lines[0].split(',')]
        self.assertIn('Customer Phone', headers)
        phone_idx = headers.index('Customer Phone')
        self.assertEqual(phone_idx, 3)  # right after Customer Name

    def test_customer_orders_export_route(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
        resp = self.client.get('/customers/100/export-orders')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.headers.get('Content-Type'))
        lines = resp.data.decode('utf-8-sig').splitlines()
        headers = [h.strip() for h in lines[0].split(',')]
        self.assertIn('Customer Phone', headers)

if __name__ == '__main__':
    unittest.main()
