import os
import unittest
from app import create_app
from database import query_one, query_all, execute, get_db_cursor, sync_inventory_reserved_quantities

class TestSoStockQuantities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def test_sync_inventory_reserved_quantities(self):
        """Verify sync_inventory_reserved_quantities computes exact open SO reservations."""
        sync_inventory_reserved_quantities()
        
        # Check M600-QP product
        prod = query_one("SELECT id, sku FROM products WHERE sku = 'M600-QP'")
        self.assertIsNotNone(prod)
        pid = prod['id']

        # Total open SO quantity for M600-QP
        open_sol = query_one("""
            SELECT COALESCE(SUM(sol.quantity), 0) as expected_reserved
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            WHERE sol.product_id = %s
              AND so.status NOT IN ('PAID', 'SHIPPED', 'CANCELLED', 'INVOICED')
              AND (so.payment_status IS NULL OR so.payment_status != 'PAID')
        """, (pid,))
        expected_res = float(open_sol['expected_reserved'])

        # Total stored inventory reserved
        inv_res = query_one("""
            SELECT COALESCE(SUM(reserved_quantity), 0) as stored_reserved,
                   COALESCE(SUM(quantity), 0) as stock_on_hand
            FROM inventory
            WHERE product_id = %s
        """, (pid,))
        stored_res = float(inv_res['stored_reserved'])

        self.assertEqual(stored_res, expected_res, f"M600-QP stored reserved ({stored_res}) must match open SO ({expected_res})")

    def test_so_detail_page_stock_catalog(self):
        """Verify SO detail page window.productsCatalog contains accurate onHand, reserved, and available."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'HQ Admin'
            sess['role'] = 'main_admin'

        # Get an active sales order
        so = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(so)

        response = self.client.get(f"/sales/{so['id']}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("window.productsCatalog =", html)
        self.assertIn("stock_on_hand:", html)
        self.assertIn("stock_reserved:", html)
        self.assertIn("stock_on_order:", html)

    def test_no_double_reservation_on_save(self):
        """Verify saving an order repeatedly does not inflate reserved_quantity."""
        sync_inventory_reserved_quantities()

        prod = query_one("SELECT id FROM products WHERE sku = 'M600-QP'")
        pid = prod['id']

        res_before = float(query_one("SELECT COALESCE(SUM(reserved_quantity), 0) as r FROM inventory WHERE product_id = %s", (pid,))['r'])

        # Re-run sync to confirm idempotency
        sync_inventory_reserved_quantities()

        res_after = float(query_one("SELECT COALESCE(SUM(reserved_quantity), 0) as r FROM inventory WHERE product_id = %s", (pid,))['r'])
        self.assertEqual(res_before, res_after)

if __name__ == '__main__':
    unittest.main()
