import unittest
import os
import re

class TestProductCatalog(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_html_path = os.path.join(self.base_dir, 'templates', 'base.html')
        self.catalog_template_path = os.path.join(self.base_dir, 'templates', 'products', 'product_catalog.html')
        self.routes_products_path = os.path.join(self.base_dir, 'routes', 'products.py')
        self.catalog_editor_path = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')

        with open(self.base_html_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()

        with open(self.catalog_template_path, 'r', encoding='utf-8') as f:
            self.catalog_html = f.read()

        with open(self.routes_products_path, 'r', encoding='utf-8') as f:
            self.routes_code = f.read()

    def test_inventory_flyout_has_product_catalog_below_price_list(self):
        """Verify Inventory flyout menu has Product Catalog row immediately below Price list."""
        inv_idx = self.base_html.find('id="flyout-inventory"')
        self.assertNotEqual(inv_idx, -1, "#flyout-inventory should exist in base.html")

        # Find Price list inside Inventory flyout
        price_list_idx = self.base_html.find('Price list', inv_idx)
        self.assertNotEqual(price_list_idx, -1, "'Price list' row should exist in inventory flyout")

        # Find Product Catalog inside Inventory flyout
        catalog_idx = self.base_html.find('Product Catalog', price_list_idx)
        self.assertNotEqual(catalog_idx, -1, "'Product Catalog' row should exist below 'Price list'")

        # Ensure Product Catalog links to products.product_catalog_view
        snippet = self.base_html[price_list_idx:catalog_idx + 100]
        self.assertIn("url_for('products.product_catalog_view')", snippet)

        # Check Khmer translation mapping
        self.assertIn("'Product Catalog': 'កាតាឡុកទំនិញ'", self.base_html)

    def test_catalog_sidebar_tool_button(self):
        """Verify Products catalog sidebar has the shortcut button to Product Catalog."""
        with open(self.catalog_editor_path, 'r', encoding='utf-8') as f:
            editor_html = f.read()
        self.assertIn("url_for('products.product_catalog_view')", editor_html)
        self.assertIn('Product Catalog (កាតាឡុកទំនិញ)', editor_html)

    def test_product_catalog_route_implementation(self):
        """Verify routes/products.py has product_catalog_view querying active products by category."""
        self.assertIn("def product_catalog_view():", self.routes_code)
        self.assertIn("@products_bp.route('/inventory/product-catalog')", self.routes_code)
        self.assertIn("@products_bp.route('/products/product-catalog')", self.routes_code)

        # Check that it filters active products only
        self.assertIn("WHERE p.is_active = TRUE", self.routes_code)

        # Check that it arranges products by category
        self.assertIn("category_groups", self.routes_code)
        self.assertIn("spreads", self.routes_code)

    def test_product_catalog_template_screenshot_match(self):
        """Verify product_catalog.html matches Screenshot 2 design without prices."""
        # Teal Banner & Collection Of Title
        self.assertIn('Collection Of {{ cat.name }}', self.catalog_html)
        self.assertIn('cat-teal-banner', self.catalog_html)

        # Booklet spread structure (Left Page & Right Page)
        self.assertIn('booklet-spread', self.catalog_html)
        self.assertIn('page-left', self.catalog_html)
        self.assertIn('page-right', self.catalog_html)
        self.assertIn('Exclusive Collection', self.catalog_html)

        # Contains product Image, SKU, Name, and Detail
        self.assertIn('cat-thumb-img', self.catalog_html)
        self.assertIn('cat-item-name', self.catalog_html)
        self.assertIn('cat-sku-tag', self.catalog_html)
        self.assertIn('cat-item-detail', self.catalog_html)

        # CRITICAL: Verify NO price displayed on product cards
        self.assertNotIn('Buy Now', self.catalog_html)
        self.assertNotIn('unit_price', self.catalog_html)
        self.assertNotIn('tier_price', self.catalog_html)
        self.assertNotIn('UNIT PRICE', self.catalog_html)
        self.assertNotIn('retail_price', self.catalog_html)

        # Verify Search, Category Filter, and View Switcher
        self.assertIn('id="catalogSearchInput"', self.catalog_html)
        self.assertIn('class="catalog-categories-bar"', self.catalog_html)
        self.assertIn('switchCatalogView', self.catalog_html)
        self.assertIn('window.print()', self.catalog_html)

    def test_khmer_category_and_collection_title(self):
        """Verify Khmer category mapping and collection title banner."""
        # Routes check
        self.assertIn('CATEGORY_KHMER_MAP', self.routes_code)
        self.assertIn('_get_category_khmer', self.routes_code)
        self.assertIn('cat.khmer_name', self.catalog_html)
        # Banner check
        self.assertIn('បណ្តុំផលិតផល {{ cat.khmer_name }}', self.catalog_html)
        self.assertIn('Collection Of {{ cat.name }}', self.catalog_html)
        # Category pills check
        self.assertIn('{{ cat.khmer_name }}', self.catalog_html)

    def test_a4_paper_layout_and_5_item_chunking(self):
        """Verify A4 Paper layout: exactly 5 products per page (1 column, 1 row per product) in 210mm x 297mm portrait."""
        # Routes 5-item chunking
        self.assertIn('chunk_size = 5', self.routes_code)
        self.assertIn('page_items', self.routes_code)
        self.assertIn('a4_pages', self.routes_code)

        # Template A4 structure (1 column, 1 row per product)
        self.assertIn('class="a4-sheet booklet-spread"', self.catalog_html)
        self.assertIn('class="a4-products-list', self.catalog_html)
        self.assertIn('class="a4-product-row', self.catalog_html)
        self.assertIn('page.page_items', self.catalog_html)

        # Print CSS A4 Portrait (210mm x 297mm)
        self.assertIn('size: 210mm 297mm;', self.catalog_html)
        self.assertIn('page-break-after: always', self.catalog_html)

    def test_product_size_extraction_and_display(self):
        """Verify product size is extracted and displayed in product details."""
        # Route extractors
        self.assertIn('_extract_product_size', self.routes_code)
        self.assertIn('_extract_product_packaging', self.routes_code)
        self.assertIn('size_display', self.routes_code)

        # Template size display
        self.assertIn('size_display', self.catalog_html)
        self.assertIn('ទំហំ', self.catalog_html)

if __name__ == '__main__':
    unittest.main()
