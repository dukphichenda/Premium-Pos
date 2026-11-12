import unittest
import json
from app import create_app
from database import query_one, execute

class TestPosBillingCustomerAndDelete(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_pos_template_has_delete_button_and_full_height(self):
        """Verify templates/branches/pos.html contains the delete button and edge-to-edge layout."""
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base_dir, 'templates', 'branches', 'pos.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Delete button & removeFromCart function
        self.assertIn('pos-bill-del-btn', content)
        self.assertIn('removeFromCart', content)
        self.assertIn('customer_name: custName', content)

        # Full height edge-to-edge & no white blank at bottom
        self.assertIn('html, body.pos-modern-body', content)
        self.assertIn('body.pos-modern-body .content-area', content)
        self.assertIn('height: 100% !important;', content)

    def test_pos_checkout_saves_customer_name_and_walkin(self):
        """Verify POS checkout saves customer_contact and links walk-in customer without catalog mutation."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'admin'

        # Get an existing product (read-only, zero catalog mutations)
        prod = query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        self.assertIsNotNone(prod)

        test_order_no = None
        try:
            # Test checkout with Walk-in customer (customer_id = None)
            res = self.client.post('/branches/1/pos/checkout', json={
                'items': [{
                    'product_id': prod['id'],
                    'quantity': 1,
                    'uom': 'Pack',
                    'total_pcs': 1,
                    'unit_price': float(prod['default_price'] or 10.0),
                    'pricing_scheme_id': 100
                }],
                'customer_id': None,
                'customer_name': 'Walk-in Customer (អតិថិជនទូទៅ)',
                'discount_amount': 0.0,
                'total_amount': float(prod['default_price'] or 10.0),
                'paid_amount': float(prod['default_price'] or 10.0),
                'payment_method': 'Cash',
                'force_checkout': True
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))
            test_order_no = data.get('order_number')
            self.assertIsNotNone(test_order_no)

            # Verify sales order has customer_id and customer_contact set
            so = query_one("""
                SELECT so.id, so.order_number, so.customer_id, so.customer_contact, c.name as customer_name
                FROM sales_orders so
                LEFT JOIN customers c ON so.customer_id = c.id
                WHERE so.order_number = %s
            """, (test_order_no,))
            self.assertIsNotNone(so)
            self.assertIsNotNone(so['customer_id'])
            self.assertIn('Walk', so['customer_contact'])

            # Verify detail_order route returns customer_name properly
            so_detail = self.client.get(f'/sales/{so["id"]}')
            self.assertEqual(so_detail.status_code, 200)
            detail_html = so_detail.data.decode('utf-8', errors='ignore')
            self.assertIn('Walk', detail_html)

        finally:
            # STRICT RULE: Delete test sales order completely! Zero test orders remain.
            if test_order_no:
                so_row = query_one("SELECT id FROM sales_orders WHERE order_number = %s", (test_order_no,))
                if so_row:
                    so_id = so_row['id']
                    execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (so_id,))
                    execute("DELETE FROM sales_orders WHERE id = %s", (so_id,))

if __name__ == '__main__':
    unittest.main()
