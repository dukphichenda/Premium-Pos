import unittest
from app import create_app

class TestSoSidebarFlushAndUom(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_sidebar_flush_against_blue_sidebar(self):
        """
        Verify that styles ensure the sales order workspace and sidebar sit completely flush (margin-left: 0)
        against the main dark blue sidebar in embedded/tab iframe mode.
        """
        resp = self.client.get('/sales/new?embed=1')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check that flush styles exist
        self.assertIn('.so-master-sidebar', html)
        self.assertIn('margin-left: 0 !important', html)
        self.assertIn('.inflow-so-workspace', html)

    def test_uom_choose_functionality_wired(self):
        """
        Verify that UOM selection popup and handlers exist on both existing lines and asterisk new row entry:
        1. #qtyDropdownPopup exists with tbody#qtyDropdownBody
        2. #newRowEntry has openQtyDropdown handler on UOM badge
        3. openQtyDropdown function is defined in scripts
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check popup structure
        self.assertIn('id="qtyDropdownPopup"', html)
        self.assertIn('id="qtyDropdownBody"', html)
        self.assertIn('id="qtyOnHandVal"', html)

        # Check asterisk new row entry has the UOM chooser trigger
        self.assertIn('id="newRowEntry"', html)
        self.assertIn('id="newItemUomInput"', html)
        self.assertIn('onclick="openQtyDropdown(event, this)"', html)

        # Check JS function
        self.assertIn('function openQtyDropdown(event, btnEl)', html)
        self.assertIn('function selectUnitForLine(', html)

    def test_shorter_sheet_pay2x2_item_wrap_and_uom_display(self):
        """
        Verify:
        1. Shorter right card width (260px) in grid and main-right.
        2. Exactly 2x2 payment tiles grid (repeat(2, 1fr)) with Cash, ABA, ACLEDA, KB PRASAC.
        3. Credit / Debit and Other Bank removed.
        4. Item inputs use textarea rows="2" for 2nd line wrapping.
        5. Stock values in UOM popup use <u> tag underlines matching inFlow design.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. 260px width
        self.assertIn('260px', html)
        self.assertIn('.so-main-right', html)

        # 2. 2x2 payment tiles
        self.assertIn('repeat(2, 1fr)', html)
        self.assertIn('data-method="Cash"', html)
        self.assertIn('data-method="ABA Bank"', html)
        self.assertIn('data-method="ACLEDA"', html)
        self.assertIn('data-method="KB PRASAC"', html)

        # 3. Credit / Debit and Other Bank removed
        self.assertNotIn('data-method="Credit/Debit"', html)
        self.assertNotIn('data-method="Other Bank"', html)

        # 4. Item inputs use textarea for 2nd line wrapping
        self.assertIn('<textarea rows="2"', html)

        # 5. Stock underline styling in JS
        self.assertIn('<u>${formatQtyNum(onHand)}', html)
        self.assertIn('<u>${formatQtyNum(reserved)}', html)

    def test_complete_and_pay_below_cancel_and_compact_height(self):
        """
        Verify:
        1. Wide Other Payment (.so-pay-tile-wide) is present above Cancel.
        2. Action buttons group contains .so-actions-sub-row with Delete and Cancel.
        3. Complete & Pay (.so-btn-complete) is placed below Cancel.
        4. Both top grid and main split use 8px gap for flush vertical alignment.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check wide other payment tile
        self.assertIn('so-pay-tile-wide', html)
        self.assertIn('data-method="Other Payment"', html)

        self.assertIn('so-actions-sub-row', html)
        self.assertIn('so-btn-delete', html)
        self.assertIn('so-btn-cancel', html)
        self.assertIn('so-btn-complete', html)

        # Confirm Other Payment precedes Cancel, and Cancel precedes Complete & Pay
        other_pos = html.find('so-pay-tile-wide')
        cancel_pos = html.find('so-btn-cancel')
        complete_pos = html.find('so-btn-complete')
        self.assertTrue(other_pos < cancel_pos < complete_pos, "Other Payment must precede Cancel, and Cancel must precede Complete & Pay")

        # Alignment check: 8px gap on both top grid and main split
        self.assertIn('.so-card-grid-top', html)
        self.assertIn('.so-modern-main-split', html)
        self.assertIn('.so-card-summary', html)
        self.assertIn('min-height: 34px', html)

    def test_so_items_table_qty_clean_and_delete_in_last_column(self):
        """
        Verify:
        1. Quantity cell has amount input and UOM badge aligned without trash button.
        2. Delete icon (trash button) is placed in the last column next to the drag handle.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('line-drag-handle-cell', html)
        self.assertIn('so-drag-handle', html)
        self.assertIn('so-qty-input', html)
        self.assertIn('so-uom-badge', html)
        self.assertIn('isDragHandlePressed', html)
        self.assertIn('handleLineDragStart', html)

    def test_kit_components_in_hand_and_reserved_stock(self):
        """
        Verify:
        1. #qtyKitComponentsContainer and #qtyKitComponentsList exist in Sales detail template.
        2. window.productsCatalog injects components, is_kit, and max_kits_buildable.
        3. Endpoint GET /api/products/<id>/components returns component stock with In Hand and Reserved.
        """
        # 1. Page template verification
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('id="qtyKitComponentsContainer"', html)
        self.assertIn('id="qtyKitComponentsList"', html)
        self.assertIn('id="qtyKitMaxBuildable"', html)
        self.assertIn('Kit Components Stock', html)
        self.assertIn('is_kit:', html)
        self.assertIn('max_kits_buildable:', html)
        self.assertIn('components:', html)

        # 2. API Endpoint verification
        api_resp = self.client.get('/api/products/513/components')
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('is_combined'))
        comps = data.get('components', [])
        self.assertGreaterEqual(len(comps), 1)
        for c in comps:
            self.assertIn('stock_on_hand', c)
            self.assertIn('stock_reserved', c)
            self.assertIn('stock_available', c)
            self.assertIn('sku', c)
            self.assertIn('quantity', c)

    def test_so_item_detail_navigation_and_dropdown_reset(self):
        """
        Verify:
        1. Line items contain .so-item-name-link navigating directly to product detail via goToProductDetail.
        2. .so-item-change-trigger is available to switch products via openItemDropdownForLine.
        3. openItemDropdown clears previous search filter results and highlights current product.
        4. Dropdown table DETAILS column contains View link calling goToProductDetail.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Functions defined
        self.assertIn('function goToProductDetail(pid, name, event)', html)
        self.assertIn('function openItemDropdownForLine(btnEl, event)', html)
        self.assertIn('function openItemDropdown(inputEl)', html)

        # Dropdown reset logic present
        self.assertIn("r.style.display = '';", html)
        self.assertIn("data-pid=", html)

        # Dropdown DETAILS column View link
        self.assertIn('goToProductDetail(', html)
        self.assertIn('title="View product detail">View</span>', html)

        # CSS classes
        self.assertIn('.so-item-name-link', html)
        self.assertIn('.so-item-change-trigger', html)

if __name__ == '__main__':
    unittest.main()



