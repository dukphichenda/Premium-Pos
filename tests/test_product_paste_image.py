import unittest
import io
import json
import base64
from app import create_app
from database import query_one

class TestProductPasteImage(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
        prod = query_one("SELECT id, name FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        self.product_id = prod['id'] if prod else 1

    def test_upload_pasted_blob(self):
        """Simulate pasting an image from clipboard as a multipart blob"""
        # 1x1 transparent PNG bytes
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        data = {
            'picture': (io.BytesIO(png_bytes), 'blob', 'image/png')
        }
        res = self.client.post(f'/products/{self.product_id}/upload_picture', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get('success'))
        self.assertTrue(json_data.get('image_url', '').startswith('/static/uploads/products/'))

    def test_upload_base64_json(self):
        """Simulate uploading a pasted image data URL in JSON"""
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        b64_str = "data:image/png;base64," + base64.b64encode(png_bytes).decode('utf-8')
        payload = {'picture': b64_str}
        res = self.client.post(f'/products/{self.product_id}/upload_picture', json=payload)
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get('success'))
        self.assertTrue(json_data.get('image_url', '').startswith('/static/uploads/products/'))

if __name__ == '__main__':
    unittest.main()
