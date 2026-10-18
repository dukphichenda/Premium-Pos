import unittest
import json
import io
from app import create_app
from database import query_one
from services.ai_customer_extractor import parse_customer_text, extract_customer_info, get_configured_gemini_api_key, save_gemini_api_key

class TestAiCustomerExtractor(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_parse_customer_text_khmer(self):
        khmer_sample = """
        ឈ្មោះ: ហាង លីហួរ ម៉ាត
        អ្នកទទួល: លីហួរ
        ទូរស័ព្ទ: 012 888 999 / 098 777 666
        ទីតាំង: ផ្ទះលេខ 45, ផ្លូវ 2004, សង្កាត់កាកាប, ខណ្ឌពោធិ៍សែនជ័យ, រាជធានីភ្នំពេញ
        """
        parsed = parse_customer_text(khmer_sample)
        self.assertIn("លីហួរ", parsed['name'])
        self.assertEqual(parsed['contact_name'], "លីហួរ")
        self.assertIn("012 888 999", parsed['phone'])
        self.assertIn("2004", parsed['address'])
        self.assertIn("ភ្នំពេញ", parsed['address'])

    def test_parse_customer_text_english(self):
        card_sample = """
        SOMA TRADING CO., LTD.
        Contact Person: Mr. Sokha Chea
        Tel: +855 12 345 678
        Address: #12, Street 310, Boeung Keng Kang 1, Phnom Penh
        """
        parsed = parse_customer_text(card_sample)
        self.assertIn("SOMA TRADING", parsed['name'])
        self.assertIn("Sokha Chea", parsed['contact_name'])
        self.assertEqual(parsed['phone'], "012 345 678")
        self.assertIn("Street 310", parsed['address'])

    def test_ai_extract_endpoint_with_text(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        payload = {
            'text': "ឈ្មោះ: ហាង កាហ្វេម៉ាត\nលេខទូរស័ព្ទ: 010 222 333\nអាសយដ្ឋាន: ផ្លូវ 271 ភ្នំពេញ"
        }
        res = self.client.post('/api/customers/ai-extract', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        ext = data.get('extracted', {})
        self.assertIn("កាហ្វេម៉ាត", ext.get('name'))
        self.assertEqual(ext.get('phone'), "010 222 333")
        self.assertIn("271", ext.get('address'))

    def test_ai_extract_endpoint_with_image_file(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        # Send a 1x1 GIF / JPEG image
        dummy_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        res = self.client.post('/api/customers/ai-extract', data={
            'image': (io.BytesIO(dummy_gif), 'test_bizcard.gif'),
            'text': "Name: Dara\nPhone: 098 765 432\nAddress: Toul Kork, Phnom Penh"
        }, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('extracted', {}).get('phone'), "098 765 432")

    def test_ai_key_status_and_save(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        # Test status endpoint
        res = self.client.get('/api/customers/ai-key-status')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('has_key', data)

        # Test save endpoint
        save_res = self.client.post('/api/customers/save-ai-key', json={'api_key': 'AIzaSy_TEST_KEY_12345678'})
        self.assertEqual(save_res.status_code, 200)
        self.assertTrue(save_res.get_json().get('success'))
        self.assertTrue(save_res.get_json().get('has_key'))

        # Verify status now reflects key
        res2 = self.client.get('/api/customers/ai-key-status')
        self.assertTrue(res2.get_json().get('has_key'))

    def test_modal_quick_add_customer_has_ai_upload_ui(self):
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            self.skipTest("No sales order")
        order_id = order['id']

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        res = self.client.get(f'/sales/{order_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'quickAddAiUploadCard', res.data)
        self.assertIn(b'quickAddCustImageInput', res.data)
        self.assertIn(b'btnQuickAddAiUpload', res.data)
        self.assertIn(b'modalAiKeyConfig', res.data)
        self.assertIn(b'handleQuickAddCustomerImageUpload', res.data)
        self.assertIn(b'processQuickAddCustomerImage', res.data)
        self.assertIn(b'ai-field-pulsing', res.data)

if __name__ == '__main__':
    unittest.main()
