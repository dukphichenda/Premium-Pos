import unittest
import os
import re

class TestPriceCardSquareAspectRatioAndMargins(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.styles_css = os.path.join(self.base_dir, 'static', 'css', 'styles.css')
        self.catalog_html = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')
        self.detail_html = os.path.join(self.base_dir, 'templates', 'products', 'detail.html')
        self.price_list_html = os.path.join(self.base_dir, 'templates', 'products', 'price_list.html')
        self.workspace_html = os.path.join(self.base_dir, 'templates', 'products', '_catalog_workspace_main.html')

    def test_css_spec_card_has_square_aspect_ratio_and_halved_margin(self):
        with open(self.styles_css, 'r', encoding='utf-8') as f:
            css = f.read()

        # 1:1 square aspect ratio on .inflow-spec-card
        self.assertIn('.inflow-spec-card {', css)
        self.assertRegex(css, r'\.inflow-spec-card\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')
        self.assertRegex(css, r'\.inflow-spec-card\s*\{[^}]*margin:\s*8px\s+auto;')

        # is-exporting square dimensions
        self.assertRegex(css, r'\.inflow-spec-card\.is-exporting\s*\{[^}]*width:\s*680px\s*!important;')
        self.assertRegex(css, r'\.inflow-spec-card\.is-exporting\s*\{[^}]*height:\s*680px\s*!important;')
        self.assertRegex(css, r'\.inflow-spec-card\.is-exporting\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')

    def test_css_modern_price_card_square_and_halved_margins(self):
        with open(self.styles_css, 'r', encoding='utf-8') as f:
            css = f.read()

        # .inflow-spec-card.modern padding reduced by 50% (from 16px to 8px 10px) and aspect-ratio 1 / 1
        self.assertRegex(css, r'\.inflow-spec-card\.modern\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')
        self.assertRegex(css, r'\.inflow-spec-card\.modern\s*\{[^}]*padding:\s*8px\s+10px\s*!important;')

        # .inflow-modern-middle-grid margins & gaps halved by 50% (from 12px to 6px)
        self.assertRegex(css, r'\.inflow-modern-middle-grid\s*\{[^}]*gap:\s*6px\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-middle-grid\s*\{[^}]*margin-top:\s*6px\s*!important;')

        # .inflow-modern-price-wrap margin halved by 50% (from 12px to 6px)
        self.assertRegex(css, r'\.inflow-modern-price-wrap\s*\{[^}]*margin-top:\s*6px\s*!important;')

        # .inflow-modern-specs-box padding halved by 50%
        self.assertRegex(css, r'\.inflow-modern-specs-box\s*\{[^}]*padding:\s*6px\s+10px\s*!important;')

        # .inflow-modern-header padding halved by 50%
        self.assertRegex(css, r'\.inflow-modern-header\s*\{[^}]*padding:\s*6px\s+12px\s*!important;')

    def test_export_canvas_margin_halved_by_50_percent(self):
        # catalog.html
        with open(self.catalog_html, 'r', encoding='utf-8') as f:
            cat = f.read()
        self.assertIn('function addExportMarginToCanvas(sourceCanvas, marginPx = 14', cat)
        self.assertIn('addExportMarginToCanvas(canvas, 14, 3.2)', cat)

        # detail.html
        with open(self.detail_html, 'r', encoding='utf-8') as f:
            det = f.read()
        self.assertIn('function addExportMarginToCanvas(sourceCanvas, marginPx = 14', det)
        self.assertIn('addExportMarginToCanvas(canvas, 14, 3.2)', det)

        # price_list.html
        with open(self.price_list_html, 'r', encoding='utf-8') as f:
            pl = f.read()
        self.assertIn('function addExportMarginToCanvas(sourceCanvas, marginPx = 14', pl)
        self.assertIn('addExportMarginToCanvas(canvas, 14, 3.2)', pl)
        self.assertIn('addExportMarginToCanvas(canvas, 12, scale)', pl)

    def test_offscreen_export_stages_enforce_680x680_square(self):
        with open(self.catalog_html, 'r', encoding='utf-8') as f:
            cat = f.read()
        self.assertIn('id="batchPriceCardStageContainer" style="position: fixed; left: -9999px; top: 0; width: 680px; height: 680px;', cat)
        self.assertIn('id="batchPriceCardStage" style="width: 680px; height: 680px; max-width: 680px; aspect-ratio: 1 / 1;', cat)
        self.assertIn("targetCard.style.width = '680px';", cat)
        self.assertIn("targetCard.style.height = '680px';", cat)
        self.assertIn("targetCard.style.aspectRatio = '1 / 1';", cat)

        with open(self.detail_html, 'r', encoding='utf-8') as f:
            det = f.read()
        self.assertIn('id="batchPriceCardStageContainerDetail" style="position: fixed; left: -9999px; top: 0; width: 680px; height: 680px;', det)
        self.assertIn('id="batchPriceCardStageDetail" style="width: 680px; height: 680px; max-width: 680px; aspect-ratio: 1 / 1;', det)
        self.assertIn("targetCard.style.width = '680px';", det)
        self.assertIn("targetCard.style.height = '680px';", det)
        self.assertIn("targetCard.style.aspectRatio = '1 / 1';", det)

    def test_database_test_orders_and_catalog_protection(self):
        """Verify strict rule compliance: zero test sales orders and product catalog integrity."""
        from database import get_db_cursor
        with get_db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM sales_orders so
                LEFT JOIN customers c ON c.id = so.customer_id
                WHERE so.order_number ILIKE '%%TEST%%' 
                   OR so.order_number ILIKE '%%TEMP%%'
                   OR c.name ILIKE '%%TEST%%';
            """)
            so_count = cur.fetchone()['count']
            self.assertEqual(so_count, 0, f"Found {so_count} leftover test sales orders in database!")

            # Verify products table exists and has valid count
            cur.execute("SELECT COUNT(*) as count FROM products WHERE is_active = TRUE;")
            prod_count = cur.fetchone()['count']
            self.assertGreater(prod_count, 0, "Products table must have active products!")

if __name__ == '__main__':
    unittest.main()
