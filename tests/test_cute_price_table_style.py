import unittest
import json
from app import create_app
from database import get_db_cursor

class TestCutePriceTableStyle(unittest.TestCase):
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
                cursor.execute("INSERT INTO categories (name, price_table_style) VALUES ('Test Cute Cat', 'classic') RETURNING id, name, price_table_style;")
                row = cursor.fetchone()
            self.test_cat_id = row['id']
            self.test_cat_name = row['name']

    def test_categories_page_renders_cute_style_options(self):
        """Verify /categories page contains Cute Look global button, row toggle button, and modal radio cards."""
        resp = self.client.get('/categories')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Global Switcher in Header has Cute button
        self.assertIn('globalBtnCute', html)
        self.assertIn('applyGlobalPriceTableStyle(\'cute\')', html)
        self.assertIn('🌸 Cute Look', html)

        # Table Column Row Action Pills have Cute button
        self.assertIn(f'cat-btn-cute-{self.test_cat_id}', html)
        self.assertIn('cat-style-pill-btn', html)

        # Add & Edit Category Modals have radio cards for Cute
        self.assertIn('newStyleRadioCute', html)
        self.assertIn('editStyleRadioCute', html)
        self.assertIn('newStyleCardCute', html)
        self.assertIn('editStyleCardCute', html)

    def test_api_set_single_category_style_cute(self):
        """Verify /api/categories/<id>/set-style updates the category price table style to cute."""
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'cute'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'cute')

        # Verify in DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_table_style FROM categories WHERE id = %s;", (self.test_cat_id,))
            cat = cursor.fetchone()
            self.assertEqual(cat['price_table_style'], 'cute')

        # Revert back to classic
        self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )

    def test_api_set_all_categories_style_cute(self):
        """Verify /api/categories/set-all-style updates all categories and app_settings to cute."""
        resp = self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'cute'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'cute')

        # Verify DB all categories have 'cute'
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM categories WHERE price_table_style != 'cute';")
            diff = cursor.fetchone()['count']
            self.assertEqual(diff, 0)

            # Verify app_settings has 'cute'
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style';")
            setting = cursor.fetchone()
            self.assertEqual(setting['setting_value'], 'cute')

        # Reset to classic
        self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'classic'}),
            content_type='application/json'
        )

    def test_product_detail_and_catalog_render_cute_look(self):
        """Verify product catalog/detail renders Cute Look style button, #cardContentCute, and cute pill capsules."""
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod = cursor.fetchone()
            if not prod:
                cursor.execute("""
                    INSERT INTO products (name, sku, category_id, is_active)
                    VALUES ('Test Product Cute Look', 'CUTE-SKU-1', %s, TRUE)
                    RETURNING id;
                """, (self.test_cat_id,))
                prod = cursor.fetchone()
            prod_id = prod['id']

            # Set product price_card_style to 'cute'
            cursor.execute("UPDATE products SET price_card_style = 'cute' WHERE id = %s;", (prod_id,))

        resp = self.client.get(f'/products/{prod_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Style switcher has Cute Look button
        self.assertIn('btnDetailStyleCute', html)
        self.assertIn('🌸 Cute Look', html)
        self.assertIn('setProductPriceCardStyle(\'cute\')', html)

        # Card container has cute class and #cardContentCute
        self.assertIn('id="cardContentCute"', html)
        self.assertIn('inflow-cute-header', html)
        self.assertIn('inflow-cute-price-wrap', html)
        self.assertIn('inflow-cute-left-pill', html)
        self.assertIn('inflow-cute-right-pill', html)
        # Verify all tier rows use coral (orange) total price and not green
        self.assertIn('inflow-cute-tier-tot-coral', html)
        self.assertNotIn('inflow-cute-tier-tot-green font-khmer', html)
        self.assertIn('PCS/ Carton)', html)

        # Legacy detail page
        resp_leg = self.client.get(f'/products/{prod_id}?legacy=1')
        self.assertEqual(resp_leg.status_code, 200)
        leg_html = resp_leg.data.decode('utf-8')
        self.assertIn('btnDetailStyleCuteDetail', leg_html)
        self.assertIn('id="cardContentCuteDetail"', leg_html)
        self.assertIn('inflow-cute-tier-tot-coral', leg_html)
        self.assertNotIn('inflow-cute-tier-tot-green font-khmer', leg_html)
        self.assertIn('PCS/ Carton)', leg_html)

    def test_product_price_card_style_persistence(self):
        """Verify updating a product's price_card_style to 'cute' via update_ajax persists."""
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod_id = cursor.fetchone()['id']

        resp = self.client.post(
            f'/products/{prod_id}/update_ajax',
            data=json.dumps({'price_card_style': 'cute'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))

        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_card_style FROM products WHERE id = %s;", (prod_id,))
            p = cursor.fetchone()
            self.assertEqual(p['price_card_style'], 'cute')

        # Revert
        self.client.post(
            f'/products/{prod_id}/update_ajax',
            data=json.dumps({'price_card_style': 'classic'}),
            content_type='application/json'
        )

    def test_price_list_page_supports_cute_style(self):
        """Verify /products/price-list includes Cute Look dropdown option and buildCuteCardHtml."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('value="cute"', html)
        self.assertIn('buildCuteCardHtml', html)
        self.assertIn('.inflow-spec-card.cute', html)
        self.assertIn('inflow-cute-header', html)
        self.assertIn('inflow-cute-price-wrap', html)
        # Verify coral total price class is used across tier rows
        self.assertIn('inflow-cute-tier-tot-coral', html)
        self.assertNotIn('inflow-cute-tier-tot-green font-khmer', html)

if __name__ == '__main__':
    unittest.main()
