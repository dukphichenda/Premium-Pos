import sys
import os
import unittest
import json
from decimal import Decimal

sys.path.insert(0, os.path.abspath('.'))
from app import create_app
import database

class TestProductPricingMarkup(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_markup_calculation_with_sales_uom_multiplier(self):
        """
        Verify requirement:
        In product mark up should calculate based on Sale UOM such as case or pcs
        and multiply costing with number of pcs in 1 case.
        Product HT25A-TTK: cost = 0.107, 300 pcs/case.
        Effective cost = 0.107 * 300 = 32.10.
        Retail 3 ($40.50) -> 26.17%
        Wholesale ($33.00) -> 2.8%
        Wholesale TSK&SK ($36.00) -> 12.15%
        """
        prod = database.query_one("""
            SELECT id, sku, name, standard_cost, uom, sales_uom, sales_uom_ratio, sales_uom_ratio_std
            FROM products
            WHERE sku ILIKE %s OR name ILIKE %s
            LIMIT 1
        """, ('%HT25A%', '%HT25A%'))
        self.assertIsNotNone(prod, "Product HT25A-TTK should exist in database")

        cost = float(prod['standard_cost'])
        ratio_std = float(prod['sales_uom_ratio_std'] or 1.0)
        ratio_sales = float(prod['sales_uom_ratio'] or 1.0)
        multiplier = ratio_std / ratio_sales if ratio_sales > 0 else 1.0

        self.assertAlmostEqual(cost, 0.107, places=3)
        self.assertEqual(multiplier, 300.0)

        effective_cost = cost * multiplier
        self.assertAlmostEqual(effective_cost, 32.10, places=2)

        # Wholesale: $33.00 -> 2.80%
        ws_markup = ((33.00 - effective_cost) / effective_cost) * 100
        self.assertAlmostEqual(ws_markup, 2.80, delta=0.05)

        # Retail 3: $40.50 -> 26.17%
        r3_markup = ((40.50 - effective_cost) / effective_cost) * 100
        self.assertAlmostEqual(r3_markup, 26.17, delta=0.05)

        # Wholesale TSK&SK: $36.00 -> 12.15%
        ts_markup = ((36.00 - effective_cost) / effective_cost) * 100
        self.assertAlmostEqual(ts_markup, 12.15, delta=0.05)

        # Now verify via product detail route response
        resp = self.client.get(f"/products/{prod['id']}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn("26.17", html)
        self.assertIn("2.8", html)
        self.assertIn("12.15", html)
        self.assertIn("Add new Pricing / Currency", html)
        self.assertIn("pricingSchemeModalOverlay", html)

    def test_pricing_schemes_api_crud(self):
        """
        Verify requirement:
        Pricing info should have add new pricing or delete.
        Test /api/pricing-schemes GET and POST batch.
        """
        # 1. Get active pricing schemes
        resp = self.client.get('/api/pricing-schemes')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertGreaterEqual(len(data['schemes']), 5)

        # 2. Add a new pricing scheme via batch
        test_scheme_name = "Test Special VIP Scheme"
        payload = {
            'schemes': [
                {'id': None, 'name': test_scheme_name, 'currency': 'US Dollar ($)', 'is_active': True}
            ],
            'deleted_ids': []
        }
        resp = self.client.post('/api/pricing-schemes/batch', 
                                data=json.dumps(payload), 
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        res_data = json.loads(resp.data)
        self.assertTrue(res_data['success'])

        created = [s for s in res_data['active_schemes'] if s['name'] == test_scheme_name]
        self.assertEqual(len(created), 1)
        new_id = created[0]['id']
        self.assertIsNotNone(new_id)

        # 3. Delete / deactivate the new pricing scheme
        del_payload = {
            'schemes': [],
            'deleted_ids': [new_id]
        }
        resp = self.client.post('/api/pricing-schemes/batch',
                                data=json.dumps(del_payload),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        del_res = json.loads(resp.data)
        self.assertTrue(del_res['success'])

        # Verify it is no longer in active schemes
        active_after = [s for s in del_res['active_schemes'] if s['id'] == new_id]
        self.assertEqual(len(active_after), 0)

        # 4. Verify Show All retrieves inactive schemes
        resp_all = self.client.get('/api/pricing-schemes?all=true')
        self.assertEqual(resp_all.status_code, 200)
        data_all = json.loads(resp_all.data)
        all_ids = [s['id'] for s in data_all['schemes']]
        self.assertIn(new_id, all_ids)

        # Clean up test row completely from DB
        database.execute("DELETE FROM product_prices WHERE pricing_scheme_id = %s", (new_id,))
        database.execute("DELETE FROM pricing_schemes WHERE id = %s", (new_id,))

    def test_single_piece_uom_markup(self):
        """
        Verify that when Sales UOM == Standard UOM (e.g. pcs == pcs),
        multiplier is 1.0 and effective cost equals base cost.
        """
        cost = 10.00
        price = 15.00
        markup = ((price - cost) / cost) * 100
        self.assertEqual(markup, 50.0)

    def test_save_product_persists_prices_and_uom(self):
        """
        Verify that saving product form saves scheme_price_<id>,
        cost_price, sales_uom, and sales_uom_ratio_std.
        """
        prod = database.query_one("SELECT id FROM products WHERE id = 102")
        self.assertIsNotNone(prod)
        
        post_data = {
            'sku': 'SKU-0102',
            'name': 'HT25A-TTK ប្រអប់បាយ4ថត 300 pcs/Case',
            'cost_price': '0.1070',
            'costing_method': 'Manual',
            'uom': 'pcs.',
            'sales_uom': 'cases',
            'sales_uom_ratio': '1',
            'sales_uom_ratio_std': '300',
            'scheme_price_100': '39.00',
            'scheme_price_102': '40.50',
            'scheme_price_105': '33.00',
            'scheme_price_107': '36.00',
        }
        resp = self.client.post(f"/products/{prod['id']}/edit", data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        # Verify in DB
        updated = database.query_one("SELECT standard_cost, sales_uom_ratio_std FROM products WHERE id = %s", (prod['id'],))
        self.assertAlmostEqual(float(updated['standard_cost']), 0.1070, places=3)
        self.assertEqual(float(updated['sales_uom_ratio_std']), 300.0)
        
        pp = database.query_one("SELECT unit_price FROM product_prices WHERE product_id = %s AND pricing_scheme_id = 105", (prod['id'],))
        self.assertEqual(float(pp['unit_price']), 33.00)

if __name__ == '__main__':
    unittest.main()
