import unittest
import json
from app import create_app
from database import get_db_cursor

class TestBrownLookPriceTableStyle(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Fetch an existing category and save original style to restore cleanly
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT id, name, price_table_style FROM categories ORDER BY id ASC LIMIT 1;")
            row = cursor.fetchone()
            self.test_cat_id = row['id']
            self.orig_cat_style = row['price_table_style'] or 'classic'
            
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style';")
            setting = cursor.fetchone()
            self.orig_global_style = setting['setting_value'] if setting else 'classic'

    def tearDown(self):
        # Restore original category and global styles cleanly
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("UPDATE categories SET price_table_style = %s WHERE id = %s;", (self.orig_cat_style, self.test_cat_id))
            cursor.execute("UPDATE app_settings SET setting_value = %s WHERE setting_key = 'default_price_table_style';", (self.orig_global_style,))

    def test_categories_page_renders_brown_style_options(self):
        """Verify /categories page contains Brown Look global button, row toggle button, and modal radio cards."""
        resp = self.client.get('/categories')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Global Switcher in Header has Brown Look button
        self.assertIn('globalBtnBrown', html)
        self.assertIn("applyGlobalPriceTableStyle('brown')", html)
        self.assertIn('☕ Brown Look', html)

        # Table Column Row Action Pills have Brown button
        self.assertIn(f'cat-btn-brown-{self.test_cat_id}', html)
        self.assertIn('cat-style-pill-btn', html)

        # Add & Edit Category Modals have radio cards for Brown Look
        self.assertIn('newStyleRadioBrown', html)
        self.assertIn('editStyleRadioBrown', html)
        self.assertIn('newStyleCardBrown', html)
        self.assertIn('editStyleCardBrown', html)

    def test_api_set_single_category_style_brown(self):
        """Verify /api/categories/<id>/set-style updates the category price table style to brown."""
        resp = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'brown'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'brown')

        # Verify in DB
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT price_table_style FROM categories WHERE id = %s;", (self.test_cat_id,))
            cat = cursor.fetchone()
            self.assertEqual(cat['price_table_style'], 'brown')

        # Test alias 'brown_look' normalizes to 'brown'
        resp_alias = self.client.post(
            f'/api/categories/{self.test_cat_id}/set-style',
            data=json.dumps({'style': 'brown_look'}),
            content_type='application/json'
        )
        self.assertEqual(resp_alias.status_code, 200)
        data_alias = json.loads(resp_alias.data.decode('utf-8'))
        self.assertTrue(data_alias.get('success'))
        self.assertEqual(data_alias.get('style'), 'brown')

    def test_api_set_all_categories_style_brown(self):
        """Verify /api/categories/set-all-style updates all categories and app_settings to brown."""
        resp = self.client.post(
            '/api/categories/set-all-style',
            data=json.dumps({'style': 'brown'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('style'), 'brown')

        # Verify DB all categories have 'brown'
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM categories WHERE price_table_style != 'brown';")
            diff = cursor.fetchone()['count']
            self.assertEqual(diff, 0)

            # Verify app_settings has 'brown'
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style';")
            setting = cursor.fetchone()
            self.assertEqual(setting['setting_value'], 'brown')

    def test_price_list_page_renders_brown_and_aspect_ratio(self):
        """Verify /products/price-list renders Brown Look option, builder function, and 1 / 0.9 aspect ratio."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check Brown Look dropdown option and JS function
        self.assertIn('<option value="brown">☕ Brown Look (Image 5)</option>', html)
        self.assertIn('buildBrownCardHtml', html)
        self.assertIn('.inflow-spec-card.brown', html)
        self.assertIn('inflow-brown-deco-wheat-tr', html)
        self.assertIn('inflow-brown-price-wrap', html)

        # Check aspect ratio 1 / 0.9 and 680x612 dimensions
        self.assertIn('aspect-ratio: 1 / 0.9 !important;', html)
        self.assertIn('width: 680', html)
        self.assertIn('height: 612', html)

    def test_product_detail_and_catalog_render_brown(self):
        """Verify product detail and workspace catalog contain #cardContentBrown sections."""
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1;")
            prod = cursor.fetchone()
            self.assertIsNotNone(prod, "At least one active product must exist")
            prod_id = prod['id']

        # Temporarily set category to brown
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("UPDATE categories SET price_table_style = 'brown' WHERE id = %s;", (self.test_cat_id,))

        resp = self.client.get(f'/products/{prod_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('id="cardContentBrown"', html)
        self.assertIn('inflow-brown-header', html)
        self.assertIn('inflow-brown-specs-card', html)
        self.assertIn('inflow-brown-price-wrap', html)
        self.assertIn('inflow-brown-tot-capsule', html)

        # Legacy detail page
        resp_leg = self.client.get(f'/products/{prod_id}?legacy=1')
        self.assertEqual(resp_leg.status_code, 200)
        leg_html = resp_leg.data.decode('utf-8')
        self.assertIn('id="cardContentBrownDetail"', leg_html)
        self.assertIn('inflow-brown-header', leg_html)
        self.assertIn('inflow-brown-specs-card', leg_html)
        self.assertIn('inflow-brown-price-wrap', leg_html)

    def test_product_catalog_facebook_renders_brown_option(self):
        """Verify /product_catalog (Card Mode) includes Brown Look option and .cat-card.brown CSS."""
        resp = self.client.get('/product_catalog')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('<option value="brown">☕ Brown Look</option>', html)
        self.assertIn('.cat-card.brown', html)

    def test_zero_test_sales_orders_and_rule1_compliance(self):
        """Verify zero test sales orders exist and database integrity is maintained."""
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM sales_orders so 
                LEFT JOIN customers c ON so.customer_id = c.id 
                WHERE so.order_number ILIKE '%TEST%' OR c.name ILIKE '%TEST%';
            """)
            test_so_count = cursor.fetchone()['count']
            self.assertEqual(test_so_count, 0, f"Found {test_so_count} lingering test sales orders. Expected 0.")

if __name__ == '__main__':
    unittest.main()
