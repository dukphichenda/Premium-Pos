import unittest
from app import app
from routes.products import _build_price_card_data, _get_product_detail_bundle
from database import query_one, execute

class TestTierQtySave(unittest.TestCase):
    def setUp(self):
        self.ctx = app.test_request_context()
        self.ctx.push()
        # Save original state of product 307
        self.orig = query_one('SELECT tier_qty_1, tier_qty_2, tier_qty_3, tier_price_1, tier_price_2, tier_price_3 FROM products WHERE id = 307')

    def tearDown(self):
        if self.orig:
            execute('''
                UPDATE products 
                SET tier_qty_1 = %s, tier_qty_2 = %s, tier_qty_3 = %s,
                    tier_price_1 = %s, tier_price_2 = %s, tier_price_3 = %s
                WHERE id = 307
            ''', (self.orig['tier_qty_1'], self.orig['tier_qty_2'], self.orig['tier_qty_3'],
                  self.orig['tier_price_1'], self.orig['tier_price_2'], self.orig['tier_price_3']))
        self.ctx.pop()

    def test_tier_qty_preserves_300_and_600(self):
        """Verify that setting tier_qty_2 = 300 and tier_qty_3 = 600 is NOT overridden by defaults"""
        execute('UPDATE products SET tier_qty_1 = 100, tier_qty_2 = 300, tier_qty_3 = 600 WHERE id = 307')
        bundle = _get_product_detail_bundle(307)
        pc = bundle['price_card']
        self.assertEqual(pc['tier_qty_1'], 100)
        self.assertEqual(pc['tier_qty_2'], 300)
        self.assertEqual(pc['tier_qty_3'], 600)

    def test_tier_qty_preserves_custom_values(self):
        """Verify custom values like 50, 500, 1000 are preserved"""
        execute('UPDATE products SET tier_qty_1 = 50, tier_qty_2 = 500, tier_qty_3 = 1000 WHERE id = 307')
        bundle = _get_product_detail_bundle(307)
        pc = bundle['price_card']
        self.assertEqual(pc['tier_qty_1'], 50)
        self.assertEqual(pc['tier_qty_2'], 500)
        self.assertEqual(pc['tier_qty_3'], 1000)

    def test_tier_qty_null_uses_dynamic_case_defaults(self):
        """Verify that when tier_qty is NULL, dynamic carton calculation applies"""
        execute('UPDATE products SET tier_qty_1 = NULL, tier_qty_2 = NULL, tier_qty_3 = NULL WHERE id = 307')
        bundle = _get_product_detail_bundle(307)
        pc = bundle['price_card']
        # Product 307: 12 packs * 50 pcs = 600 pcs/case
        self.assertEqual(pc['tier_qty_1'], 100)
        self.assertEqual(pc['tier_qty_2'], 600)
        self.assertEqual(pc['tier_qty_3'], 1200)

    def test_tier_price_preserves_42_and_81(self):
        """Verify that tier_price_2 = 42.0 and tier_price_3 = 81.0 are not discarded"""
        execute('UPDATE products SET tier_qty_1 = 100, tier_qty_2 = 300, tier_qty_3 = 600, tier_price_1 = 15.0, tier_price_2 = 42.0, tier_price_3 = 81.0 WHERE id = 307')
        bundle = _get_product_detail_bundle(307)
        pc = bundle['price_card']
        self.assertEqual(pc['tot_price_2'], 42.0)
        self.assertEqual(pc['tot_price_3'], 81.0)

    def test_ajax_update_tier_qty(self):
        """Verify POST /products/307/update_ajax updates and returns new tier_qty values"""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['role'] = 'main_admin'
            
            res = client.post('/products/307/update_ajax', json={
                'tier_qty_1': 100,
                'tier_qty_2': 300,
                'tier_qty_3': 600
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['success'])
            pc = data['price_card']
            self.assertEqual(pc['tier_qty_1'], 100)
            self.assertEqual(pc['tier_qty_2'], 300)
            self.assertEqual(pc['tier_qty_3'], 600)

            # Verify in DB
            db_row = query_one('SELECT tier_qty_1, tier_qty_2, tier_qty_3 FROM products WHERE id = 307')
            self.assertEqual(db_row['tier_qty_1'], 100)
            self.assertEqual(db_row['tier_qty_2'], 300)
            self.assertEqual(db_row['tier_qty_3'], 600)

if __name__ == '__main__':
    unittest.main()
