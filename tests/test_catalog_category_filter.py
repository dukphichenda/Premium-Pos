import unittest
import os
import re

class TestCatalogCategoryFilter(unittest.TestCase):
    def setUp(self):
        catalog_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(catalog_path, 'r', encoding='utf-8') as f:
            self.html = f.read()

    def test_category_filter_at_top_of_dropdown(self):
        # Locate the dropdown
        dropdown_idx = self.html.find('id="catFilterDropdown"')
        self.assertNotEqual(dropdown_idx, -1, "Dropdown #catFilterDropdown should exist")

        cat_section_idx = self.html.find('<!-- Category Section', dropdown_idx)
        sort_section_idx = self.html.find('<!-- Sort & Ranking Section', dropdown_idx)
        sales_section_idx = self.html.find('<!-- Sales Filter Section', dropdown_idx)
        stock_section_idx = self.html.find('<!-- Stock Filter Section', dropdown_idx)

        self.assertNotEqual(cat_section_idx, -1, "Category section should exist inside dropdown")
        self.assertNotEqual(sort_section_idx, -1, "Sort section should exist inside dropdown")
        self.assertNotEqual(sales_section_idx, -1, "Sales section should exist inside dropdown")
        self.assertNotEqual(stock_section_idx, -1, "Stock section should exist inside dropdown")

        # Category section must appear before Sort, Sales, and Stock
        self.assertLess(cat_section_idx, sort_section_idx, "Category filter must be placed before Sort & Ranking")
        self.assertLess(cat_section_idx, sales_section_idx, "Category filter must be placed before Sales Filter")
        self.assertLess(cat_section_idx, stock_section_idx, "Category filter must be placed before Stock Filter")

    def test_category_search_controls(self):
        self.assertIn('id="catFilterSearchInput"', self.html)
        self.assertIn('oninput="filterCategoryOptions(this.value)"', self.html)
        self.assertIn('id="catFilterSearchClearBtn"', self.html)
        self.assertIn('clearCategorySearch', self.html)
        self.assertIn('id="catFilterNoMatchMsg"', self.html)

    def test_category_search_css_important(self):
        # Verify CSS handles display: none !important for category filter options
        self.assertIn('#catFilterCategoryList .cat-filter-opt.is-cat-hidden', self.html)
        self.assertIn('display: none !important;', self.html)

    def test_filter_category_options_js(self):
        # Verify JS function applies display !important and class is-cat-hidden
        self.assertIn("function filterCategoryOptions(q)", self.html)
        self.assertIn("r.style.setProperty('display', 'none', 'important')", self.html)
        self.assertIn("r.classList.add('is-cat-hidden')", self.html)

if __name__ == '__main__':
    unittest.main()
