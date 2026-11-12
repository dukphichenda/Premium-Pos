import os
import unittest
from app import create_app
from database import get_db_cursor

class TestGenZPriceCardExportStyling(unittest.TestCase):
    def test_gen_z_price_list_html_styling(self):
        price_list_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'price_list.html')
        with open(price_list_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Check .inflow-spec-card.gen_z in price_list.html
        self.assertIn('border-radius: 28px !important;', content)
        self.assertIn('padding: 24px 26px 20px 26px !important;', content)
        self.assertIn('aspect-ratio: 1 / 1 !important;', content)
        self.assertIn('justify-content: space-between !important;', content)

        # 2. Check stage container is absolute positioned at 0, 0
        self.assertIn('id="plBatchExportStageContainer" style="position: absolute; left: 0; top: 0;', content)

        # 3. Check renderOffscreenPriceCard handles gen_z
        self.assertIn("styleToUse === 'gen_z' || styleToUse === 'genz'", content)
        self.assertIn("cardEl.style.justifyContent = 'space-between'", content)
        self.assertIn("cardEl.style.borderRadius = '28px'", content)
        self.assertIn("cardEl.style.padding = '24px 26px 20px 26px'", content)

        # 4. Check captureItemToCanvas passes scroll-offset proof html2canvas options
        self.assertIn('captureItemToCanvas', content)
        self.assertIn('x: 0', content)
        self.assertIn('y: 0', content)
        self.assertIn('width: 680', content)
        self.assertIn('height: 680', content)
        self.assertIn('scrollX: 0', content)
        self.assertIn('scrollY: 0', content)
        self.assertIn("clonedContainer.style.position = 'absolute'", content)

    def test_gen_z_styles_css(self):
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'styles.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check .inflow-spec-card.gen_z
        self.assertIn('.inflow-spec-card.gen_z', content)
        self.assertIn('border-radius: 28px !important;', content)
        self.assertIn('padding: 24px 26px 20px 26px !important;', content)

    def test_catalog_and_detail_offscreen_containers(self):
        cat_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(cat_path, 'r', encoding='utf-8') as f:
            cat_content = f.read()
        self.assertIn('id="batchPriceCardStageContainer" style="position: absolute; left: 0; top: 0;', cat_content)
        self.assertIn('#cardContentGenZ', cat_content)

        detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'detail.html')
        with open(detail_path, 'r', encoding='utf-8') as f:
            detail_content = f.read()
        self.assertIn('id="batchPriceCardStageContainerDetail" style="position: absolute; left: 0; top: 0;', detail_content)
        self.assertIn('#cardContentGenZDetail', detail_content)

    def test_database_catalog_protection_and_zero_test_sos(self):
        app = create_app()
        with app.app_context():
            with get_db_cursor() as cursor:
                # 1. Product Catalog Protection (Rule 1)
                cursor.execute("SELECT COUNT(*) AS cnt FROM products WHERE is_active = TRUE;")
                prod_row = cursor.fetchone()
                self.assertGreater(prod_row['cnt'], 0, "Active products must exist in database")

                # 2. Check for lingering test orders
                cursor.execute("""
                    SELECT order_number, remarks FROM sales_orders 
                    WHERE order_number ILIKE '%test%' 
                       OR order_number ILIKE '%temp%' 
                       OR remarks ILIKE '%test%';
                """)
                test_sos = cursor.fetchall()
                self.assertEqual(len(test_sos), 0, f"Found lingering test sales orders: {[r['order_number'] for r in test_sos]}")

if __name__ == '__main__':
    unittest.main()
