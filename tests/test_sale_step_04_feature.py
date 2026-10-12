import sys
import os
import unittest
import json
from decimal import Decimal

sys.path.insert(0, os.path.abspath('.'))
from app import create_app
import database

class TestSaleStep04Feature(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        so = database.query_one("SELECT id FROM sales_orders WHERE branch_id IS NULL ORDER BY id DESC LIMIT 1")
        self.test_so_id = so['id'] if so else 1

    def test_date_filters_all_presets(self):
        presets = [
            'All', 'Today', 'This Week', 'This Month', 'This Quarter', 'This Year',
            'Yesterday', 'Last Week', 'Last Month', 'Last Quarter', 'Last Year',
            'Last 7 Days', 'Last 30 Days'
        ]
        for preset in presets:
            response = self.client.get(f'/sales/{self.test_so_id}?date_filter={preset}')
            self.assertEqual(response.status_code, 200, f"Failed on date filter preset: {preset}")
            self.assertIn(b'Order Date', response.data)

    def test_status_filters_multi_select(self):
        status_combos = [
            'Open, In Progress, Paid',
            'Open, In Progress',
            'Open',
            'Quote',
            'Fully Shipped',
            'Invoiced',
            'Paid',
            'Cancelled',
            'All'
        ]
        for combo in status_combos:
            response = self.client.get(f'/sales/{self.test_so_id}?status_filter={combo}')
            self.assertEqual(response.status_code, 200, f"Failed on status combo: {combo}")
            self.assertIn(b'Status', response.data)

    def test_html_ui_components_present(self):
        response = self.client.get(f'/sales/{self.test_so_id}')
        html = response.data.decode('utf-8')
        
        # 1. Drawer Date Filter Presets
        self.assertIn('This Week', html)
        self.assertIn('This Quarter', html)
        self.assertIn('Last 7 Days', html)
        self.assertIn('Last 30 Days', html)
        
        # 2. Drawer Status Multi-Select Checkboxes
        self.assertIn('drawerStatusDropdownPopup', html)
        self.assertIn('chkStatusAll', html)
        self.assertIn('status-option-chk', html)
        
        # 3. Quantity Cell & Unit Conversion Popup
        self.assertIn('inflow-qty-cell-wrapper', html)
        self.assertIn('inflow-qty-uom-btn', html)
        self.assertIn('qtyDropdownPopup', html)
        self.assertIn('qtyDropdownBody', html)
        self.assertIn('Qty On Hand', html)
        self.assertIn('Qty Available', html)
        self.assertIn('window.productsCatalog', html)

    def test_save_sales_order_with_unit_conversion(self):
        # Pick a product with sales_uom ratio > 1 (e.g. product 109 with 500 pcs/case)
        prod = database.query_one("SELECT id, sku, uom, sales_uom, sales_uom_ratio_std FROM products WHERE sales_uom_ratio_std > 1 AND sales_uom IS NOT NULL LIMIT 1")
        self.assertIsNotNone(prod)
        
        cust = database.query_one("SELECT id FROM customers LIMIT 1")
        self.assertIsNotNone(cust)

        pid = prod['id']
        ratio = float(prod['sales_uom_ratio_std'])
        sales_uom = prod['sales_uom']
        display_qty = 5.0
        unit_price = 100.0  # per case

        lines_payload = [{
            'product_id': pid,
            'description': 'Test unit conversion line',
            'quantity': display_qty,
            'uom': sales_uom,
            'unit_price': unit_price,
            'discount_percent': 0
        }]

        # Create order
        response = self.client.post('/sales/new/save', data={
            'customer_id': cust['id'],
            'location_id': 1,
            'sales_rep': 'Tester',
            'notes': 'Unit test SO',
            'lines_json': json.dumps(lines_payload)
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        # Verify in DB
        last_so = database.query_one("SELECT id, order_number, total_amount FROM sales_orders WHERE notes = 'Unit test SO' ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(last_so)
        self.assertEqual(float(last_so['total_amount']), display_qty * unit_price)

        line = database.query_one("SELECT * FROM sales_order_lines WHERE sales_order_id = %s", (last_so['id'],))
        self.assertIsNotNone(line)
        self.assertEqual(float(line['quantity_display']), display_qty)
        self.assertEqual(line['uom'], sales_uom)
        # Standard quantity should equal display_qty * ratio
        expected_std_qty = display_qty * ratio
        self.assertEqual(float(line['quantity']), expected_std_qty)

        # Cleanup test SO
        with database.get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (last_so['id'],))
            cur.execute("DELETE FROM sales_orders WHERE id = %s", (last_so['id'],))

if __name__ == '__main__':
    unittest.main()
