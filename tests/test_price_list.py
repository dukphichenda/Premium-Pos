import unittest
from app import create_app

class TestPriceList(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_inventory_flyout_has_price_list(self):
        """Verify Inventory flyout menu in base.html has Price list row."""
        resp = self.client.get('/inventory')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Price list', html)
        self.assertTrue('/price-list' in html)

    def test_price_list_page_renders(self):
        """Verify /products/price-list and /inventory/price-list return 200 and contain required controls."""
        for path in ['/products/price-list', '/inventory/price-list']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed for {path}")
            html = resp.data.decode('utf-8')

            # Page title and Khmer translation
            self.assertIn('Product Price List', html)
            self.assertIn('តារាងតម្លៃទំនិញ', html)

            # Option to show: All Products, By Category, Selected Products
            self.assertIn('id="scopeAll"', html)
            self.assertIn('id="scopeCategory"', html)
            self.assertIn('id="scopeSelected"', html)
            self.assertIn('id="categoryFilter"', html)

            # Option to Group By
            self.assertIn('id="groupByFilter"', html)
            self.assertIn('Group by:', html)
            self.assertIn('value="category"', html)
            self.assertIn('value="uom"', html)

            # PDF export button & Print
            self.assertIn('id="btnExportPdf"', html)
            self.assertIn('exportPriceListPDF()', html)
            self.assertIn('html2pdf', html)

            # Multi-select products modal / drawer
            self.assertIn('id="productPickerModal"', html)
            self.assertIn('openProductPickerModal()', html)

            # Card structure (Image 2 exact match)
            self.assertIn('pl-price-card', html)
            self.assertIn('pl-card-header-grid', html)
            self.assertIn('pl-card-upper-grid', html)
            self.assertIn('pl-card-price-hdr-grid', html)
            self.assertIn('(UNIT PRICE)', html)
            self.assertIn('(Product Detail)', html)

    def test_price_list_table_features(self):
        """Verify Table View generator, Scheme selector, UOM selector, and pack pcs sub-note."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Price List Table View Container & Elements
        self.assertIn('id="priceTableWrapper"', html)
        self.assertIn('id="priceListTable"', html)
        self.assertIn('id="priceTableBody"', html)
        self.assertIn('id="selectAllRowsChk"', html)

        # Columns in table (Stock and UOM removed per user request)
        self.assertIn('Picture', html)
        self.assertIn('Product Title', html)
        self.assertIn('Size / Spec', html)
        self.assertIn('Packaging Breakdown', html)
        self.assertIn('Unit Price', html)
        self.assertNotIn('<th style="width: 110px; text-align: center;">Stock</th>', html)
        self.assertNotIn('<th style="width: 100px; text-align: center;">UOM</th>', html)

        # Price Scheme Filter selector
        self.assertIn('id="priceSchemeFilter"', html)
        self.assertIn('Scheme:', html)

        # UOM Filter selector with pack option
        self.assertIn('id="uomFilter"', html)
        self.assertIn('value="pack"', html)
        self.assertIn('value="case"', html)
        self.assertIn('value="pcs"', html)

        # View Mode switcher [ Table | Cards ]
        self.assertIn('id="viewModeSwitcher"', html)
        self.assertIn('id="btnViewTable"', html)
        self.assertIn('id="btnViewCards"', html)

        # Generate Table Button & function
        self.assertIn('id="btnGenerateTable"', html)
        self.assertIn('generatePriceTable()', html)

        # CSV Export
        self.assertIn('exportTableToCSV()', html)

        # Pack pcs sub-detail logic and CSS
        self.assertIn('pl-table-pcs-note', html)
        self.assertIn('pcs / pack', html)

    def test_catalog_has_price_list_button(self):
        """Verify Products catalog sidebar has the Price List shortcut button."""
        resp = self.client.get('/products')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('/products/price-list', html)
        self.assertIn('Price List Table (តារាងតម្លៃទំនិញ)', html)

    def test_price_list_starts_blank_without_preselection(self):
        """Verify when opening price list page, products are not pre-selected and table starts blank."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Scope selected is active on initial load
        self.assertIn('class="pl-scope-btn active" id="scopeSelected"', html)
        self.assertIn('id="selectedCountPill">0<', html)

        # Counter shows 0 products on initial load
        self.assertIn('id="visibleCounter">Showing 0 of ', html)

        # Client-side state defaults to empty set and selected scope
        self.assertIn("let currentScope = 'selected';", html)
        self.assertIn('selectedProductIds = new Set();', html)
        self.assertNotIn('ALL_PRODUCTS_DATA.forEach(p => selectedProductIds.add(p.id));', html)

        # Empty state prompt row present
        self.assertIn('No Products Selected Yet', html)

    def test_price_list_table_pdf_export_features(self):
        """Verify Table PDF export excludes category column, has 5:4 aspect ratio product picture, robust Khmer font rendering, and supports All/Category/Selected scopes."""
        resp = self.client.get('/products/price-list')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Dropdown for PDF export in header & table view
        self.assertIn('id="plExportPdfDropdownMenu"', html)
        self.assertIn('id="plExportPdfDropdownMenuTable"', html)
        self.assertIn("handleExportPdfScope('all'", html)
        self.assertIn("handleExportPdfScope('category'", html)
        self.assertIn("handleExportPdfScope('selected'", html)

        # PDF Category Modal exists
        self.assertIn('id="plPdfCategoryModal"', html)
        self.assertIn('id="plPdfCategorySelect"', html)
        self.assertIn('confirmPdfCategoryExport()', html)

        # In Table View PDF export: No Category column in table header or rows
        pdf_table_idx = html.find("currentViewMode === 'table'")
        cards_branch_idx = html.find("Branch for Cards View PDF export")
        pdf_table_export_code = html[pdf_table_idx:cards_branch_idx]
        self.assertNotIn('>Category<', pdf_table_export_code)

        # Product picture container has width 5 and height 4 aspect ratio (90px x 72px)
        self.assertIn('aspect-ratio: 5 / 4', pdf_table_export_code)
        self.assertIn('width: 90px; height: 72px;', pdf_table_export_code)
        self.assertIn('object-fit: contain', pdf_table_export_code)

        # Robust Khmer font rendering in Table PDF: Kantumruy Pro with weight 700 and letterRendering: false
        self.assertIn("'Kantumruy Pro', 'Siemreap', sans-serif !important", pdf_table_export_code)
        self.assertIn('letterRendering: false', pdf_table_export_code)

        # 9 rows per page
        self.assertIn('ROWS_PER_PAGE = 9', pdf_table_export_code)

if __name__ == '__main__':
    unittest.main()
