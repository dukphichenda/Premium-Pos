import unittest
import json
from app import create_app
from database import query_one, execute, get_db_cursor

class ModernStockAdjustmentsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

    def test_new_adjustment_page_renders_with_inflow_features(self):
        """Test GET /inventory/adjustments/new contains inFlow screenshot layout & options."""
        res = self.client.get('/inventory/adjustments/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        
        # Verify requested features exist
        self.assertIn("Stock Adjustment Number", html)
        self.assertIn("Reason", html)
        self.assertIn("Correction", html)
        self.assertIn("Write-Off", html)
        self.assertIn("Internal usage", html)
        self.assertIn("Add one by one", html)
        self.assertIn("Add by Category", html)
        self.assertIn("Add All Products", html)
        self.assertIn("Qty on Hand", html)
        self.assertIn("Qty Reserved", html)
        self.assertIn("Initial", html)
        self.assertIn("Change", html)
        self.assertIn("Final", html)
        self.assertIn("Adjust stock", html)
        self.assertIn("Remove stock", html)
        self.assertIn("Add stock", html)

    def test_api_products_for_adjustment_endpoint(self):
        """Test API returning products with on_hand_qty and reserved_qty."""
        res = self.client.get('/api/inventory/products-for-adjustment?all=true')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('products', data)
        self.assertGreaterEqual(len(data['products']), 0)
        if len(data['products']) > 0:
            first = data['products'][0]
            self.assertIn('on_hand_qty', first)
            self.assertIn('reserved_qty', first)
            self.assertIn('available_qty', first)
            self.assertIn('sublocation', first)

    def test_create_and_view_modern_batch_stock_adjustment(self):
        """Test multi-product batch creation and viewing in detail."""
        # Find 1 or 2 test products
        p1 = query_one("SELECT id, sku, name FROM products WHERE is_active = TRUE LIMIT 1")
        if not p1:
            self.skipTest("No products in database to test adjustments")

        loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1") or query_one("SELECT id FROM locations LIMIT 1")
        loc_id = loc['id'] if loc else 100

        # Post modern JSON adjustment
        adj_number = f"TEST-ADJ-{p1['id']}"
        payload = {
            'location_id': loc_id,
            'adjustment_number': adj_number,
            'adjustment_date': '2026-10-16',
            'reason': 'Correction',
            'notes': 'Automated test adjustment verification',
            'custom_fields_json': {
                'auditor': 'Antigravity Test Suite',
                'reference_doc': 'SO-9999',
                'tag': 'Unit-Test'
            },
            'lines': [
                {
                    'product_id': p1['id'],
                    'sublocation': 'A-5',
                    'initial_qty': 10,
                    'change_qty': -2,
                    'final_qty': 8
                }
            ]
        }

        res = self.client.post(
            '/inventory/adjustments/create',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'Accept': 'application/json'}
        )
        self.assertEqual(res.status_code, 200)
        resp_data = json.loads(res.data)
        self.assertTrue(resp_data['success'])
        self.assertIn('adjustment_id', resp_data)
        adj_id = resp_data['adjustment_id']

        # Now view detail page
        detail_res = self.client.get(f'/inventory/adjustments/{adj_id}')
        self.assertEqual(detail_res.status_code, 200)
        detail_html = detail_res.data.decode('utf-8')
        self.assertIn(adj_number, detail_html)
        self.assertIn(p1['sku'], detail_html)
        self.assertIn("A-5", detail_html)

if __name__ == '__main__':
    unittest.main()
