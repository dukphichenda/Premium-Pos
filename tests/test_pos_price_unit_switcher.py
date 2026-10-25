import unittest
import os
import json
from app import create_app
from database import query_one, query_all

class TestPosPriceUnitSwitcher(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_pos_template_has_unit_switcher_controls_and_functions(self):
        """Verify templates/branches/pos.html includes the Price Mode buttons and JavaScript functions."""
        pos_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'branches', 'pos.html')
        with open(pos_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check buttons exist in subheader
        self.assertIn('id="segPriceUnit-Case"', content)
        self.assertIn('id="segPriceUnit-Pack"', content)
        self.assertIn('id="segPriceUnit-Pcs"', content)
        self.assertIn("switchPriceUnitMode('Case')", content)
        self.assertIn("switchPriceUnitMode('Pack')", content)
        self.assertIn("switchPriceUnitMode('Pcs')", content)

        # Check Bills mode badge
        self.assertIn('id="posBillsActiveModeBadge"', content)

        # Check JavaScript functions
        self.assertIn('function calculateProductPriceForUnit(p, unitMode, schemeId)', content)
        self.assertIn('function switchPriceUnitMode(mode)', content)
        self.assertIn('function refreshGridPrices()', content)
        self.assertIn('let currentPriceUnitMode', content)

    def test_pos_route_includes_uom_in_products(self):
        """Verify routes/branches.py queries p.uom in POS product catalog."""
        branches_py_path = os.path.join(os.path.dirname(__file__), '..', 'routes', 'branches.py')
        with open(branches_py_path, 'r', encoding='utf-8') as f:
            py_content = f.read()

        self.assertIn("COALESCE(p.uom, 'pcs.') as uom", py_content)

    def test_pos_page_renders_with_branch_and_products(self):
        """Verify GET /branches/<id>/pos renders successfully with status code 200."""
        with self.app.test_request_context():
            branch = query_one("SELECT id FROM branches LIMIT 1")
            if not branch:
                self.skipTest("No branch found in database")
            bid = branch['id']

            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'admin'
                sess['role'] = 'main_admin'
                sess['branch_id'] = bid

            res = self.client.get(f'/branches/{bid}/pos')
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn('segPriceUnit-Case', html)
            self.assertIn('segPriceUnit-Pack', html)
            self.assertIn('segPriceUnit-Pcs', html)
            self.assertIn('posBillsActiveModeBadge', html)

if __name__ == '__main__':
    unittest.main()
