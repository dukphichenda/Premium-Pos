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

if __name__ == '__main__':
    unittest.main()
