import unittest
from app import create_app
from database import query_one, query_all, execute

class TestDeliveryLabelDescAndJpg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_update_and_get_shipping(self):
        # Fetch an existing order
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales orders in database")

        order_id = order['id']
        payload = {
            'carrier': 'Capitol',
            'package_count': 3,
            'cod_amount': 150.50,
            'delivery_notes': 'Taxi near market',
            'customer_address': 'Phnom Penh St 271'
        }
        res = self.client.post(f'/sales/{order_id}/update-shipping', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('carrier'), 'Capitol')
        self.assertEqual(data.get('package_count'), 3)
        self.assertEqual(data.get('cod_amount'), 150.50)

        # Verify via GET endpoint
        get_res = self.client.get(f'/sales/{order_id}/shipping')
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()
        self.assertTrue(get_data.get('success'))
        self.assertEqual(get_data.get('carrier'), 'Capitol')
        self.assertEqual(get_data.get('package_count'), 3)
        self.assertEqual(get_data.get('cod_amount'), 150.50)
        self.assertEqual(get_data.get('delivery_notes'), 'Taxi near market')

    def test_print_routes_support_autojpg(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales orders in database")

        # Check invoice print with autojpg=1
        res = self.client.get(f'/sales/{order["id"]}/print?type=invoice&autojpg=1')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'exportInvoiceToJpg', res.data)
        self.assertIn(b'Export JPG', res.data)

        # Check label print with autojpg=1
        res_label = self.client.get(f'/sales/{order["id"]}/print?type=label&autojpg=1')
        self.assertEqual(res_label.status_code, 200)
        self.assertIn(b'exportToJpg', res_label.data)
        self.assertIn(b'Export JPG', res_label.data)

    def test_invoice_left_sidebar_and_telegram_share(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales orders in database")

        order_id = order['id']
        res = self.client.get(f'/sales/{order_id}/print?type=invoice&autoshare=telegram')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'invoiceStudioSidebar', res.data)
        self.assertIn(b'invoice-studio-layout', res.data)
        self.assertIn(b'shareTelegramBtn', res.data)
        self.assertIn(b'shareInvoiceToTelegram', res.data)
        self.assertIn(b'generateA5InvoiceCanvas', res.data)

        # Test upload-share-image endpoint
        # 1x1 transparent GIF base64
        sample_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        post_res = self.client.post(f'/sales/{order_id}/upload-share-image', json={
            'image_data': sample_b64
        })
        self.assertEqual(post_res.status_code, 200)
        post_data = post_res.get_json()
        self.assertTrue(post_data.get('success'))
        self.assertIn('image_url', post_data)
        self.assertIn('telegram_url', post_data)
        self.assertIn('t.me/share/url', post_data['telegram_url'])

if __name__ == '__main__':
    unittest.main()
