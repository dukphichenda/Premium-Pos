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

        # Multi-category dropdown elements
        self.assertIn("adjCategoryTriggerBtn", html)
        self.assertIn("catMultiSelectContainer", html)
        self.assertIn("adjCategoryDropdownMenu", html)
        self.assertIn("adj-cat-cb", html)
        self.assertIn("Select All", html)

        # Arrangement modal elements
        self.assertIn("adjArrangeModal", html)
        self.assertIn("By Category", html)
        self.assertIn("By Letter / Alphabetical", html)
        self.assertIn("Lowest Stock First", html)
        self.assertIn("Highest Stock First", html)
        self.assertIn("Confirm & Add All Products", html)
        self.assertIn("adjTableArrangeSelect", html)

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

        import time
        adj_number = f"TEST-ADJ-{p1['id']}-{int(time.time()*1000)}"
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
        if res.status_code != 200:
            print("FAILED RESPONSE:", res.data.decode('utf-8'))
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

    def test_multi_category_products_selection(self):
        """Test API allows selecting multiple categories simultaneously."""
        cats = query_one("SELECT id FROM categories LIMIT 2")
        if not cats:
            self.skipTest("No categories found in database")
        
        # Test comma-separated category_ids
        res = self.client.get(f'/api/inventory/products-for-adjustment?category_ids=101,102')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        
        # All returned products must belong to one of the selected categories
        for p in data['products']:
            self.assertIn(p['category_id'], [101, 102])

    def test_add_all_products_sorting_options(self):
        """Test API sorting by category, letter/latter, lowest stock, and highest stock."""
        # 1. By Category
        res_cat = self.client.get('/api/inventory/products-for-adjustment?all=true&sort_by=category')
        self.assertEqual(res_cat.status_code, 200)
        prods_cat = json.loads(res_cat.data)['products']
        if len(prods_cat) >= 2:
            cat_names = [p['category_name'].lower() for p in prods_cat]
            self.assertEqual(cat_names, sorted(cat_names))

        # 2. By Letter (A-Z)
        res_letter = self.client.get('/api/inventory/products-for-adjustment?all=true&sort_by=letter')
        self.assertEqual(res_letter.status_code, 200)
        prods_letter = json.loads(res_letter.data)['products']
        if len(prods_letter) >= 2:
            names = [p['name'].lower() for p in prods_letter]
            self.assertEqual(names, sorted(names))

        # 3. By Lowest Stock
        res_low = self.client.get('/api/inventory/products-for-adjustment?all=true&sort_by=lowest_stock')
        self.assertEqual(res_low.status_code, 200)
        prods_low = json.loads(res_low.data)['products']
        if len(prods_low) >= 2:
            quantities = [p['on_hand_qty'] for p in prods_low]
            self.assertEqual(quantities, sorted(quantities))

        # 4. By Highest Stock
        res_high = self.client.get('/api/inventory/products-for-adjustment?all=true&sort_by=highest_stock')
        self.assertEqual(res_high.status_code, 200)
        prods_high = json.loads(res_high.data)['products']
        if len(prods_high) >= 2:
            quantities = [p['on_hand_qty'] for p in prods_high]
            self.assertEqual(quantities, sorted(quantities, reverse=True))

if __name__ == '__main__':
    unittest.main()

