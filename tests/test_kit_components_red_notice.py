import unittest
from app import create_app
from routes.sales_orders import _get_product_components_map, _get_drawer_and_metadata

class TestKitComponentsRedNotice(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_product_components_map_contains_stock_fields(self):
        """Verify _get_product_components_map includes stock_on_hand, stock_reserved, stock_available"""
        with self.app.app_context():
            comp_map = _get_product_components_map()
            self.assertIsInstance(comp_map, dict)
            # Find any product with components (e.g. PID 513 or others)
            for pid, comps in comp_map.items():
                self.assertTrue(len(comps) > 0)
                for c in comps:
                    self.assertIn('sku', c)
                    self.assertIn('name', c)
                    self.assertIn('quantity', c)
                    self.assertIn('uom', c)
                    self.assertIn('stock_on_hand', c)
                    self.assertIn('stock_reserved', c)
                    self.assertIn('stock_available', c)
                break

    def test_sales_detail_html_contains_kit_panel_and_backorder_popup(self):
        """Verify sales/detail.html contains kit panel in item dropdown and backorder popup"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'
            sess['active_branch_id'] = None

        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Item Dropdown Kit Components Panel (where user drew the red outline)
        self.assertIn('id="itemDropdownKitPanel"', html)
        self.assertIn('id="previewKitBuildableBadge"', html)
        self.assertIn('id="previewKitComponentsList"', html)
        self.assertIn('id="previewKitNoticeBanner"', html)
        self.assertIn('Kit Components Notice', html)

        # 2. Backorder Notice Popover (floating red notice for ! badge)
        self.assertIn('id="backorderNoticePopup"', html)
        self.assertIn('id="boPopupTitle"', html)
        self.assertIn('id="boPopupSubtitle"', html)
        self.assertIn('id="boPopupAlertText"', html)
        self.assertIn('id="boPopupBody"', html)
        self.assertIn('id="boPopupFooter"', html)
        self.assertIn('id="boPopupBuildable"', html)

        # 3. JavaScript functions present
        self.assertIn('function showBackorderNotice(', html)
        self.assertIn('function closeBackorderNotice(', html)
        self.assertIn('function initBackorderNotices(', html)
        self.assertIn('updateItemDropdownPreview(', html)
        self.assertIn('initBackorderNotices();', html)

        # 4. Check for QTY in hand and Reserve labels in detail
        self.assertIn('Qty in Hand:', html)
        self.assertIn('Reserve:', html)
        self.assertIn('.inflow-backorder-badge', html)

if __name__ == '__main__':
    unittest.main()
