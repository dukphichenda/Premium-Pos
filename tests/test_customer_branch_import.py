import unittest
import csv
import io
from database import query_one, query_all, execute
from services.csv_exchange import preview_import_data, execute_import_data

class TestCustomerBranchImport(unittest.TestCase):
    def setUp(self):
        # Ensure test branch exists
        self.branch = query_one("SELECT id, code, name FROM branches WHERE id = 2;")
        if not self.branch:
            self.branch = query_one("SELECT id, code, name FROM branches LIMIT 1;")
        self.branch_id = self.branch['id'] if self.branch else 2

        # Clean up any leftover test customers
        execute("DELETE FROM customers WHERE name LIKE 'TEST_CUST_%%';")

    def tearDown(self):
        # Clean up test customers
        execute("DELETE FROM customers WHERE name LIKE 'TEST_CUST_%%';")

    def test_customer_csv_preview_and_branch_import(self):
        # Sample CSV mimicking inFlow_Customer.csv from user screenshot
        csv_data = (
            "Name,ContactName,Phone,Fax,Email,Website,Address1,Address2,City,State,Country,PostalCode,Remarks\n"
            "TEST_CUST_001,Mr. Sokha,012345678,,sokha@test.com,,Borey Piphup Thmey,Building B,Phnom Penh,Phnom Penh,Cambodia,12000,VIP Customer\n"
            "TEST_CUST_002,Ms. Chanthou,098765432,,chanthou@test.com,,Street 271,,Phnom Penh,Phnom Penh,Cambodia,12000,Retail Store\n"
        ).encode('utf-8')

        # 1. Preview
        preview_res = preview_import_data('customer', csv_data, has_headers=True, import_mode='keep', branch_id=self.branch_id)
        self.assertEqual(preview_res['total_rows'], 2)
        self.assertEqual(preview_res['data_type'], 'customer')
        self.assertIsNone(preview_res.get('orders_summary'), "Customer preview must not have orders_summary")

        # Snapshot product count to ensure Product Catalog Protection rule
        prod_count_before = query_one("SELECT COUNT(*) as c FROM products;")['c']

        # 2. Execute import under 'keep' mode for selected branch
        exec_res = execute_import_data(
            'customer', csv_data,
            has_headers=True,
            import_mode='keep',
            branch_id=self.branch_id
        )

        self.assertTrue(exec_res['success'])
        self.assertEqual(exec_res['imported'], 2)
        self.assertEqual(exec_res['updated'], 0)

        # 3. Verify customers were saved with target branch_id
        c1 = query_one("SELECT * FROM customers WHERE name = 'TEST_CUST_001';")
        self.assertIsNotNone(c1)
        self.assertEqual(c1['branch_id'], self.branch_id)
        self.assertEqual(c1['contact_name'], 'Mr. Sokha')
        self.assertEqual(c1['phone'], '012345678')
        self.assertEqual(c1['address1'], 'Borey Piphup Thmey')
        self.assertEqual(c1['address2'], 'Building B')
        self.assertEqual(c1['city'], 'Phnom Penh')
        self.assertEqual(c1['remarks'], 'VIP Customer')

        c2 = query_one("SELECT * FROM customers WHERE name = 'TEST_CUST_002';")
        self.assertIsNotNone(c2)
        self.assertEqual(c2['branch_id'], self.branch_id)

        # 4. Verify update under 'keep' mode
        update_csv = (
            "Name,ContactName,Phone,Fax,Email,Website,Address1,Address2,City,State,Country,PostalCode,Remarks\n"
            "TEST_CUST_001,Mr. Sokha Updated,012999888,,sokha_new@test.com,,New Villa 12,,Phnom Penh,Phnom Penh,Cambodia,12000,Updated VIP\n"
        ).encode('utf-8')

        exec_res_upd = execute_import_data(
            'customer', update_csv,
            has_headers=True,
            import_mode='keep',
            branch_id=self.branch_id
        )

        self.assertTrue(exec_res_upd['success'])
        self.assertEqual(exec_res_upd['imported'], 0)
        self.assertEqual(exec_res_upd['updated'], 1)

        c1_upd = query_one("SELECT * FROM customers WHERE name = 'TEST_CUST_001';")
        self.assertEqual(c1_upd['branch_id'], self.branch_id)
        self.assertEqual(c1_upd['contact_name'], 'Mr. Sokha Updated')
        self.assertEqual(c1_upd['phone'], '012999888')
        self.assertEqual(c1_upd['address1'], 'New Villa 12')
        self.assertEqual(c1_upd['remarks'], 'Updated VIP')

        # 5. Product Catalog Protection: ZERO product mutations
        prod_count_after = query_one("SELECT COUNT(*) as c FROM products;")['c']
        self.assertEqual(prod_count_before, prod_count_after, "Product catalog must never be mutated during customer import")

if __name__ == '__main__':
    unittest.main()
