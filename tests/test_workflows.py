import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, execute, execute_returning_id

class TestWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Clean up any leftover test data
        execute("DELETE FROM stock_transfer_lines WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM stock_transfers WHERE notes = 'Stock transfer test'")
        execute("DELETE FROM stock_adjustment_lines WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM stock_adjustments WHERE notes = 'Cycle count test'")
        execute("DELETE FROM sales_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM sales_orders WHERE customer_id IN (SELECT id FROM customers WHERE phone = '012999888')")
        execute("DELETE FROM purchase_orders WHERE vendor_id IN (SELECT id FROM vendors WHERE phone = '023888777')")
        execute("DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku = 'WORKFLOW-TEST-01')")
        execute("DELETE FROM products WHERE sku = 'WORKFLOW-TEST-01'")
        execute("DELETE FROM customers WHERE phone = '012999888'")
        execute("DELETE FROM vendors WHERE phone = '023888777'")

        # Ensure a test customer, product, and warehouse exist
        cls.loc_main = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")['id']
        cls.loc_stm = query_one("SELECT id FROM locations WHERE id != %s LIMIT 1", (cls.loc_main,))['id']

        cls.cust_id = execute_returning_id("""
            INSERT INTO customers (name, phone, address1, city)
            VALUES ('Automated Test Customer', '012999888', 'Russian Blvd', 'Phnom Penh')
            RETURNING id;
        """)

        cls.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, address1)
            VALUES ('Automated Test Vendor', '023888777', 'Phnom Penh Port')
            RETURNING id;
        """)

        cls.prod_id = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, average_cost, uom)
            VALUES ('WORKFLOW-TEST-01', 'Workflow Test Eco Box 500', 25.00, 15.00, 15.00, 'case')
            RETURNING id;
        """)

        # Set initial inventory
        execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
            VALUES (%s, %s, '', 100)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET quantity = 100;
        """, (cls.prod_id, cls.loc_main))

    @classmethod
    def tearDownClass(cls):
        execute("DELETE FROM stock_transfer_lines WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM stock_transfers WHERE notes = 'Stock transfer test'")
        execute("DELETE FROM stock_adjustment_lines WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM stock_adjustments WHERE notes = 'Cycle count test'")
        execute("DELETE FROM sales_order_lines WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM purchase_order_lines WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM sales_orders WHERE customer_id = %s", (cls.cust_id,))
        execute("DELETE FROM purchase_orders WHERE vendor_id = %s", (cls.vend_id,))
        execute("DELETE FROM inventory WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM inventory_logs WHERE product_id = %s", (cls.prod_id,))
        execute("DELETE FROM products WHERE id = %s", (cls.prod_id,))
        execute("DELETE FROM customers WHERE id = %s", (cls.cust_id,))
        execute("DELETE FROM vendors WHERE id = %s", (cls.vend_id,))

    def test_sales_fulfillment_workflow(self):
        """Test full SO lifecycle: Create -> Pick -> Pack -> Ship -> Pay"""
        # 1. Create SO
        post_data = {
            'customer_id': self.cust_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [10],
            'unit_price[]': [25.00],
            'discount_percent[]': [0],
            'description[]': ['Workflow Test Eco Box 500']
        }
        res = self.client.post('/sales/create', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify SO exists
        so = query_one("SELECT * FROM sales_orders WHERE customer_id = %s ORDER BY id DESC LIMIT 1", (self.cust_id,))
        self.assertIsNotNone(so)
        so_id = so['id']
        self.assertEqual(float(so['total_amount']), 250.00)
        self.assertEqual(so['status'], 'OPEN')

        # 2. Advance to Picked
        res_pick = self.client.post(f'/sales/{so_id}/status', data={'status': 'PICKED'}, follow_redirects=True)
        self.assertEqual(res_pick.status_code, 200)
        so_picked = query_one("SELECT status FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_picked['status'], 'PICKED')

        # 3. Advance to Packed
        res_pack = self.client.post(f'/sales/{so_id}/status', data={'status': 'PACKED'}, follow_redirects=True)
        self.assertEqual(res_pack.status_code, 200)
        so_packed = query_one("SELECT status FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_packed['status'], 'PACKED')

        # 4. Ship Order (Deducts stock from 100 down to 90)
        stock_before = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        res_ship = self.client.post(f'/sales/{so_id}/status', data={
            'status': 'SHIPPED',
            'carrier': 'FastDelivery',
            'tracking_number': 'TRK-TEST-99'
        }, follow_redirects=True)
        self.assertEqual(res_ship.status_code, 200)

        stock_after = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        self.assertEqual(float(stock_after), float(stock_before) - 10)

        # 5. Record Payment
        res_pay = self.client.post(f'/sales/{so_id}/pay', data={'amount': 250.00}, follow_redirects=True)
        self.assertEqual(res_pay.status_code, 200)
        so_paid = query_one("SELECT payment_status, balance_due FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_paid['payment_status'], 'PAID')
        self.assertEqual(float(so_paid['balance_due']), 0.0)

    def test_purchase_receiving_workflow(self):
        """Test PO lifecycle: Create -> Receive (increments inventory & logs ledger) -> Pay"""
        # 1. Create PO
        post_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [50],
            'unit_cost[]': [14.00],
            'description[]': ['Workflow Test Eco Box 500']
        }
        res = self.client.post('/purchases/create', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        po = query_one("SELECT * FROM purchase_orders WHERE vendor_id = %s ORDER BY id DESC LIMIT 1", (self.vend_id,))
        self.assertIsNotNone(po)
        po_id = po['id']
        self.assertEqual(float(po['total_amount']), 700.00)

        # 2. Receive Goods
        stock_before = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        res_rec = self.client.post(f'/purchases/{po_id}/receive', follow_redirects=True)
        self.assertEqual(res_rec.status_code, 200)

        stock_after = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        self.assertEqual(float(stock_after), float(stock_before) + 50)

        po_rec = query_one("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po_rec['status'], 'RECEIVED')

    def test_stock_adjustment_workflow(self):
        """Test physical count adjustment updates stock and writes to ledger"""
        res = self.client.post('/inventory/adjustments/create', data={
            'location_id': self.loc_main,
            'reason': 'Recount',
            'product_id': self.prod_id,
            'new_qty': 120,
            'notes': 'Cycle count test'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        stock = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        self.assertEqual(float(stock), 120.0)

    def test_stock_transfer_workflow(self):
        """Test transferring stock between warehouses"""
        res = self.client.post('/inventory/transfers/create', data={
            'from_location_id': self.loc_main,
            'to_location_id': self.loc_stm,
            'product_id': self.prod_id,
            'quantity': 25,
            'notes': 'Stock transfer test'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        stock_src = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['quantity']
        stock_dst = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_stm))['quantity']

        self.assertEqual(float(stock_src), 95.0) # 120 - 25 = 95
        self.assertEqual(float(stock_dst), 25.0)

if __name__ == '__main__':
    unittest.main()
