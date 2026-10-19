import unittest
import json
from app import create_app
from database import get_db_cursor

class TestCategoryPriceTableStyle(unittest.TestCase):
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
                cursor.execute("INSERT INTO categories (name, price_table_style) VALUES ('Test Cat', 'classic') RETURNING id, name, price_table_style;")
                row = cursor.fetchone()
            self.test_cat_id = row['id']
            self.test_cat_name = row['name']

    def test_categories_page_renders_style_switchers(self):
        """Verify /categories page contains Global Style Switcher, Table Style Column, and Modals."""
        resp = self.client.get('/categories')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Global Switcher in Header
        self.assertIn('All Products Style:', html)
        self.assertIn('applyGlobalPriceTableStyle', html)
        self.assertIn('/api/categories/set-all-style', html)

        # Table Column & Row Action Pills
        self.assertIn('Price Table Style', html)
        self.assertIn('setCategoryStyle', html)
        self.assertIn(f'cat-btn-classic-{self.test_cat_id}', html)
        self.assertIn(f'cat-btn-modern-{self.test_cat_id}', html)

        # Add & Edit Category Modals have radio cards
        self.assertIn('newStyleRadioClassic', html)
        self.assertIn('newStyleRadioModern', html)
        self.assertIn('editStyleRadioClassic', html)
        self.assertIn('editStyleRadioModern', html)

    def test_api_set_single_category_style(self):
        """Verify /api/categories/<id>/set-style updates the category price table style."""
        # 1. Update to modern
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'modern'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'modern')

        # Verify in DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_table_style FROM categories WHERE id = %s;", (self.test_cat_id,))
            cat = cursor.fetchone()
            self.assertEqual(cat['price_table_style'], 'modern')

        # 2. Update to classic
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'classic')

        # 3. Invalid style rejected
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'unsupported_style'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_set_all_categories_style(self):
        """Verify /api/categories/set-all-style updates all categories and app_settings."""
        # Set all to modern
        resp = self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'modern'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'modern')

        # Verify DB all categories have 'modern'
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM categories WHERE price_table_style != 'modern';")
            diff = cursor.fetchone()['count']
            self.assertEqual(diff, 0)

            # Verify app_settings has 'modern'
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style';")
            setting = cursor.fetchone()
            self.assertEqual(setting['setting_value'], 'modern')

        # Reset to classic
        resp = self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)

    def test_price_list_includes_card_style_options(self):
        """Verify /products/price-list includes Card Style selector and modern card support."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Toolbar dropdown
        self.assertIn('id="cardStyleFilter"', html)
        self.assertIn('value="auto"', html)
        self.assertIn('value="modern"', html)
        self.assertIn('value="classic"', html)

        # JavaScript builders & Modern CSS
        self.assertIn('buildModernCardHtml', html)
        self.assertIn('buildClassicCardHtml', html)
        self.assertIn('pl-price-card modern', html)
        self.assertIn('pl-modern-header', html)
        self.assertIn('pl-modern-specs-box', html)
        self.assertIn('pl-modern-price-banner', html)

    def test_product_detail_reflects_price_table_style(self):
        """Verify product detail page /products/<id> renders Classic & Modern card styles correctly."""
        # Find a product in the test category or any active product
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod = cursor.fetchone()
            if not prod:
                cursor.execute("""
                    INSERT INTO products (name, sku, category_id, is_active)
                    VALUES ('Test Product Price Card', 'TEST-PC-1', %s, TRUE)
                    RETURNING id;
                """, (self.test_cat_id,))
                prod = cursor.fetchone()
            prod_id = prod['id']

            # Set category to modern
            cursor.execute("UPDATE categories SET price_table_style = 'modern' WHERE id = %s;", (self.test_cat_id,))
            cursor.execute("UPDATE products SET category_id = %s, price_card_style = NULL WHERE id = %s;", (self.test_cat_id, prod_id))

        # Request product catalog / detail page
        resp = self.client.get(f'/products/{prod_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check for style switcher buttons
        self.assertIn('btnDetailStyleClassic', html)
        self.assertIn('btnDetailStyleModern', html)
        self.assertIn('setProductPriceCardStyle', html)

        # Check for both card content containers
        self.assertIn('id="cardContentClassic"', html)
        self.assertIn('id="cardContentModern"', html)
        self.assertIn('inflow-modern-header', html)
        self.assertIn('inflow-modern-specs-box', html)
        self.assertIn('inflow-modern-price-banner', html)

    def test_product_detail_update_price_card_style_ajax(self):
        """Verify updating a product's price_card_style via update_product_ajax persists to the database."""
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod_id = cursor.fetchone()['id']

        # Update to modern
        resp = self.client.post(
            f'/products/{prod_id}/update_ajax',
            data=json.dumps({'price_card_style': 'modern'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))

        # Verify DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_card_style FROM products WHERE id = %s;", (prod_id,))
            p = cursor.fetchone()
            self.assertEqual(p['price_card_style'], 'modern')

        # Update back to classic
        resp = self.client.post(
            f'/products/{prod_id}/update_ajax',
            data=json.dumps({'price_card_style': 'classic'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))

        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_card_style FROM products WHERE id = %s;", (prod_id,))
            p = cursor.fetchone()
            self.assertEqual(p['price_card_style'], 'classic')

if __name__ == '__main__':
    unittest.main()
