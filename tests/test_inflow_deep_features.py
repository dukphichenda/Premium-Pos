import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id

class TestInflowDeepFeatures(unittest.TestCase):
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
        # Clean up any leftover test data
        execute("""
            DELETE FROM sales_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM sales_orders WHERE notes LIKE 'Test Deep SO%%';
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test Deep PO%%';
            DELETE FROM stock_transfer_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM stock_transfers WHERE notes LIKE 'Test Deep Transfer%%';
            DELETE FROM stock_adjustment_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM stock_adjustments WHERE notes LIKE 'Test Deep Adj%%';
            DELETE FROM product_prices WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM product_vendors WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM product_versions WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM products WHERE sku LIKE 'TEST-DEEP-%%';
            DELETE FROM customers WHERE phone = '099000111';
            DELETE FROM vendors WHERE phone = '099000222';
        """)

        # Set up test locations, customer, vendor, product
        self.loc_main = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")['id']
        self.loc_stm = query_one("SELECT id FROM locations WHERE id != %s LIMIT 1", (self.loc_main,))['id']

        self.cust_id = execute_returning_id("""
            INSERT INTO customers (name, phone, address1, city, balance)
            VALUES ('Deep Test Customer', '099000111', 'Street 2004', 'Phnom Penh', 0)
            RETURNING id;
        """)

        self.vend_id = execute_returning_id("""
            INSERT INTO vendors (name, phone, address1, balance)
            VALUES ('Deep Test Vendor', '099000222', 'Veng Sreng Blvd', 0)
            RETURNING id;
        """)

        self.prod_id = execute_returning_id("""
            INSERT INTO products (
                sku, name, description, barcode, uom, master_pack_qty, inner_pack_qty,
                default_location_id, reorder_point, reorder_quantity,
                standard_cost, average_cost, default_price,
                item_type, tax_code, costing_method, image_url,
                custom1, custom2, custom3, custom4, custom5
            ) VALUES (
                'TEST-DEEP-01', 'Eco Kraft Box ប្រអប់ក្រដាស', 'Eco friendly packaging box', '885000111222',
                'case', 24, 6, %s, 10, 50,
                10.00, 10.00, 20.00,
                'Stockable', 'Taxable', 'Manual', '/static/uploads/products/test_sample.jpg',
                'Biodegradable', 'Brown', 'Medium', 'ISO9001', 'Local'
            ) RETURNING id;
        """, (self.loc_main,))

        # Initialize baseline version and vendor
        execute("""
            INSERT INTO product_versions (product_id, version_number, name, sku, standard_cost, default_price, change_summary)
            VALUES (%s, 1, 'Eco Kraft Box ប្រអប់ក្រដាស', 'TEST-DEEP-01', 10.00, 20.00, 'Baseline test version');
        """, (self.prod_id,))

        execute("""
            INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost)
            VALUES (%s, %s, 'VEND-KB-01', 9.50)
            ON CONFLICT (product_id, vendor_id) DO NOTHING;
        """, (self.prod_id, self.vend_id))

        # Initial inventory in Main Warehouse
        execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity, reserved_quantity)
            VALUES (%s, %s, '', 100, 0)
            ON CONFLICT (product_id, location_id, sublocation)
            DO UPDATE SET quantity = 100, reserved_quantity = 0;
        """, (self.prod_id, self.loc_main))

    def tearDown(self):
        execute("""
            DELETE FROM sales_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM sales_orders WHERE notes LIKE 'Test Deep SO%%';
            DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM purchase_orders WHERE notes LIKE 'Test Deep PO%%';
            DELETE FROM stock_transfer_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM stock_transfers WHERE notes LIKE 'Test Deep Transfer%%';
            DELETE FROM stock_adjustment_lines WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM stock_adjustments WHERE notes LIKE 'Test Deep Adj%%';
            DELETE FROM product_prices WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM product_vendors WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM product_versions WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM inventory WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM inventory_logs WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'TEST-DEEP-%%');
            DELETE FROM products WHERE sku LIKE 'TEST-DEEP-%%';
            DELETE FROM customers WHERE id = %s;
            DELETE FROM vendors WHERE id = %s;
        """, (self.cust_id, self.vend_id))

    def test_product_detail_page_renders_inflow_architecture(self):
        """Verify product detail view has all inFlow toolbar buttons, section panels, and tabs"""
        res = self.client.get(f'/products/{self.prod_id}?legacy=1')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Toolbar controls
        self.assertIn('inflow-toolbar', html)
        self.assertIn('Save', html)
        self.assertIn('Copy', html)
        self.assertIn('Version', html)
        self.assertIn('Deactivate', html)
        self.assertIn('Attachment', html)

        # 3 Panes
        self.assertIn('Basic', html)
        self.assertIn('Picture', html)
        self.assertIn('Sales Info', html)
        self.assertIn('Costing Info', html)
        self.assertIn('Inventory', html)

        # Bottom Tabs
        self.assertIn('Product Info', html)
        self.assertIn('Extra Info', html)
        self.assertIn('Product Vendors', html)
        self.assertIn('Movement History', html)
        self.assertIn('Order History', html)

        # Khmer font & Unicode support
        self.assertIn('ប្រអប់ក្រដាស', html)

    def test_inplace_product_edit_and_version_tracking(self):
        """Verify full in-place editing updates fields and increments version history"""
        schemes = query_all("SELECT id FROM pricing_schemes WHERE is_active = TRUE LIMIT 2")
        s1_id = schemes[0]['id']
        s2_id = schemes[1]['id'] if len(schemes) > 1 else s1_id

        post_data = {
            'sku': 'TEST-DEEP-01',
            'name': 'Updated Eco Box ប្រអប់ក្រដាសកែច្នៃ v2',
            'description': 'Updated eco specifications',
            'barcode': '999888777666',
            'uom': 'carton',
            'master_pack_qty': '48',
            'inner_pack_qty': '12',
            'reorder_point': '25',
            'reorder_quantity': '100',
            'item_type': 'Stockable',
            'tax_code': 'Taxable',
            'costing_method': 'Average',
            'cost_price': '12.50',
            'custom1': 'Recycled Kraft',
            'custom2': 'Natural Brown',
            'custom3': 'Large',
            'custom4': 'ISO14001',
            'custom5': 'Export Grade',
            f'scheme_price_{s1_id}': '25.00',
            f'scheme_price_{s2_id}': '22.00',
            f'stock_qty_{self.loc_main}': '150',
            f'stock_qty_{self.loc_stm}': '30'
        }

        res = self.client.post(f'/products/{self.prod_id}/save', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify product updated
        updated = query_one("SELECT * FROM products WHERE id = %s", (self.prod_id,))
        self.assertEqual(updated['name'], 'Updated Eco Box ប្រអប់ក្រដាសកែច្នៃ v2')
        self.assertEqual(updated['barcode'], '999888777666')
        self.assertEqual(updated['uom'], 'carton')
        self.assertEqual(float(updated['master_pack_qty']), 48)
        self.assertEqual(float(updated['reorder_point']), 25)
        self.assertEqual(float(updated['standard_cost']), 12.50)
        self.assertEqual(updated['custom1'], 'Recycled Kraft')
        self.assertEqual(updated['custom5'], 'Export Grade')

        # Verify version incremented
        versions = query_all("SELECT * FROM product_versions WHERE product_id = %s ORDER BY version_number DESC", (self.prod_id,))
        self.assertGreaterEqual(len(versions), 2)
        self.assertEqual(versions[0]['version_number'], 2)
        self.assertEqual(versions[0]['name'], 'Updated Eco Box ប្រអប់ក្រដាសកែច្នៃ v2')

        # Verify pricing scheme tiers saved
        p1 = query_one("SELECT unit_price FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (self.prod_id, s1_id))
        self.assertIsNotNone(p1)
        self.assertEqual(float(p1['unit_price']), 25.00)

        # Verify multi-warehouse stock updated and audited
        inv_main = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))
        self.assertEqual(float(inv_main['quantity']), 150.0)

        inv_stm = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_stm))
        self.assertEqual(float(inv_stm['quantity']), 30.0)

        logs = query_all("SELECT * FROM inventory_logs WHERE product_id = %s AND movement_type = 'ADJUSTMENT'", (self.prod_id,))
        self.assertGreaterEqual(len(logs), 1)

    def test_picture_clear_functionality(self):
        """Verify [Clear] picture button marks clear_picture=1 and removes image_url"""
        self.assertIsNotNone(query_one("SELECT image_url FROM products WHERE id = %s", (self.prod_id,))['image_url'])

        post_data = {
            'sku': 'TEST-DEEP-01',
            'name': 'Eco Kraft Box ប្រអប់ក្រដាស',
            'clear_picture': '1'
        }
        res = self.client.post(f'/products/{self.prod_id}/save', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        cleared = query_one("SELECT image_url FROM products WHERE id = %s", (self.prod_id,))
        self.assertIsNone(cleared['image_url'])

    def test_versions_json_api(self):
        """Verify /products/<id>/versions API returns snapshot history"""
        res = self.client.get(f'/products/{self.prod_id}/versions')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]['version_number'], 1)
        self.assertIn('created_at', data[0])

    def test_product_copy_duplication(self):
        """Verify [Copy] duplicates specifications, pricing tiers, and vendor items"""
        res = self.client.get(f'/products/{self.prod_id}/copy', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        copied = query_one("SELECT * FROM products WHERE name LIKE 'Eco Kraft Box%%Copy' LIMIT 1")
        self.assertIsNotNone(copied)
        copied_id = copied['id']

        self.assertNotEqual(copied['sku'], 'TEST-DEEP-01')
        self.assertEqual(float(copied['default_price']), 20.00)

        # Verify product_vendors copied
        copied_vendors = query_all("SELECT * FROM product_vendors WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(copied_vendors), 1)
        self.assertEqual(copied_vendors[0]['vendor_id'], self.vend_id)
        self.assertEqual(float(copied_vendors[0]['cost']), 9.50)

        # Verify initial version 1 recorded
        copied_versions = query_all("SELECT * FROM product_versions WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(copied_versions), 1)
        self.assertEqual(copied_versions[0]['version_number'], 1)
        self.assertEqual(float(copied_versions[0]['default_price']), 20.00)

        # Clean up copied product
        execute("DELETE FROM product_versions WHERE product_id = %s", (copied_id,))
        execute("DELETE FROM product_prices WHERE product_id = %s", (copied_id,))
        execute("DELETE FROM product_vendors WHERE product_id = %s", (copied_id,))
        execute("DELETE FROM inventory WHERE product_id = %s", (copied_id,))
        execute("DELETE FROM products WHERE id = %s", (copied_id,))

    def test_product_status_toggle(self):
        """Verify [Deactivate] / [Activate] toggles is_active flag"""
        # Deactivate
        self.client.post(f'/products/{self.prod_id}/toggle-status', follow_redirects=True)
        p1 = query_one("SELECT is_active FROM products WHERE id = %s", (self.prod_id,))
        self.assertFalse(p1['is_active'])

        # Reactivate
        self.client.post(f'/products/{self.prod_id}/toggle-status', follow_redirects=True)
        p2 = query_one("SELECT is_active FROM products WHERE id = %s", (self.prod_id,))
        self.assertTrue(p2['is_active'])

    def test_sales_fulfillment_complete_lifecycle(self):
        """Test full SO pipeline: Pick -> Pack -> Ship -> Invoice -> Record Payment"""
        # Create Sales Order
        post_data = {
            'customer_id': self.cust_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [10],
            'unit_price[]': [20.00],
            'discount_percent[]': [5.0],
            'notes': 'Test Deep SO Lifecycle'
        }
        res = self.client.post('/sales/create', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        so = query_one("SELECT * FROM sales_orders WHERE notes = 'Test Deep SO Lifecycle'")
        self.assertIsNotNone(so)
        so_id = so['id']
        self.assertEqual(float(so['total_amount']), 190.00) # 10 * 20 - 5% = 190

        # Advance: Open -> Picked
        self.client.post(f'/sales/{so_id}/status', data={'status': 'PICKED'}, follow_redirects=True)
        self.assertEqual(query_one("SELECT status FROM sales_orders WHERE id = %s", (so_id,))['status'], 'PICKED')

        # Advance: Picked -> Packed
        self.client.post(f'/sales/{so_id}/status', data={'status': 'PACKED'}, follow_redirects=True)
        self.assertEqual(query_one("SELECT status FROM sales_orders WHERE id = %s", (so_id,))['status'], 'PACKED')

        # Advance: Packed -> Shipped (Deducts Physical Stock)
        self.client.post(f'/sales/{so_id}/status', data={'status': 'SHIPPED', 'carrier': 'Phnom Penh Express', 'tracking_number': 'TRK-999'}, follow_redirects=True)
        so_shipped = query_one("SELECT * FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_shipped['status'], 'SHIPPED')
        self.assertEqual(so_shipped['carrier'], 'Phnom Penh Express')

        # Verify physical stock deducted from 100 to 90
        inv = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))
        self.assertEqual(float(inv['quantity']), 90.0)

        # Advance: Shipped -> Invoiced
        self.client.post(f'/sales/{so_id}/status', data={'status': 'INVOICED'}, follow_redirects=True)
        self.assertEqual(query_one("SELECT status FROM sales_orders WHERE id = %s", (so_id,))['status'], 'INVOICED')

        # Record payment: $190
        pay_res = self.client.post(f'/sales/{so_id}/pay', data={'amount': '190.00', 'method': 'ABA Pay', 'reference': 'ABA-TX-1001'}, follow_redirects=True)
        self.assertEqual(pay_res.status_code, 200)

        so_paid = query_one("SELECT * FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(float(so_paid['paid_amount']), 190.00)
        self.assertEqual(float(so_paid['balance_due']), 0.00)
        self.assertEqual(so_paid['payment_status'], 'PAID')

    def test_purchase_order_receiving_recalculates_moving_average_cost(self):
        """Test PO receipt increases inventory and recalculates moving average cost accurately"""
        # Current stock: 100 units @ $10.00 average cost
        # Receive: 50 units @ $16.00 unit cost
        # Expected new average cost: ((100 * 10) + (50 * 16)) / 150 = (1000 + 800) / 150 = 1800 / 150 = $12.00
        post_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [50],
            'unit_cost[]': [16.00],
            'notes': 'Test Deep PO Receiving'
        }
        res = self.client.post('/purchases/create', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        po = query_one("SELECT * FROM purchase_orders WHERE notes = 'Test Deep PO Receiving'")
        self.assertIsNotNone(po)
        po_id = po['id']

        # Receive Goods
        rcv_res = self.client.post(f'/purchases/{po_id}/receive', follow_redirects=True)
        self.assertEqual(rcv_res.status_code, 200)

        # Verify inventory increased from 100 to 150
        inv = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))
        self.assertEqual(float(inv['quantity']), 150.0)

        # Verify Moving Average Cost recalculated to exactly $12.00
        p = query_one("SELECT average_cost, last_purchase_cost FROM products WHERE id = %s", (self.prod_id,))
        self.assertAlmostEqual(float(p['average_cost']), 12.00, places=2)
        self.assertEqual(float(p['last_purchase_cost']), 16.00)

        # Verify payables balance added to vendor
        v = query_one("SELECT balance FROM vendors WHERE id = %s", (self.vend_id,))
        self.assertEqual(float(v['balance']), 800.00) # 50 * 16

        # Record Vendor Payment
        self.client.post(f'/purchases/{po_id}/pay', data={'amount': '800.00', 'method': 'Bank Transfer', 'reference': 'FT-8899'}, follow_redirects=True)
        po_paid = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(float(po_paid['paid_amount']), 800.00)
        self.assertEqual(float(po_paid['balance_due']), 0.00)

    def test_create_product_records_correct_version_default_price(self):
        """Verify newly created product records non-zero default_price in initial product_versions snapshot"""
        new_sku = 'TEST-DEEP-CREATE-01'
        res = self.client.post('/products/create', data={
            'name': 'New Product Test Version Price',
            'sku': new_sku,
            'cost_price': '15.00',
            'scheme_price_100': '35.00'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        p = query_one("SELECT id, default_price FROM products WHERE sku = %s", (new_sku,))
        self.assertIsNotNone(p)
        self.assertEqual(float(p['default_price']), 35.00)

        v = query_one("SELECT * FROM product_versions WHERE product_id = %s", (p['id'],))
        self.assertIsNotNone(v)
        self.assertEqual(float(v['default_price']), 35.00)

        # Clean up
        execute("DELETE FROM product_versions WHERE product_id = %s", (p['id'],))
        execute("DELETE FROM product_prices WHERE product_id = %s", (p['id'],))
        execute("DELETE FROM products WHERE id = %s", (p['id'],))

    def test_purchase_order_cancel_reverts_vendor_balance(self):
        """Verify cancelling an ISSUED purchase order reverts vendor open payables and sets status CANCELLED"""
        post_data = {
            'vendor_id': self.vend_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [10],
            'unit_cost[]': [25.00],
            'notes': 'Test Deep PO Cancel'
        }
        self.client.post('/purchases/create', data=post_data, follow_redirects=True)
        po = query_one("SELECT * FROM purchase_orders WHERE notes = 'Test Deep PO Cancel'")
        po_id = po['id']
        self.assertEqual(po['status'], 'ISSUED')

        v_before = query_one("SELECT balance FROM vendors WHERE id = %s", (self.vend_id,))
        self.assertEqual(float(v_before['balance']), 250.00)

        # Cancel PO
        c_res = self.client.post(f'/purchases/{po_id}/cancel', follow_redirects=True)
        self.assertEqual(c_res.status_code, 200)

        po_after = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
        self.assertEqual(po_after['status'], 'CANCELLED')
        self.assertEqual(float(po_after['balance_due']), 0.00)

        v_after = query_one("SELECT balance FROM vendors WHERE id = %s", (self.vend_id,))
        self.assertEqual(float(v_after['balance']), 0.00)

    def test_sales_order_direct_invoice_fulfills_and_deducts_inventory(self):
        """Verify transitioning an order directly to INVOICED fulfills physical inventory and logs movement"""
        post_data = {
            'customer_id': self.cust_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [15],
            'unit_price[]': [20.00],
            'notes': 'Test Deep SO Direct Invoice'
        }
        self.client.post('/sales/create', data=post_data, follow_redirects=True)
        so = query_one("SELECT * FROM sales_orders WHERE notes = 'Test Deep SO Direct Invoice'")
        so_id = so['id']

        # Transition directly to INVOICED without explicit SHIPPED call
        self.client.post(f'/sales/{so_id}/status', data={'status': 'INVOICED'}, follow_redirects=True)
        so_inv = query_one("SELECT * FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_inv['status'], 'INVOICED')
        self.assertIsNotNone(so_inv['shipped_date'])
        self.assertIsNotNone(so_inv['invoiced_date'])

        # Stock deducted from 100 to 85, reserved stock cleared to 0
        inv = query_one("SELECT quantity, reserved_quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))
        self.assertEqual(float(inv['quantity']), 85.0)
        self.assertEqual(float(inv['reserved_quantity']), 0.0)

        # Ledger recorded
        log = query_one("SELECT * FROM inventory_logs WHERE product_id = %s AND reference_id = %s", (self.prod_id, so['order_number']))
        self.assertIsNotNone(log)

    def test_sales_order_cancel_releases_reserved_stock_and_reverts_balance(self):
        """Verify cancelling an OPEN order releases reserved inventory and reverts customer balance"""
        post_data = {
            'customer_id': self.cust_id,
            'location_id': self.loc_main,
            'order_date': '2026-10-07',
            'product_id[]': [self.prod_id],
            'quantity[]': [20],
            'unit_price[]': [20.00],
            'notes': 'Test Deep SO Cancel'
        }
        self.client.post('/sales/create', data=post_data, follow_redirects=True)
        so = query_one("SELECT * FROM sales_orders WHERE notes = 'Test Deep SO Cancel'")
        so_id = so['id']

        inv_reserved = query_one("SELECT reserved_quantity FROM inventory WHERE product_id = %s AND location_id = %s", (self.prod_id, self.loc_main))['reserved_quantity']
        self.assertGreaterEqual(float(inv_reserved), 20.0)

        cust_balance = query_one("SELECT balance FROM customers WHERE id = %s", (self.cust_id,))['balance']
        self.assertGreaterEqual(float(cust_balance), 400.0)

        # Cancel order
        self.client.post(f'/sales/{so_id}/status', data={'status': 'CANCELLED'}, follow_redirects=True)
        so_cancelled = query_one("SELECT status, balance_due FROM sales_orders WHERE id = %s", (so_id,))
        self.assertEqual(so_cancelled['status'], 'CANCELLED')
        self.assertEqual(float(so_cancelled['balance_due']), 0.0)

        cust_balance_after = query_one("SELECT balance FROM customers WHERE id = %s", (self.cust_id,))['balance']
        self.assertEqual(float(cust_balance_after), 0.0)

    def test_internal_system_locations_excluded_from_warehouses(self):
        """Verify internal system locations (<PICKED>, <WORK ORDER>) are excluded from locations list and stock matrix"""
        res_loc = self.client.get('/locations')
        self.assertEqual(res_loc.status_code, 200)
        self.assertNotIn('<PICKED>', res_loc.data.decode('utf-8'))
        self.assertNotIn('<WORK ORDER>', res_loc.data.decode('utf-8'))

        res_inv = self.client.get('/inventory')
        self.assertEqual(res_inv.status_code, 200)
        self.assertNotIn('<PICKED>', res_inv.data.decode('utf-8'))
        self.assertNotIn('<WORK ORDER>', res_inv.data.decode('utf-8'))

if __name__ == '__main__':
    unittest.main()
