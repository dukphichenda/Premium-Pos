import unittest
from app import create_app
from database import query_one
from routes.sales_orders import generate_order_share_token, verify_order_share_token

class TestTelegramShareDirectPrint(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_token_generation_and_verification(self):
        token = generate_order_share_token(99999)
        self.assertTrue(token)
        self.assertTrue(verify_order_share_token(99999, token))
        self.assertFalse(verify_order_share_token(99999, 'wrongtoken123456'))
        self.assertFalse(verify_order_share_token(88888, token))

    def test_telegram_share_data_endpoint(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order in database")
        order_id = order['id']

        res = self.client.get(f'/sales/{order_id}/telegram-share-data')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('preview_url', data)
        self.assertIn('telegram_url', data)
        self.assertIn('caption', data)
        self.assertIn('token=', data['preview_url'])
        self.assertIn(data['preview_url'], data['caption'])

    def test_shared_print_preview_has_no_settings_in_sidebar(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order in database")
        order_id = order['id']
        token = generate_order_share_token(order_id)

        # Access with valid share token (shared view)
        res = self.client.get(f'/sales/{order_id}/print?type=invoice&token={token}')
        self.assertEqual(res.status_code, 200)
        
        # Verify it is the authentic print preview layout
        self.assertIn(b'invoiceStudioSidebar', res.data)
        self.assertIn(b'invoice-studio-layout', res.data)
        self.assertIn(b'btn-print', res.data)
        self.assertIn(b'btn-pdf', res.data)
        self.assertIn(b'window.print()', res.data)
        self.assertIn(b'invoiceSheet', res.data)

        # Verify NO settings in sidebar and NO modal
        self.assertNotIn(b'id="liveRateInput"', res.data)
        self.assertNotIn(b'id="chkShowKhr"', res.data)
        self.assertNotIn(b'id="chkShowSignature"', res.data)
        self.assertNotIn(b'id="signatureModal"', res.data)
        self.assertNotIn(b'Currency & Exchange Rate', res.data)
        self.assertNotIn(b'tabInvoice', res.data)

    def test_admin_print_preview_has_settings_in_sidebar(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order in database")
        order_id = order['id']

        # Access normally as logged-in user without share token
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

        res = self.client.get(f'/sales/{order_id}/print?type=invoice')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'sidebar-settings-section', res.data)
        self.assertIn(b'liveRateInput', res.data)
        self.assertIn(b'openSignatureModal', res.data)
        self.assertIn(b'Invoice Settings', res.data)

    def test_so_detail_page_has_telegram_split_and_share_support(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order in database")
        order_id = order['id']

        res = self.client.get(f'/sales/{order_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'telegramShareSplitWrapper', res.data)
        self.assertIn(b'soDirectTelegramBtn', res.data)
        self.assertIn(b'directShareOrderTelegram', res.data)

    def test_upload_share_image_returns_preview_url(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order in database")
        order_id = order['id']

        sample_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        res = self.client.post(f'/sales/{order_id}/upload-share-image', json={
            'image_data': sample_b64
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('preview_url', data)
        self.assertIn('token', data)
        self.assertIn('caption', data)

if __name__ == '__main__':
    unittest.main()
