import unittest
import json
from app import create_app
from database import query_one, query_all, get_db_cursor

class TestSaleStep03Feature(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_new_sales_order_does_not_create_db_record_or_order_number(self):
        """Verify GET /sales/new renders draft without assigning order number or inserting into DB"""
        # Count orders before visiting /sales/new
        before_count = query_one("SELECT COUNT(*) as c FROM sales_orders")['c']

        # Visit /sales/new
        response = self.client.get('/sales/new')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')

        # Count orders after visiting /sales/new - MUST NOT increase!
        after_count = query_one("SELECT COUNT(*) as c FROM sales_orders")['c']
        self.assertEqual(before_count, after_count, "Visiting /sales/new must NOT insert any record into sales_orders table!")

        # Verify Order # input field is blank (matching inFlow screenshot0009.JPEG)
        self.assertIn('id="orderNumberInput"', html)
        self.assertIn('value=""', html)

        # Verify tab title is 'Sales Order' without fake order number
        self.assertIn("title: 'Sales Order'", html)

        # Verify expand arrow button is present in search drawer header
        self.assertIn('id="drawerExpandBtn"', html)
        self.assertIn('onclick="toggleDrawerExpand()"', html)
        self.assertIn('title="Expand list"', html)

        # Verify both compact and expanded drawer views are present
        self.assertIn('inflow-drawer-compact-view', html)
        self.assertIn('inflow-drawer-expanded-view', html)
        self.assertIn('inflow-expanded-table', html)

        # Verify expanded table columns match inFlow desktop (Order #, Date, Status, Customer, PO, Location, Shipped, Total, Paid, Balance)
        self.assertIn('P.O. #', html)
        self.assertIn('Shipped Date', html)
        self.assertIn('Balance', html)

        # Verify inFlow save prompt modal is present
        self.assertIn('id="inflowSavePromptModal"', html)
        self.assertIn("Save changes to Sales Order?", html)
        self.assertIn("Don't Save", html)

    def test_expand_arrow_present_on_existing_order_detail(self):
        """Verify expand arrow button is present in detail view of existing orders"""
        existing = query_one("SELECT id, order_number FROM sales_orders ORDER BY id DESC LIMIT 1")
        if existing:
            response = self.client.get(f"/sales/{existing['id']}")
            self.assertEqual(response.status_code, 200)
            html = response.data.decode('utf-8')
            self.assertIn('id="drawerExpandBtn"', html)
            self.assertIn('inflow-drawer-expanded-view', html)
            self.assertIn('inflow-expanded-table', html)
            self.assertIn('id="inflowSavePromptModal"', html)

    def test_save_sales_order_assigns_order_number_and_persists_to_db(self):
        """Verify clicking Save creates the sales order and generates the SO number"""
        cust = query_one("SELECT id, name FROM customers WHERE is_active = TRUE LIMIT 1")
        prod = query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE LIMIT 1")
        loc = query_one("SELECT id FROM locations WHERE is_active = TRUE LIMIT 1")

        before_count = query_one("SELECT COUNT(*) as c FROM sales_orders")['c']

        post_data = {
            'customer_id': str(cust['id']),
            'location_id': str(loc['id']),
            'sales_rep': 'Test Rep',
            'notes': 'Created via Step 03 Save button',
            'lines_json': json.dumps([{
                'product_id': prod['id'],
                'description': 'Test item',
                'quantity': 2,
                'unit_price': float(prod['default_price'] or 10.0),
                'discount_percent': 0,
                'uom': 'pcs'
            }])
        }

        try:
            # Submit save for new order
            res = self.client.post('/sales/new/save', data=post_data, follow_redirects=False)
            self.assertEqual(res.status_code, 302)

            after_count = query_one("SELECT COUNT(*) as c FROM sales_orders")['c']
            self.assertEqual(after_count, before_count + 1)

            # Check newly created order
            new_order = query_one("SELECT * FROM sales_orders ORDER BY id DESC LIMIT 1")
            self.assertTrue(new_order['order_number'].startswith('SO-'))
            self.assertEqual(new_order['customer_id'], cust['id'])
            self.assertGreater(float(new_order['total_amount']), 0)

            # Verify redirect target is the new order detail page
            self.assertIn(f"/sales/{new_order['id']}", res.headers['Location'])
        finally:
            # Guaranteed cleanup of test order and sequence reset
            created = query_one("SELECT id, total_amount FROM sales_orders WHERE notes = 'Created via Step 03 Save button' ORDER BY id DESC LIMIT 1")
            if created:
                with get_db_cursor(commit=True) as cur:
                    cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (created['id'],))
                    cur.execute("DELETE FROM sales_orders WHERE id = %s", (created['id'],))
                    cur.execute("UPDATE customers SET balance = GREATEST(0, balance - %s) WHERE id = %s", (float(created['total_amount'] or 0), cust['id']))
                    cur.execute(r"SELECT GREATEST(COALESCE(MAX(id), 0), COALESCE(MAX(NULLIF(regexp_replace(order_number, '\D', '', 'g'), '')::bigint), 0)) FROM sales_orders")
                    row = cur.fetchone()
                    max_so = list(row.values())[0] if row else 0
                    if max_so > 0:
                        cur.execute("SELECT setval('so_number_seq', %s, true)", (max_so,))

if __name__ == '__main__':
    unittest.main()
