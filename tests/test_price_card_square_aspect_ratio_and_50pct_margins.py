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

        # .inflow-modern-middle-grid: 50% height split for picture with description
        self.assertRegex(css, r'\.inflow-modern-middle-grid\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-middle-grid\s*\{[^}]*height:\s*calc\(50%\s*-\s*25px\)\s*!important;')

        # .inflow-modern-price-wrap: 50% height split for table below
        self.assertRegex(css, r'\.inflow-modern-price-wrap\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-price-wrap\s*\{[^}]*height:\s*calc\(50%\s*-\s*25px\)\s*!important;')

        # .inflow-modern-price-banner: expanded to 46px to prevent losing/clipping subtitle text (Price) and (UNIT PRICE)
        self.assertRegex(css, r'\.inflow-modern-price-banner\s*\{[^}]*height:\s*46px\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-price-banner\s*\{[^}]*min-height:\s*46px\s*!important;')

        # .inflow-modern-price-table-card & tier rows: fill bottom 50% with equal 33.333% distribution
        self.assertRegex(css, r'\.inflow-modern-price-table-card\s*\{[^}]*flex:\s*1\s+1\s+auto\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-price-table-card\s*\{[^}]*height:\s*calc\(100%\s*-\s*46px\)\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-tier-row\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-tier-row\s*\{[^}]*height:\s*33\.333%\s*!important;')

        # Enlarged typography to fit tall rows
        self.assertRegex(css, r'\.inflow-modern-qty-badge\s*\{[^}]*font-size:\s*16px\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-tier-tot\s*\{[^}]*font-size:\s*22px\s*!important;')
        self.assertRegex(css, r'\.inflow-modern-tier-unit\s*\{[^}]*font-size:\s*16\.5px\s*!important;')

    def test_price_list_html_modern_card_50_50_height_split(self):
        with open(self.price_list_html, 'r', encoding='utf-8') as f:
            pl = f.read()

        # .pl-price-card.modern aspect ratio 1:1 square
        self.assertRegex(pl, r'\.pl-price-card\.modern\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')

        # .pl-modern-middle-grid: 50% height for picture with description
        self.assertRegex(pl, r'\.pl-modern-middle-grid\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-middle-grid\s*\{[^}]*height:\s*calc\(50%\s*-\s*25px\)\s*!important;')

        # .pl-modern-price-wrap: 50% height for table below
        self.assertRegex(pl, r'\.pl-modern-price-wrap\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-price-wrap\s*\{[^}]*height:\s*calc\(50%\s*-\s*25px\)\s*!important;')

        # .pl-modern-price-banner: expanded to 46px to avoid clipping text
        self.assertRegex(pl, r'\.pl-modern-price-banner\s*\{[^}]*height:\s*46px\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-price-banner\s*\{[^}]*min-height:\s*46px\s*!important;')

        # .pl-modern-price-table-card & tier rows: fill bottom 50%
        self.assertRegex(pl, r'\.pl-modern-price-table-card\s*\{[^}]*flex:\s*1\s+1\s+auto\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-price-table-card\s*\{[^}]*height:\s*calc\(100%\s*-\s*46px\)\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-tier-row\s*\{[^}]*flex:\s*1\s+1\s+0\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-tier-row\s*\{[^}]*height:\s*33\.333%\s*!important;')

        # Enlarged typography
        self.assertRegex(pl, r'\.pl-modern-qty-badge\s*\{[^}]*font-size:\s*16px\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-tier-tot\s*\{[^}]*font-size:\s*22px\s*!important;')
        self.assertRegex(pl, r'\.pl-modern-tier-unit\s*\{[^}]*font-size:\s*16\.5px\s*!important;')

        # Stage enforces 680x680 square
        self.assertIn('id="plBatchExportStage" style="width: 680px; height: 680px;', pl)
        self.assertIn("cardEl.style.height = '680px';", pl)

    def test_detail_and_catalog_html_modern_price_cards(self):
        """Verify embedded styles in detail.html and catalog.html ensure square 1:1 and no squashed view."""
        with open(self.detail_html, 'r', encoding='utf-8') as f:
            det = f.read()
        self.assertRegex(det, r'#printablePriceCardDetail\.modern\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')
        self.assertRegex(det, r'#printablePriceCardDetail\.modern\s*\{[^}]*display:\s*flex\s*!important;')
        self.assertRegex(det, r'\.inflow-modern-price-banner\s*\{[^}]*height:\s*46px\s*!important;')
        self.assertRegex(det, r'\.inflow-modern-tier-tot\s*\{[^}]*font-size:\s*22px\s*!important;')

        with open(self.catalog_html, 'r', encoding='utf-8') as f:
            cat = f.read()
        self.assertRegex(cat, r'#printablePriceCard\.modern\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1\s*!important;')
        self.assertRegex(cat, r'#printablePriceCard\.modern\s*\{[^}]*display:\s*flex\s*!important;')
        self.assertRegex(cat, r'\.inflow-modern-price-banner\s*\{[^}]*height:\s*46px\s*!important;')
        self.assertRegex(cat, r'\.inflow-modern-tier-tot\s*\{[^}]*font-size:\s*22px\s*!important;')

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
