import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, execute, execute_returning_id

class TestSoCrossAndMoveLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

        # Ensure no test orders from previous runs
        execute("""
            DELETE FROM sales_order_lines WHERE sales_order_id IN (
                SELECT id FROM sales_orders WHERE notes LIKE 'TEST-SO-CROSS-MOVE%%'
            );
            DELETE FROM sales_orders WHERE notes LIKE 'TEST-SO-CROSS-MOVE%%';
        """)

    def tearDown(self):
        # Guarantee 0 test SOs remain (User rule: delete all test SOs)
        execute("""
            DELETE FROM sales_order_lines WHERE sales_order_id IN (
                SELECT id FROM sales_orders WHERE notes LIKE 'TEST-SO-CROSS-MOVE%%'
            );
            DELETE FROM sales_orders WHERE notes LIKE 'TEST-SO-CROSS-MOVE%%';
        """)

    def test_so_template_has_selector_before_no_and_no_right_trash(self):
        """
        Verify:
        1. SO items table has inflow-grid-selector-col header before # header.
        2. Rightmost action column with trash button is removed from header.
        3. Cross delete button (✕) and move up/down buttons (▲, ▼) are present in the selector column.
        4. #newRowEntry has empty selector column before '+' and no rightmost empty cell.
        """
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Header structure: selector-col comes before #
        table_idx = html.find('id="lineItemsTable"')
        self.assertTrue(table_idx > -1, "lineItemsTable should exist")
        table_html = html[table_idx:table_idx + 1000]
        self.assertIn('class="inflow-grid-selector-col"', table_html)
        idx_selector_th = table_html.find('class="inflow-grid-selector-col"')
        idx_no_th = table_html.find('>#</th>')
        self.assertTrue(idx_selector_th < idx_no_th, "Selector header should be placed before # header in lineItemsTable")

        # 2. Right trash button column removed from the table headers
        self.assertNotIn('<th style="width: 44px; text-align: center;" title="Actions"></th>', html)

        # 3. Row operations: cross delete and move buttons
        self.assertIn('line-delete-cross-btn', html)
        self.assertIn('so-line-move-stack', html)
        self.assertIn('so-line-move-btn', html)
        self.assertIn('moveSoLineUp', html)
        self.assertIn('moveSoLineDown', html)
        self.assertIn('deleteSpecificSoLine', html)

        # 4. #newRowEntry structure
        self.assertIn('<tr id="newRowEntry"', html)
        idx_new_row = html.find('id="newRowEntry"')
        new_row_slice = html[idx_new_row:idx_new_row + 800]
        self.assertIn('inflow-grid-selector-col', new_row_slice)
        self.assertIn('+', new_row_slice)

    def test_existing_so_shows_cross_and_move_for_lines(self):
        """
        Verify an existing SO with lines displays cross (✕) and move up/down (▲, ▼) buttons
        before each line's No. column.
        """
        # Find an existing product without mutating catalog
        prod = query_one("SELECT id, name, sku FROM products LIMIT 1")
        if not prod:
            self.skipTest("No existing product found in database.")

        cust = query_one("SELECT id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else None

        loc = query_one("SELECT id FROM locations LIMIT 1")
        loc_id = loc['id'] if loc else 1

        so_id = execute_returning_id("""
            INSERT INTO sales_orders (order_number, customer_id, location_id, order_date, status, payment_status, total_amount, balance_due, notes)
            VALUES ('SO-TEST-CROSS-01', %s, %s, CURRENT_DATE, 'PENDING', 'UNPAID', 50.0, 50.0, 'TEST-SO-CROSS-MOVE-01')
            RETURNING id;
        """, (cust_id, loc_id))

        execute("""
            INSERT INTO sales_order_lines (sales_order_id, line_num, product_id, description, quantity, unit_price, subtotal, uom)
            VALUES (%s, 1, %s, %s, 1, 50.0, 50.0, 'pcs.');
        """, (so_id, prod['id'], prod['name']))

        resp = self.client.get(f'/sales/{so_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('line-delete-cross-btn', html)
        self.assertIn('moveSoLineUp', html)
        self.assertIn('moveSoLineDown', html)
        self.assertIn('deleteSpecificSoLine', html)

        # In the rendered row, selector cell with cross & move buttons appears before line-no-col
        idx_row = html.find(f'data-product-id="{prod["id"]}"')
        self.assertTrue(idx_row > -1)
        row_slice = html[idx_row:idx_row + 1500]

        idx_selector_td = row_slice.find('inflow-grid-selector-col')
        idx_no_td = row_slice.find('line-no-col')
        self.assertTrue(idx_selector_td < idx_no_td, "Selector column must appear before No. column in line row")
        self.assertIn('✕', row_slice)
        self.assertIn('▲', row_slice)
        self.assertIn('▼', row_slice)

        # Rightmost delete trash can svg is absent from the row
        self.assertNotIn('so-qty-trash-btn', row_slice)

if __name__ == '__main__':
    unittest.main()
