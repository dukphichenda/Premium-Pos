import io
import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from database import query_one, execute, execute_returning_id

class TestAttachmentPasteAndUpload(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_po_detail_template_contains_paste_support(self):
        """Verify purchases/detail.html contains direct paste elements and keyboard paste handler"""
        # Create a test PO
        vendor_id = execute_returning_id("INSERT INTO vendors (name) VALUES ('Test Paste Vendor') RETURNING id")
        po_id = execute_returning_id("INSERT INTO purchase_orders (order_number, vendor_id, status) VALUES ('PO-TEST-PASTE', %s, 'OPEN') RETURNING id", (vendor_id,))

        try:
            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            response = self.client.get(f'/purchases/{po_id}')
            self.assertEqual(response.status_code, 200)
            html = response.data.decode('utf-8')

            # Verify dropzone has paste attributes and button
            self.assertIn('id="poDropzone"', html)
            self.assertIn('tabindex="0"', html)
            self.assertIn('po-paste-btn', html)
            self.assertIn('pastePoImageFromClipboard()', html)
            self.assertIn('Direct paste with Ctrl+V supported', html)

            # Verify JS clipboard handling functions
            self.assertIn('extractImagesFromClipboard', html)
            self.assertIn("window.addEventListener('paste'", html)
            self.assertIn('pastePoImageFromClipboard', html)
        finally:
            execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
            execute("DELETE FROM vendors WHERE id = %s", (vendor_id,))

    def test_so_detail_template_contains_paste_support(self):
        """Verify sales/detail.html contains direct paste elements and keyboard paste handler"""
        cust_id = execute_returning_id("INSERT INTO customers (name) VALUES ('Test Paste Cust') RETURNING id")
        so_id = execute_returning_id("INSERT INTO sales_orders (order_number, customer_id, status) VALUES ('SO-TEST-PASTE', %s, 'OPEN') RETURNING id", (cust_id,))

        try:
            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            response = self.client.get(f'/sales/{so_id}')
            self.assertEqual(response.status_code, 200)
            html = response.data.decode('utf-8')

            self.assertIn('id="orderAttachmentModal"', html)
            self.assertIn('pasteSoImageFromClipboard()', html)
            self.assertIn('paste image with Ctrl+V', html)
            self.assertIn("window.addEventListener('paste'", html)
        finally:
            execute("DELETE FROM sales_orders WHERE id = %s", (so_id,))
            execute("DELETE FROM customers WHERE id = %s", (cust_id,))

    def test_po_upload_attachment_accepts_pasted_image(self):
        """Verify /purchases/<id>/attachments/upload properly saves a pasted image file"""
        vendor_id = execute_returning_id("INSERT INTO vendors (name) VALUES ('Test Paste Vendor 2') RETURNING id")
        po_id = execute_returning_id("INSERT INTO purchase_orders (order_number, vendor_id, status) VALUES ('PO-TEST-UPLOAD', %s, 'OPEN') RETURNING id", (vendor_id,))

        try:
            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'

            # 1x1 transparent PNG byte content
            tiny_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
            data = {
                'file': (io.BytesIO(tiny_png), 'photo_2026-10-22_14-03-10.png')
            }

            resp = self.client.post(f'/purchases/{po_id}/attachments/upload', data=data, content_type='multipart/form-data')
            self.assertEqual(resp.status_code, 200)
            res_json = resp.get_json()
            self.assertTrue(res_json.get('success'))

            # Check DB record
            att_row = query_one("SELECT * FROM purchase_order_attachments WHERE purchase_order_id = %s", (po_id,))
            self.assertIsNotNone(att_row)
            self.assertEqual(att_row['file_name'], 'photo_2026-10-22_14-03-10.png')
            self.assertTrue(att_row['file_path'].startswith('/static/uploads/purchase_attachments/'))
        finally:
            execute("DELETE FROM purchase_order_attachments WHERE purchase_order_id = %s", (po_id,))
            execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
            execute("DELETE FROM vendors WHERE id = %s", (vendor_id,))

if __name__ == '__main__':
    unittest.main()
