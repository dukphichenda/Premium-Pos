import sys
import os
import unittest
import json

sys.path.insert(0, os.path.abspath('.'))
from app import create_app
import database

class TestDecimalSettings(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_settings_page_renders_decimal_sections(self):
        """Verify settings page has System Defaults and Per-Item decimal sections."""
        resp = self.client.get('/settings?tab=tabDecimals')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn("Decimal Numbers & Precision", html)
        self.assertIn("System Default Decimal Places", html)
        self.assertIn("Per-Item Decimal Settings", html)
        self.assertIn("Selling Price Decimals", html)
        self.assertIn("Costing / Unit Cost Decimals", html)
        self.assertIn("Quantity / Stock Decimals", html)
        self.assertIn("itemsDecimalTable", html)

    def test_update_system_decimal_defaults(self):
        """Verify updating system-wide decimal defaults."""
        post_data = {
            'active_tab': 'tabDecimals',
            'name': 'inFlow Premium Business',
            'decimal_places_price': '2',
            'decimal_places_cost': '3',
            'decimal_places_qty': '0',
            'decimal_places_markup': '2',
            'decimal_places_total': '2',
            'decimal_places_measurement': '2'
        }
        resp = self.client.post('/settings/update', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        company = database.query_one("SELECT decimal_places_price, decimal_places_cost, decimal_places_qty FROM companies LIMIT 1")
        self.assertEqual(company['decimal_places_price'], 2)
        self.assertEqual(company['decimal_places_cost'], 3)
        self.assertEqual(company['decimal_places_qty'], 0)

    def test_single_item_decimal_override(self):
        """Verify setting decimal numbers separately for an individual item."""
        prod = database.query_one("SELECT id FROM products WHERE id = 102")
        self.assertIsNotNone(prod, "Product 102 should exist")

        # Set custom decimals: price=3, cost=4, qty=1
        payload = {
            'price_decimals': '3',
            'cost_decimals': '4',
            'qty_decimals': '1'
        }
        resp = self.client.post(f'/settings/items/{prod["id"]}/decimals',
                                data=json.dumps(payload),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        res = json.loads(resp.data)
        self.assertTrue(res['success'])

        # Verify in database
        updated = database.query_one("SELECT price_decimals, cost_decimals, qty_decimals FROM products WHERE id = %s", (prod['id'],))
        self.assertEqual(updated['price_decimals'], 3)
        self.assertEqual(updated['cost_decimals'], 4)
        self.assertEqual(updated['qty_decimals'], 1)

        # Reset back to default (None)
        reset_payload = {
            'price_decimals': None,
            'cost_decimals': None,
            'qty_decimals': None
        }
        resp = self.client.post(f'/settings/items/{prod["id"]}/decimals',
                                data=json.dumps(reset_payload),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        res = json.loads(resp.data)
        self.assertTrue(res['success'])

        reset_item = database.query_one("SELECT price_decimals, cost_decimals, qty_decimals FROM products WHERE id = %s", (prod['id'],))
        self.assertIsNone(reset_item['price_decimals'])
        self.assertIsNone(reset_item['cost_decimals'])
        self.assertIsNone(reset_item['qty_decimals'])

    def test_batch_item_decimals_update(self):
        """Verify batch updating decimal numbers for multiple items."""
        items_payload = {
            'items': [
                {'id': 100, 'price_decimals': 2, 'cost_decimals': 3, 'qty_decimals': 0},
                {'id': 101, 'price_decimals': 1, 'cost_decimals': 2, 'qty_decimals': 0}
            ]
        }
        resp = self.client.post('/api/settings/items/decimals/batch',
                                data=json.dumps(items_payload),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        res = json.loads(resp.data)
        self.assertTrue(res['success'])

    def test_search_items_for_decimals(self):
        """Verify AJAX search for items in settings."""
        resp = self.client.get('/api/settings/items/search?q=HT25A')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertGreaterEqual(len(data['items']), 1)
        self.assertIn("HT25A", data['items'][0]['name'])

if __name__ == '__main__':
    unittest.main()
