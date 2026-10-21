import unittest
import json
from app import create_app
from database import get_db_cursor

class TestGenZPriceTableStyle(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Ensure we have at least one test category in database
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT id, name, price_table_style FROM categories ORDER BY id ASC LIMIT 1;")
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO categories (name, price_table_style) VALUES ('Test Gen Z Cat', 'classic') RETURNING id, name, price_table_style;")
                row = cursor.fetchone()
            self.test_cat_id = row['id']
            self.test_cat_name = row['name']

    def test_categories_page_renders_gen_z_style_options(self):
        """Verify /categories page contains Gen Z global button, row toggle button, and modal radio cards."""
        resp = self.client.get('/categories')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Global Switcher in Header has Gen Z button
        self.assertIn('globalBtnGenZ', html)
        self.assertIn("applyGlobalPriceTableStyle('gen_z')", html)
        self.assertIn('⚡ Gen Z', html)

        # Table Column Row Action Pills have Gen Z button
        self.assertIn(f'cat-btn-gen_z-{self.test_cat_id}', html)
        self.assertIn('cat-style-pill-btn', html)

        # Add & Edit Category Modals have radio cards for Gen Z
        self.assertIn('newStyleRadioGenZ', html)
        self.assertIn('editStyleRadioGenZ', html)
        self.assertIn('newStyleCardGenZ', html)
        self.assertIn('editStyleCardGenZ', html)

    def test_api_set_single_category_style_gen_z(self):
        """Verify /api/categories/<id>/set-style updates the category price table style to gen_z."""
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'gen_z'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'gen_z')

        # Verify in DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_table_style FROM categories WHERE id = %s;", (self.test_cat_id,))
            cat = cursor.fetchone()
            self.assertEqual(cat['price_table_style'], 'gen_z')

        # Revert back to classic
        self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )

    def test_api_set_all_categories_style_gen_z(self):
        """Verify /api/categories/set-all-style updates all categories and app_settings to gen_z."""
        resp = self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'gen_z'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'gen_z')

        # Verify DB all categories have 'gen_z'
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM categories WHERE price_table_style != 'gen_z';")
            diff = cursor.fetchone()['count']
            self.assertEqual(diff, 0)

            # Verify app_settings has 'gen_z'
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style';")
            setting = cursor.fetchone()
            self.assertEqual(setting['setting_value'], 'gen_z')

        # Reset to classic
        self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )

    def test_product_detail_and_catalog_render_gen_z(self):
        """Verify product catalog/detail renders Gen Z style button, #cardContentGenZ, and Gen Z design elements."""
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod = cursor.fetchone()
            if not prod:
                cursor.execute("""
                    INSERT INTO products (name, sku, category_id, is_active)
                    VALUES ('Test Product Gen Z', 'GENZ-SKU-1', %s, TRUE)
                    RETURNING id;
                """, (self.test_cat_id,))
                prod = cursor.fetchone()
            prod_id = prod['id']

            # Set product price_card_style to 'gen_z'
            cursor.execute("UPDATE products SET price_card_style = 'gen_z' WHERE id = %s;", (prod_id,))

        resp = self.client.get(f'/products/{prod_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Style switcher has Gen Z button
        self.assertIn('btnDetailStyleGenZ', html)
        self.assertIn('⚡ Gen Z', html)
        self.assertIn("setProductPriceCardStyle('gen_z')", html)

        # Card container has gen_z class and #cardContentGenZ
        self.assertIn('id="cardContentGenZ"', html)
        self.assertIn('inflow-genz-header', html)
        self.assertIn('inflow-genz-crown-doodle', html)
        self.assertIn('inflow-genz-mood-doodle', html)
        self.assertIn('inflow-genz-specs-card', html)
        self.assertIn('inflow-genz-price-wrap', html)
        self.assertIn('inflow-genz-tot-capsule', html)
        self.assertIn('inflow-genz-best-choice-sticker', html)

        # Legacy detail page
        resp_leg = self.client.get(f'/products/{prod_id}?legacy=1')
        self.assertEqual(resp_leg.status_code, 200)
        leg_html = resp_leg.data.decode('utf-8')
        self.assertIn('btnDetailStyleGenZDetail', leg_html)
        self.assertIn('id="cardContentGenZDetail"', leg_html)
        self.assertIn('inflow-genz-header', leg_html)
        self.assertIn('inflow-genz-specs-card', leg_html)
        self.assertIn('inflow-genz-tot-capsule', leg_html)
        self.assertIn('inflow-genz-best-choice-sticker', leg_html)

    def test_product_price_card_style_persistence_gen_z(self):
        """Verify updating a product's price_card_style to 'gen_z' via update_ajax persists."""
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod = cursor.fetchone()
            prod_id = prod['id']

        resp = self.client.post(
            f'/products/{prod_id}/update_ajax',
            data=json.dumps({'field': 'price_card_style', 'value': 'gen_z'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))

        # Verify DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_card_style FROM products WHERE id = %s;", (prod_id,))
            p = cursor.fetchone()
            self.assertEqual(p['price_card_style'], 'gen_z')

    def test_price_list_page_renders_gen_z_option(self):
        """Verify /products/price-list page contains Gen Z option in cardStyleFilter."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('<option value="gen_z">⚡ Gen Z (Image 4)</option>', html)
        self.assertIn('buildGenZCardHtml', html)

if __name__ == '__main__':
    unittest.main()
