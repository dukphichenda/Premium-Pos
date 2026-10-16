import unittest
import json
from app import create_app
from database import query_one

class TestSoHoverPreview(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_sidebar_has_hover_preview_elements_and_json(self):
        """Verify sales orders workspace has hover preview popover and JSON cache"""
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Popover DOM element
        self.assertIn('id="soOrderItemsHoverPreview"', html)
        self.assertIn('id="soPreviewDataJson"', html)
        self.assertIn('so-items-preview-popover', html)
        self.assertIn('id="soPrevTotalItems"', html)
        self.assertIn('id="soPrevTotalQty"', html)
        self.assertIn('id="soPrevTotalAmount"', html)
        self.assertIn('id="soPrevItemsTbody"', html)
        self.assertIn('so-card-items-pill', html)
        self.assertIn('data-total-items=', html)
        self.assertIn('initSoOrderHoverPreview', html)

    def test_api_order_preview_items_endpoint(self):
        """Verify /sales/api/preview_items/<id> returns valid preview JSON with items sold"""
        order = query_one("""
            SELECT so.id, so.order_number 
            FROM sales_orders so 
            JOIN sales_order_lines sol ON so.id = sol.sales_order_id 
            LIMIT 1
        """)
        self.assertIsNotNone(order, "Should find at least one order with lines")
        oid = order['id']

        resp = self.client.get(f'/sales/api/preview_items/{oid}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['id'], oid)
        self.assertEqual(data['order_number'], order['order_number'])
        self.assertIn('total_items', data)
        self.assertIn('total_qty', data)
        self.assertIn('total_amount', data)
        self.assertIn('items', data)
        self.assertGreater(len(data['items']), 0)
        first_item = data['items'][0]
        self.assertIn('name', first_item)
        self.assertIn('qty', first_item)
        self.assertIn('price', first_item)
        self.assertIn('subtotal', first_item)

if __name__ == '__main__':
    unittest.main()
