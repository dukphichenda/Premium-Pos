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

if __name__ == '__main__':
    unittest.main()
