import unittest
import os
import re

class TestProductCatalogToolbarAndSearch(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.catalog_path = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')

    def test_catalog_toolbar_reordering(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            html = f.read()

        # Find toolbar
        tb_start = html.find('class="inflow-catalog-sidebar-toolbar"')
        self.assertNotEqual(tb_start, -1, "Sidebar toolbar must exist")
        tb_end = html.find('</div>', tb_start)
        toolbar_snippet = html[tb_start:html.find('<!-- Wide Search Bar', tb_start)]

        # Verify buttons order in toolbar:
        # 1. merge_duplicates_view
        # 2. price_list_view
        # 3. inflow-cat-filter-wrapper (Filters in the middle)
        # 4. product_catalog_view
        # 5. new_product
        # 6. btnMinimizeProductSidebar
        idx_merge = toolbar_snippet.find('merge_duplicates_view')
        idx_price = toolbar_snippet.find('price_list_view')
        idx_filter = toolbar_snippet.find('inflow-cat-filter-wrapper')
        idx_catalog = toolbar_snippet.find('product_catalog_view')
        idx_new = toolbar_snippet.find('new_product')
        idx_minimize = toolbar_snippet.find('btnMinimizeProductSidebar')

        self.assertNotEqual(idx_merge, -1, "Merge duplicates button must exist in toolbar")
        self.assertNotEqual(idx_price, -1, "Price list button must exist in toolbar")
        self.assertNotEqual(idx_filter, -1, "Filter wrapper must exist in toolbar")
        self.assertNotEqual(idx_catalog, -1, "Product catalog button must exist in toolbar")
        self.assertNotEqual(idx_new, -1, "New product button must exist in toolbar")
        self.assertNotEqual(idx_minimize, -1, "Minimize sidebar button must exist in toolbar")

        # Verify order: merge < price < filter < catalog < new < minimize
        self.assertTrue(idx_merge < idx_price < idx_filter < idx_catalog < idx_new < idx_minimize,
                        "Filter must be positioned in the middle between left buttons and right buttons")

        # Verify search icon is NOT inside the toolbar buttons
        self.assertNotIn('catSearchToggle', toolbar_snippet, "Search icon toggle should not be in the top toolbar")

    def test_wide_search_bar_below_filter(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            html = f.read()

        tb_pos = html.find('class="inflow-catalog-sidebar-toolbar"')
        search_pos = html.find('id="catSearchBoxWrapper"')
        sort_pos = html.find('id="catSortBarWrapper"')

        self.assertNotEqual(tb_pos, -1)
        self.assertNotEqual(search_pos, -1)
        self.assertNotEqual(sort_pos, -1)

        # Search box must be below toolbar and above sort bar
        self.assertTrue(tb_pos < search_pos < sort_pos,
                        "Search bar must be located below the toolbar/filter and above the sort bar")

        # Search box must be permanently displayed (style="display: block;")
        search_snippet = html[search_pos:search_pos + 800]
        self.assertIn('display: block;', search_snippet)
        self.assertNotIn('display: none;', search_snippet)
        self.assertIn('id="catSearchInput"', search_snippet)

    def test_product_sort_toggle_and_dropdown(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            html = f.read()

        # catSortBar must trigger toggleCatalogSortDirection
        self.assertIn('id="catSortBar"', html)
        self.assertIn('onclick="toggleCatalogSortDirection(event)"', html)

        # cat-sort-quick-trigger must trigger toggleSortDropdown
        self.assertIn('class="cat-sort-quick-trigger"', html)
        self.assertIn('onclick="toggleSortDropdown(event)"', html)

        # toggleCatalogSortDirection function must be defined
        self.assertIn('function toggleCatalogSortDirection', html)

    def test_all_nav_links_have_handlers(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            html = f.read()

        tb_snippet = html[html.find('class="inflow-catalog-sidebar-toolbar"'):html.find('<!-- Wide Search Bar')]
        self.assertIn('handleNavClick(event, this.href)', tb_snippet)

if __name__ == '__main__':
    unittest.main()
