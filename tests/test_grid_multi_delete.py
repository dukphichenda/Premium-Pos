import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, execute, execute_returning_id

class TestGridMultiDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def test_po_detail_has_multi_select_and_cross_delete(self):
        """Verify PO detail template has tick boxes removed while keeping 1-by-1 cross delete and line operations."""
        po = query_one("SELECT id FROM purchase_orders ORDER BY id DESC LIMIT 1")
        if not po:
            self.skipTest("No purchase order found in database.")
        
        resp = self.client.get(f"/purchases/{po['id']}")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check tick box is removed
        self.assertNotIn('id="masterSelectAllPoLines"', html)
        self.assertNotIn('class="line-select-chk"', html)

        # Check cross delete button and operations remain
        self.assertIn('class="line-delete-cross-btn"', html)
        self.assertIn('deleteSpecificPoLine', html)
        self.assertIn('deleteSelectedPoLine', html)

    def test_so_detail_has_multi_select_and_cross_delete(self):
        """Verify SO detail template has tick boxes removed while keeping line operations."""
        so = query_one("SELECT id FROM sales_orders WHERE status != 'PAID' ORDER BY id DESC LIMIT 1")
        if not so:
            so = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not so:
            self.skipTest("No sales order found in database.")

        resp = self.client.get(f"/sales/{so['id']}")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check tick box is removed
        self.assertNotIn('id="masterSelectAllSoLines"', html)
        self.assertNotIn('class="line-select-chk"', html)

        # Check JS function presence
        self.assertIn('deleteSpecificSoLine', html)
        self.assertIn('deleteSelectedLine', html)

    def test_css_has_line_delete_cross_btn_styles(self):
        """Verify static/css/styles.css contains the styles for cross delete button and row selection."""
        with open("static/css/styles.css", "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".line-delete-cross-btn", css)
        self.assertIn(".inflow-selector-cell-content", css)
        self.assertIn(".inflow-master-chk", css)
        self.assertIn(".is-selected-row", css)
        self.assertIn(".is-active-row", css)

if __name__ == '__main__':
    unittest.main()
