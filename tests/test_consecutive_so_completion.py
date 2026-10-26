import unittest
from app import create_app
from database import query_one, get_db_cursor

class TestConsecutiveSoCompletion(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

    def test_templates_do_not_hardcode_is_paid_return_in_scripts(self):
        """Ensure no javascript functions have static Jinja return statements on is_paid."""
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for tpl_rel in ['templates/sales/_detail_canvas.html', 'templates/sales/detail.html']:
            tpl_path = os.path.join(base_dir, tpl_rel)
            with open(tpl_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Ensure handleCanvasCompletePay does not have '{% if is_paid %} return;'
            self.assertNotIn(
                '{% if is_paid %}\n        return;\n        {% endif %}',
                content,
                f"Found hardcoded Jinja return in {tpl_rel}"
            )
            self.assertNotIn(
                '{% if is_paid %}\r\n        return;\r\n        {% endif %}',
                content,
                f"Found hardcoded Jinja return in {tpl_rel}"
            )

    def test_detail_order_renders_dynamic_is_order_paid(self):
        """Ensure detail_order renders dynamic isOrderPaid function."""
        # Find any existing order
        ord_rec = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if ord_rec:
            res = self.client.get(f"/sales/{ord_rec['id']}")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn('function isOrderPaid()', html)
            self.assertIn('handleCanvasCompletePay()', html)
            self.assertIn('soPartialMeta', html)

    def test_complete_consecutive_orders_via_complete_pay(self):
        """Test completing two consecutive orders in sequence without catalog mutation."""
        cust = query_one("SELECT id FROM customers LIMIT 1")
        prod = query_one("SELECT id, default_price FROM products ORDER BY id ASC LIMIT 1")
        if not cust or not prod:
            self.skipTest("Need customers and products to run this test")

        pid = prod['id']
        initial_prod_price = float(prod['default_price'] or 0)

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sales_orders (order_number, customer_id, status, payment_status, total_amount, balance_due)
                VALUES ('SO-TEST-CONSEC1', %s, 'OPEN', 'UNPAID', 50.00, 50.00)
                RETURNING id
            """, (cust['id'],))
            so1_id = cur.fetchone()['id']
            cur.execute("""
                INSERT INTO sales_orders (order_number, customer_id, status, payment_status, total_amount, balance_due)
                VALUES ('SO-TEST-CONSEC2', %s, 'OPEN', 'UNPAID', 75.00, 75.00)
                RETURNING id
            """, (cust['id'],))
            so2_id = cur.fetchone()['id']

        try:
            # Complete first order
            res1 = self.client.post(f"/sales/{so1_id}/complete_pay", data={'payment_method': 'ABA Bank'}, follow_redirects=False)
            self.assertIn(res1.status_code, (200, 302))
            so1 = query_one("SELECT status, payment_status, payment_method FROM sales_orders WHERE id = %s", (so1_id,))
            self.assertEqual(so1['status'], 'PAID')
            self.assertEqual(so1['payment_status'], 'PAID')
            self.assertEqual(so1['payment_method'], 'ABA Bank')

            # Complete second order (consecutive)
            res2 = self.client.post(f"/sales/{so2_id}/complete_pay", data={'payment_method': 'Cash'}, follow_redirects=False)
            self.assertIn(res2.status_code, (200, 302))
            so2 = query_one("SELECT status, payment_status, payment_method FROM sales_orders WHERE id = %s", (so2_id,))
            self.assertEqual(so2['status'], 'PAID')
            self.assertEqual(so2['payment_status'], 'PAID')
            self.assertEqual(so2['payment_method'], 'Cash')

            # RULE 1 check: Verify product catalog price was NEVER mutated
            prod_after = query_one("SELECT default_price FROM products WHERE id = %s", (pid,))
            self.assertIsNotNone(prod_after)
            self.assertEqual(float(prod_after['default_price'] or 0), initial_prod_price)

        finally:
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM sales_orders WHERE id IN (%s, %s)", (so1_id, so2_id))

if __name__ == '__main__':
    unittest.main()
