import unittest
import csv
import io
import os
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

from app import create_app
from database import query_one, query_all, execute

class TestAdaptiveCosting(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_toggle_adaptive_cost_api(self):
        """Test API endpoints for toggling adaptive costing on product and price scheme."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Check product VET (id 142) or find a test product
        prod = query_one("SELECT id, name, is_adaptive_cost FROM products WHERE sku = 'VET' OR name ILIKE '%%VET%%' LIMIT 1")
        if not prod:
            prod = query_one("SELECT id, name, is_adaptive_cost FROM products LIMIT 1")
        self.assertIsNotNone(prod)
        prod_id = prod['id']
        original_status = bool(prod.get('is_adaptive_cost', False))

        try:
            # 1. Toggle ON
            res = self.client.post(f'/api/products/{prod_id}/toggle_adaptive_cost', json={'is_adaptive_cost': True})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))
            self.assertTrue(data.get('is_adaptive_cost'))

            db_prod = query_one("SELECT is_adaptive_cost FROM products WHERE id = %s", (prod_id,))
            self.assertTrue(db_prod['is_adaptive_cost'])

            # 2. Toggle scheme adaptive
            scheme = query_one("SELECT id FROM pricing_schemes WHERE is_active = TRUE LIMIT 1")
            if scheme:
                scheme_id = scheme['id']
                s_res = self.client.post(f'/api/products/{prod_id}/toggle_scheme_adaptive/{scheme_id}', json={'is_adaptive': True})
                self.assertEqual(s_res.status_code, 200)
                s_data = s_res.get_json()
                self.assertTrue(s_data.get('success'))
                self.assertTrue(s_data.get('is_adaptive'))

                pp = query_one("SELECT is_adaptive FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (prod_id, scheme_id))
                self.assertTrue(pp['is_adaptive'])

                # Toggle scheme adaptive OFF
                self.client.post(f'/api/products/{prod_id}/toggle_scheme_adaptive/{scheme_id}', json={'is_adaptive': False})
        finally:
            # Restore original status
            execute("UPDATE products SET is_adaptive_cost = %s WHERE id = %s", (original_status, prod_id))

    def test_adaptive_cost_in_profit_calculation(self):
        """
        Verify that when a product is adaptive, its COGS in reports equals its sale price,
        yielding exactly $0.00 profit.
        """
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        # Find or create a sales order line with VET or create a temporary test order
        vet = query_one("SELECT id, sku FROM products WHERE sku = 'VET' OR name ILIKE '%%VET%%' LIMIT 1")
        if not vet:
            vet = query_one("SELECT id, sku FROM products LIMIT 1")
        vet_id = vet['id']

        # Temporarily enable is_adaptive_cost
        execute("UPDATE products SET is_adaptive_cost = TRUE WHERE id = %s", (vet_id,))

        try:
            # Query reports/view/sales-order-profit
            resp = self.client.get('/reports/view/sales-order-profit?date_range=All')
            self.assertEqual(resp.status_code, 200)

            # Test SQL COGS expression directly
            from routes.reports import _get_line_cogs_sql_expr
            cogs_expr = _get_line_cogs_sql_expr('sol', 'p', 'pp', 'so')

            res = query_one(f"""
                SELECT 
                    sol.id,
                    sol.unit_price,
                    COALESCE(sol.subtotal, sol.quantity * sol.unit_price) as sale_amt,
                    ({cogs_expr}) as calculated_cogs,
                    COALESCE(sol.subtotal, sol.quantity * sol.unit_price) - ({cogs_expr}) as calculated_profit
                FROM sales_order_lines sol
                JOIN products p ON sol.product_id = p.id
                JOIN sales_orders so ON sol.sales_order_id = so.id
                LEFT JOIN product_prices pp ON pp.product_id = p.id AND pp.pricing_scheme_id = 107
                WHERE sol.product_id = %s AND sol.subtotal > 0
                LIMIT 1
            """, (vet_id,))

            if res:
                self.assertAlmostEqual(float(res['sale_amt']), float(res['calculated_cogs']), places=2)
                self.assertAlmostEqual(float(res['calculated_profit']), 0.0, places=2)
        finally:
            # Reset back to False
            execute("UPDATE products SET is_adaptive_cost = FALSE WHERE id = %s", (vet_id,))
