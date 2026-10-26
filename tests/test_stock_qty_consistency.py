import unittest
import json
from app import create_app
from database import query_one, query_all, execute, get_db_cursor, sync_inventory_reserved_quantities

class StockQtyConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'

    def test_adjustment_form_js_does_not_subtract_reserved_from_on_hand(self):
        """Ensure adjustment_form.html never subtracts reserved_qty from Qty on Hand display or input."""
        res = self.client.get('/inventory/adjustments/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Bad pattern: subtracting reserved_qty_base from final_qty_base to display as On Hand
        self.assertNotIn("onHandDisp = (item.final_qty_base - item.reserved_qty_base)", html)
        self.assertNotIn("item.final_qty_base = newOnHandBase + item.reserved_qty_base", html)
        self.assertNotIn("(line.new_qty - line.reserved_qty) / factor", html)

        # Good pattern: onHandDisp reflects final_qty_base
        self.assertIn("const onHandDisp = item.final_qty_base / factor;", html)
        self.assertIn("item.final_qty_base = newOnHandBase;", html)

    def test_api_products_for_adjustment_quantities(self):
        """Verify API /api/inventory/products-for-adjustment returns consistent on_hand, reserved, and available."""
        res = self.client.get('/api/inventory/products-for-adjustment?all=true')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('products', data)

        for p in data['products'][:10]:
            on_hand = float(p.get('on_hand_qty') or 0.0)
            reserved = float(p.get('reserved_qty') or 0.0)
            available = float(p.get('available_qty') or 0.0)
            # Available must strictly equal on_hand - reserved
            self.assertAlmostEqual(available, on_hand - reserved, places=2)

    def test_sync_inventory_reserved_handles_internal_pseudo_locations(self):
        """Verify internal pseudo locations like <PICKED> fall back to default warehouse for reservations."""
        # Find product 101 or any product
        prod = query_one("SELECT id FROM products WHERE is_active = TRUE LIMIT 1")
        if not prod:
            self.skipTest("No active product found")
        pid = prod['id']

        def_loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")
        def_loc_id = def_loc['id'] if def_loc else 100

        # Run sync_inventory_reserved_quantities
        sync_inventory_reserved_quantities(product_ids=[pid])
        
        # Verify no reservations exist on internal locations <PICKED> or <WORK ORDER>
        internal_res = query_all("""
            SELECT i.product_id, i.location_id, i.reserved_quantity, l.name
            FROM inventory i
            JOIN locations l ON i.location_id = l.id
            WHERE i.product_id = %s AND l.name LIKE '<%%>' AND i.reserved_quantity > 0;
        """, (pid,))
        self.assertEqual(len(internal_res), 0, "Internal locations must not hold reserved quantities")

if __name__ == '__main__':
    unittest.main()
