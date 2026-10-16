import unittest
import sys
import os
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all, execute, execute_returning_id
from services.csv_exchange import execute_import_data

class TestBranchIsolationImportView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Ensure branches 1 and 2 exist
        execute("INSERT INTO branches (id, code, name, is_active) VALUES (1, 'STM', 'Premium STM', TRUE) ON CONFLICT (id) DO NOTHING;")
        execute("INSERT INTO branches (id, code, name, is_active) VALUES (2, 'SK', 'SK Food box', TRUE) ON CONFLICT (id) DO NOTHING;")

    def setUp(self):
        # Create test customers in branches 1 and 2
        execute("DELETE FROM sales_order_lines WHERE sales_order_id IN (SELECT id FROM sales_orders WHERE order_number IN ('SO-ISO-01', 'SO-ISO-02'));")
        execute("DELETE FROM sales_orders WHERE order_number IN ('SO-ISO-01', 'SO-ISO-02');")
        execute("DELETE FROM customers WHERE name IN ('Isolation Cust Branch 1', 'Isolation Cust Branch 2', 'Shared Name Cust');")

        self.c1_id = execute_returning_id("""
            INSERT INTO customers (name, phone, branch_id, is_active)
            VALUES ('Isolation Cust Branch 1', '012111111', 1, TRUE)
            RETURNING id;
        """)

        self.c2_id = execute_returning_id("""
            INSERT INTO customers (name, phone, branch_id, is_active)
            VALUES ('Isolation Cust Branch 2', '012222222', 2, TRUE)
            RETURNING id;
        """)

        # Create test sales orders in branches 1 and 2
        self.so1_id = execute_returning_id("""
            INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date)
            VALUES ('SO-ISO-01', %s, 1, 100.0, 0, 100.0, 'OPEN', 'UNPAID', CURRENT_DATE)
            RETURNING id;
        """, (self.c1_id,))

        self.so2_id = execute_returning_id("""
            INSERT INTO sales_orders (order_number, customer_id, branch_id, total_amount, paid_amount, balance_due, status, payment_status, order_date)
            VALUES ('SO-ISO-02', %s, 2, 200.0, 0, 200.0, 'OPEN', 'UNPAID', CURRENT_DATE)
            RETURNING id;
        """, (self.c2_id,))

    def tearDown(self):
        execute("DELETE FROM sales_order_lines WHERE sales_order_id IN (%s, %s);", (self.so1_id, self.so2_id))
        execute("DELETE FROM sales_orders WHERE id IN (%s, %s);", (self.so1_id, self.so2_id))
        execute("DELETE FROM customers WHERE id IN (%s, %s);", (self.c1_id, self.c2_id))
        execute("DELETE FROM customers WHERE name IN ('Isolation Cust Branch 1', 'Isolation Cust Branch 2', 'Shared Name Cust', 'Imported Branch 1 Cust', 'Imported Branch 2 Cust');")

    def test_customer_import_stores_per_branch_and_allows_same_name_in_different_branches(self):
        """Verify customer imports set branch_id and scope duplicate detection by branch."""
        # Import customer for Branch 1
        csv_b1 = "Customer Name,Phone,Address\nShared Name Cust,012333001,Street 1"
        res_b1 = execute_import_data('customer', csv_b1, has_headers=True, import_mode='keep', branch_id=1)
        self.assertEqual(res_b1['imported'], 1)

        row_b1 = query_one("SELECT id, branch_id, phone FROM customers WHERE name = 'Shared Name Cust' AND branch_id = 1")
        self.assertIsNotNone(row_b1)
        self.assertEqual(row_b1['branch_id'], 1)
        self.assertEqual(row_b1['phone'], '012333001')

        # Import customer with SAME NAME for Branch 2 -> should create a separate record for Branch 2!
        csv_b2 = "Customer Name,Phone,Address\nShared Name Cust,012333002,Street 2"
        res_b2 = execute_import_data('customer', csv_b2, has_headers=True, import_mode='keep', branch_id=2)
        self.assertEqual(res_b2['imported'], 1)

        row_b2 = query_one("SELECT id, branch_id, phone FROM customers WHERE name = 'Shared Name Cust' AND branch_id = 2")
        self.assertIsNotNone(row_b2)
        self.assertEqual(row_b2['branch_id'], 2)
        self.assertEqual(row_b2['phone'], '012333002')
        self.assertNotEqual(row_b1['id'], row_b2['id'])

    def test_branch_user_can_only_view_own_customers(self):
        """Branch 1 user can only view Branch 1 customers, cannot view Branch 2 customers."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'toulkork'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        # Customer list
        resp = self.client.get('/customers?search=Isolation+Cust')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Isolation Cust Branch 1', html)
        self.assertNotIn('Isolation Cust Branch 2', html)

        # Attempt to access Branch 2 customer details
        resp_detail = self.client.get(f'/customers/{self.c2_id}', follow_redirects=True)
        html_detail = resp_detail.get_data(as_text=True)
        self.assertIn('Access Denied: You do not have permission to view customers outside your branch', html_detail)

    def test_branch_user_can_only_view_own_sales_orders(self):
        """Branch 1 user can only view Branch 1 orders, cannot view Branch 2 orders."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'toulkork'
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1

        # Sales orders view (redirects to modern sales orders workspace)
        resp = self.client.get('/sales?view=table', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('SO-ISO-01', html)
        self.assertNotIn('SO-ISO-02', html)

        # Attempt to view Branch 2 order detail
        resp_so2 = self.client.get(f'/sales/{self.so2_id}', follow_redirects=True)
        html_so2 = resp_so2.get_data(as_text=True)
        self.assertIn('You do not have permission to view orders from another store or Main Store', html_so2)

        # Attempt to complete pay on Branch 2 order
        resp_pay = self.client.post(f'/sales/{self.so2_id}/complete_pay', json={'payment_method': 'Cash'})
        self.assertEqual(resp_pay.status_code, 403)

        # Attempt to delete Branch 2 order
        resp_del = self.client.post(f'/sales/{self.so2_id}/delete', json={})
        self.assertEqual(resp_del.status_code, 403)

    def test_hq_admin_can_see_all(self):
        """HQ admin (main_admin) can see customers and orders across all branches."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None

        # HQ customer overview: All
        resp_cust = self.client.get('/customers?branch=all&search=Isolation+Cust')
        self.assertEqual(resp_cust.status_code, 200)
        html_cust = resp_cust.get_data(as_text=True)
        self.assertIn('Isolation Cust Branch 1', html_cust)
        self.assertIn('Isolation Cust Branch 2', html_cust)

        # HQ filter customers to Branch 1
        resp_cust_b1 = self.client.get('/customers?branch=1&search=Isolation+Cust')
        html_cust_b1 = resp_cust_b1.get_data(as_text=True)
        self.assertIn('Isolation Cust Branch 1', html_cust_b1)
        self.assertNotIn('Isolation Cust Branch 2', html_cust_b1)

        # HQ sales orders overview: All
        resp_sales = self.client.get('/sales?view=table&branch=all', follow_redirects=True)
        self.assertEqual(resp_sales.status_code, 200)
        html_sales = resp_sales.get_data(as_text=True)
        self.assertIn('SO-ISO-01', html_sales)
        self.assertIn('SO-ISO-02', html_sales)

        # HQ can view order details of any branch
        resp_d1 = self.client.get(f'/sales/{self.so1_id}')
        self.assertEqual(resp_d1.status_code, 200)
        self.assertIn('SO-ISO-01', resp_d1.get_data(as_text=True))

        resp_d2 = self.client.get(f'/sales/{self.so2_id}')
        self.assertEqual(resp_d2.status_code, 200)
        self.assertIn('SO-ISO-02', resp_d2.get_data(as_text=True))

    def test_sales_order_import_assigns_branch_id_and_isolates_customers(self):
        """Sales order CSV import sets branch_id on both the sales order and auto-created customers."""
        execute("DELETE FROM sales_order_lines WHERE sales_order_id IN (SELECT id FROM sales_orders WHERE order_number IN ('SO-IMP-B1', 'SO-IMP-B2'));")
        execute("DELETE FROM sales_orders WHERE order_number IN ('SO-IMP-B1', 'SO-IMP-B2');")
        execute("DELETE FROM customers WHERE name IN ('AutoCust Branch 1', 'AutoCust Branch 2');")

        # Import SO for Branch 1
        csv_so1 = "Order Number,Customer Name,Order Date,Item Name,Quantity,Unit Price\nSO-IMP-B1,AutoCust Branch 1,2026-10-14,SKU-0198,2,10.0"
        res1 = execute_import_data('sales_order', csv_so1, has_headers=True, import_mode='keep', branch_id=1)
        self.assertEqual(res1['imported'], 1)

        so1 = query_one("SELECT id, order_number, branch_id, customer_id FROM sales_orders WHERE order_number = 'SO-IMP-B1'")
        self.assertIsNotNone(so1)
        self.assertEqual(so1['branch_id'], 1)

        c1 = query_one("SELECT id, name, branch_id FROM customers WHERE id = %s", (so1['customer_id'],))
        self.assertIsNotNone(c1)
        self.assertEqual(c1['branch_id'], 1)
        self.assertEqual(c1['name'], 'AutoCust Branch 1')

        # Import SO for Branch 2
        csv_so2 = "Order Number,Customer Name,Order Date,Item Name,Quantity,Unit Price\nSO-IMP-B2,AutoCust Branch 2,2026-10-14,SKU-0198,1,20.0"
        res2 = execute_import_data('sales_order', csv_so2, has_headers=True, import_mode='keep', branch_id=2)
        self.assertEqual(res2['imported'], 1)

        so2 = query_one("SELECT id, order_number, branch_id, customer_id FROM sales_orders WHERE order_number = 'SO-IMP-B2'")
        self.assertIsNotNone(so2)
        self.assertEqual(so2['branch_id'], 2)

        c2 = query_one("SELECT id, name, branch_id FROM customers WHERE id = %s", (so2['customer_id'],))
        self.assertIsNotNone(c2)
        self.assertEqual(c2['branch_id'], 2)
        self.assertEqual(c2['name'], 'AutoCust Branch 2')

        # Clean up
        execute("DELETE FROM sales_order_lines WHERE sales_order_id IN (%s, %s);", (so1['id'], so2['id']))
        execute("DELETE FROM sales_orders WHERE id IN (%s, %s);", (so1['id'], so2['id']))
        execute("DELETE FROM customers WHERE id IN (%s, %s);", (c1['id'], c2['id']))

if __name__ == '__main__':
    unittest.main()

