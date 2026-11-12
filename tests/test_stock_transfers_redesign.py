import unittest
import os
import json
from app import create_app
from database import query_all, query_one, get_db_cursor

class StockTransfersRedesignTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

    def test_transfers_list_view_renders_kpis_and_actions(self):
        """Verify /inventory/transfers renders summary cards, filters, and New Transfer button."""
        res = self.client.get('/inventory/transfers')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Inter-Warehouse Stock Transfers', html)
        self.assertIn('+ New Stock Transfer', html)
        self.assertIn('/inventory/transfers/new', html)
        self.assertIn('Total Transfers', html)
        self.assertIn('Draft Requests', html)
        self.assertIn('Completed Transfers', html)
        self.assertIn('Total Units Transferred', html)
        # Check old modal is removed
        self.assertNotIn('id="newTransferModal"', html)

    def test_new_transfer_form_renders_full_editor_and_search_popup(self):
        """Verify /inventory/transfers/new renders the multi-product editor matching stock adjustment."""
        res = self.client.get('/inventory/transfers/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Document Header
        self.assertIn('Stock Transfer Number', html)
        self.assertIn('id="trfNumberInput"', html)
        self.assertIn('id="trfFromLocationSelect"', html)
        self.assertIn('id="trfToLocationSelect"', html)
        self.assertIn('id="trfDateInput"', html)
        self.assertIn('id="trfNotesInput"', html)

        # Products Table & Bottom Search Row
        self.assertIn('id="trfProductsTable"', html)
        self.assertIn('id="trfNewRowEntry"', html)
        self.assertIn('id="trfProductLiveSearch"', html)
        self.assertIn('placeholder="Type to add item..."', html)

        # Floating Dropdown popup (Matching Image 2)
        self.assertIn('id="trfLiveSearchResults"', html)
        self.assertIn('class="inflow-item-dropdown-popup"', html)

        # Action buttons
        self.assertIn('Save Draft', html)
        self.assertIn('Complete Transfer', html)
        self.assertIn('trfHistorySidebar', html)

    def test_save_transfer_draft_does_not_modify_inventory(self):
        """Verify saving a transfer request as DRAFT creates records but leaves inventory untouched."""
        # Find 2 distinct warehouses and 1 product
        locs = query_all("SELECT id FROM locations WHERE is_active = TRUE ORDER BY id ASC LIMIT 2")
        self.assertGreaterEqual(len(locs), 2, "Need at least 2 active locations for transfer test")
        from_loc = locs[0]['id']
        to_loc = locs[1]['id']

        prod = query_one("SELECT id, sku FROM products ORDER BY id ASC LIMIT 1")
        self.assertIsNotNone(prod, "Need at least 1 product")
        pid = prod['id']

        # Get initial stock at source and destination
        src_inv_before = query_one("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s", (pid, from_loc))
        src_qty_before = float(src_inv_before['qty']) if src_inv_before else 0.0

        dest_inv_before = query_one("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s", (pid, to_loc))
        dest_qty_before = float(dest_inv_before['qty']) if dest_inv_before else 0.0

        payload = {
            'transfer_number': 'TRF-TEST-DRAFT-01',
            'from_location_id': from_loc,
            'to_location_id': to_loc,
            'transfer_date': '2026-11-12',
            'notes': 'Test Automated Draft Transfer',
            'status': 'DRAFT',
            'lines': [
                {
                    'product_id': pid,
                    'quantity': 5,
                    'uom': 'pcs.',
                    'uom_factor': 1.0,
                    'source_on_hand': src_qty_before,
                    'source_available': src_qty_before
                }
            ]
        }

        res = self.client.post('/inventory/transfers/save', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        trf_id = data['transfer_id']

        # Verify transfer saved in DB as DRAFT
        saved_trf = query_one("SELECT * FROM stock_transfers WHERE id = %s", (trf_id,))
        self.assertEqual(saved_trf['status'], 'DRAFT')

        # Verify inventory was NOT changed
        src_inv_after = query_one("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s", (pid, from_loc))
        src_qty_after = float(src_inv_after['qty']) if src_inv_after else 0.0
        self.assertEqual(src_qty_before, src_qty_after, "Draft transfer must not touch source inventory")

        dest_inv_after = query_one("SELECT COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s", (pid, to_loc))
        dest_qty_after = float(dest_inv_after['qty']) if dest_inv_after else 0.0
        self.assertEqual(dest_qty_before, dest_qty_after, "Draft transfer must not touch destination inventory")

        # Clean up test transfer draft
        del_res = self.client.post(f'/inventory/transfers/{trf_id}/delete')
        self.assertEqual(del_res.status_code, 200)

    def test_adjustment_form_search_popup_matches_sales_order_styling(self):
        """Verify adjustment_form.html renders floating popup table with Image 2 headers."""
        res = self.client.get('/inventory/adjustments/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Floating dropdown popup
        self.assertIn('id="adjLiveSearchResults"', html)
        self.assertIn('class="inflow-item-dropdown-popup"', html)

        # Image 2 headers: PHOTO | CATEGORY | ITEM | ON HAND | RESERVED | AVAILABLE
        self.assertIn('PHOTO', html)
        self.assertIn('CATEGORY', html)
        self.assertIn('ITEM', html)
        self.assertIn('ON HAND', html)
        self.assertIn('RESERVED', html)
        self.assertIn('AVAILABLE', html)

        # Mint-cyan highlight matching Image 2
        self.assertIn('#CCFBF1', html)

    def test_zero_test_sales_orders_in_database(self):
        """Verify strict rule: exactly 0 test sales orders remain in the database."""
        test_sos = query_all("""
            SELECT id, order_number FROM sales_orders 
            WHERE order_number ILIKE '%test%' 
               OR notes ILIKE '%test%'
               OR customer_contact ILIKE '%test%'
        """)
        self.assertEqual(len(test_sos), 0, f"Found unexpected test sales orders in DB: {test_sos}")

if __name__ == '__main__':
    unittest.main()
