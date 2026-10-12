import sys
import os
sys.path.insert(0, os.path.abspath('.'))
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import unittest
from app import create_app
from database import query_one, query_all

class TestSalesOrderUOMSync(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_uom_distribution_non_empty(self):
        """Ensure cases, pcs., ea., and packs are properly populated and no null quantity_display."""
        stats = query_all("""
            SELECT uom, COUNT(*) as cnt, COUNT(quantity_display) as qd_cnt 
            FROM sales_order_lines 
            GROUP BY uom 
            ORDER BY cnt DESC;
        """)
        uom_map = {r['uom']: r for r in stats}
        print("\nUOM Distribution in PostgreSQL:")
        for u, r in uom_map.items():
            print(f"  {u}: {r['cnt']} lines (quantity_display: {r['qd_cnt']})")

        self.assertIn('cases', uom_map)
        self.assertIn('packs', uom_map)
        self.assertIn('ea.', uom_map)
        self.assertIn('pcs.', uom_map)

        self.assertGreater(uom_map['cases']['cnt'], 10000, "Should have > 10,000 cases lines")
        self.assertEqual(uom_map['cases']['cnt'], uom_map['cases']['qd_cnt'], "All cases lines should have quantity_display")

    def test_sample_order_22798(self):
        """Verify SO-022798 has exact lines: packs, 0.5 cases, 0.5 cases, pcs."""
        so = query_one("SELECT id, order_number, total_amount FROM sales_orders WHERE order_number = 'SO-022798'")
        self.assertIsNotNone(so)

        lines = query_all("""
            SELECT sol.line_num, sol.quantity_display, sol.uom, sol.quantity, sol.unit_price, sol.subtotal, p.name as product_name
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE sol.sales_order_id = %s
            ORDER BY sol.line_num
        """, (so['id'],))

        self.assertEqual(len(lines), 4)

        # Line 1: packs
        self.assertEqual(lines[0]['uom'], 'packs')
        self.assertEqual(float(lines[0]['quantity_display']), 1.0)
        self.assertEqual(float(lines[0]['unit_price']), 23.0)

        # Line 2: 0.5 cases @ $60.00 = $30.00
        self.assertEqual(lines[1]['uom'], 'cases')
        self.assertEqual(float(lines[1]['quantity_display']), 0.5)
        self.assertEqual(float(lines[1]['quantity']), 500.0) # 500 base pcs
        self.assertEqual(float(lines[1]['unit_price']), 60.0)
        self.assertEqual(float(lines[1]['subtotal']), 30.0)

        # Line 3: 0.5 cases @ $90.00 = $45.00
        self.assertEqual(lines[2]['uom'], 'cases')
        self.assertEqual(float(lines[2]['quantity_display']), 0.5)
        self.assertEqual(float(lines[2]['quantity']), 500.0) # 500 base pcs
        self.assertEqual(float(lines[2]['unit_price']), 90.0)
        self.assertEqual(float(lines[2]['subtotal']), 45.0)

        # Line 4: delivery pcs
        self.assertEqual(lines[3]['uom'], 'pcs.')
        self.assertEqual(float(lines[3]['quantity_display']), 1.0)
        self.assertEqual(float(lines[3]['subtotal']), 1.5)

    def test_sample_order_22790(self):
        """Verify SO-022790 has line 3 as 1.0 case (1000 pcs)."""
        so = query_one("SELECT id, order_number, total_amount FROM sales_orders WHERE order_number = 'SO-022790'")
        self.assertIsNotNone(so)

        line3 = query_one("""
            SELECT sol.quantity_display, sol.uom, sol.quantity, sol.unit_price, sol.subtotal
            FROM sales_order_lines sol
            WHERE sol.sales_order_id = %s AND sol.line_num = 3
        """, (so['id'],))

        self.assertEqual(line3['uom'], 'cases')
        self.assertEqual(float(line3['quantity_display']), 1.0)
        self.assertEqual(float(line3['quantity']), 1000.0)
        self.assertEqual(float(line3['unit_price']), 37.0)
        self.assertEqual(float(line3['subtotal']), 37.0)

    def test_web_ui_rendering(self):
        """Verify web detail page renders 0.5 and cases correctly."""
        so = query_one("SELECT id FROM sales_orders WHERE order_number = 'SO-022798'")
        res = self.client.get(f"/sales/{so['id']}")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Should render cases button and 0.5 qty
        self.assertIn('cases', html)
        self.assertTrue('value="0.5000"' in html or 'value="0.5"' in html)

    def test_print_invoice_rendering(self):
        """Verify invoice print view displays 0.5 and cases correctly."""
        so = query_one("SELECT id FROM sales_orders WHERE order_number = 'SO-022798'")
        res = self.client.get(f"/sales/{so['id']}/print?type=invoice")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('cases', html)
        self.assertIn('0.5', html)

if __name__ == '__main__':
    unittest.main()
