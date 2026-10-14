import unittest
import sys
sys.path.insert(0, '.')
from services.product_merge import (
    clean_text,
    calculate_similarity,
    find_duplicate_groups,
    execute_product_merge,
    bulk_merge_all_duplicates
)
from database import query_one, query_all, execute, execute_returning_id
from app import app


class TestBulkMergeCategory(unittest.TestCase):
    def setUp(self):
        execute("DELETE FROM sales_order_lines WHERE product_id IN (SELECT id FROM products WHERE sku IN ('TST-MST-01', 'TST-DUP-01'))")
        execute("DELETE FROM products WHERE sku IN ('TST-MST-01', 'TST-DUP-01')")
        execute("DELETE FROM categories WHERE name = 'Test Merge Category'")

    def test_variant_conflict_differentiation(self):
        """
        Verify that distinct product variants (black vs clear, with lid vs no lid,
        different sizes/models) are NOT treated as duplicates (similarity < 0.20).
        """
        p_black = {'name': 'UKP90-500PP-C-T (BLACK)', 'sku': 'UKP90-500PP-C-T-BLACK'}
        p_clear = {'name': 'UKP90-500PP-C-T (CLEAR)', 'sku': 'UKP90-500PP-C-T-CLEAR'}
        self.assertLess(calculate_similarity(p_black, p_clear), 0.20)

        p_lid = {'name': 'N3500G-QP ប្រអប់ញ៉ូម មានគម្រប 3500ml', 'sku': 'N3500G'}
        p_nolid = {'name': 'N3500G-Nolid-QP ប្រអប់ញ៉ូម អត់គម្រប 3500ml', 'sku': 'N3500G-NOLID'}
        self.assertLess(calculate_similarity(p_lid, p_nolid), 0.20)

        p_size1 = {'name': 'HNF កែវកាហ្វេក្តៅ 1000ml', 'sku': 'HNF1000'}
        p_size2 = {'name': 'HNF កែវកាហ្វេក្តៅ 500ml', 'sku': 'HNF500'}
        self.assertLess(calculate_similarity(p_size1, p_size2), 0.20)

        p_tray1 = {'name': 'QP ប្រអប់កាកអំពៅ 1ថត', 'sku': 'QP-1T'}
        p_tray2 = {'name': 'QP ប្រអប់កាកអំពៅ 2ថត', 'sku': 'QP-2T'}
        self.assertLess(calculate_similarity(p_tray1, p_tray2), 0.20)

    def test_true_duplicate_matching(self):
        """
        Verify that true duplicate representations (e.g. master with pack count in title
        vs quick sales item without pack count) have high similarity >= 0.85.
        """
        p1 = {'name': 'SPOON-TL ស្លាបព្រា វែង/ LONG SPOON 5000pcs/Case', 'sku': 'SPOON-TL'}
        p2 = {'name': 'TL ស្លាបព្រា វែង/ LONG SPOON', 'sku': 'TL-Spoon'}
        self.assertGreaterEqual(calculate_similarity(p1, p2), 0.85)

        p3 = {'name': 'ST02-JB ប្រអប់ស៊ូស៊ី Shushi Box 1000ប្រអប់/កេស', 'sku': 'ST02-JB'}
        p4 = {'name': 'JB ប្រអប់ស៊ូស៊ី Shushi Box ST02- 100pcs', 'sku': 'JB_ST02'}
        self.assertGreaterEqual(calculate_similarity(p3, p4), 0.85)

    def test_merge_preserves_orders_and_deletes_duplicate(self):
        """
        Create a test category, master product, and non-category duplicate product with orders
        from both HQ and branch. Verify merge re-links both orders to master and deletes duplicate.
        """
        # 1. Create test category
        cat_id = execute_returning_id("INSERT INTO categories (name) VALUES ('Test Merge Category') RETURNING id;")

        # 2. Create master product (with category)
        master_id = execute_returning_id("""
            INSERT INTO products (name, sku, category_id, default_price, is_active)
            VALUES ('Test Master Cup 500ML', 'TST-MST-01', %s, 10.00, TRUE)
            RETURNING id;
        """, (cat_id,))

        # 3. Create duplicate product (WITHOUT category)
        dup_id = execute_returning_id("""
            INSERT INTO products (name, sku, category_id, default_price, is_active)
            VALUES ('Test Master Cup 500ML (50pcs)', 'TST-DUP-01', NULL, 10.00, TRUE)
            RETURNING id;
        """)

        # 4. Create customer for order testing
        cust_id = query_one("SELECT id FROM customers LIMIT 1;")
        if cust_id:
            c_id = cust_id['id']
        else:
            c_id = execute_returning_id("INSERT INTO customers (name) VALUES ('Merge Test Customer') RETURNING id;")

        # 5. Create HQ Sales Order & line referencing dup_id
        so_hq_id = execute_returning_id("""
            INSERT INTO sales_orders (order_number, customer_id, branch_id, status, total_amount)
            VALUES ('SO-TEST-HQ-01', %s, NULL, 'Completed', 50.00)
            RETURNING id;
        """, (c_id,))
        sol_hq_id = execute_returning_id("""
            INSERT INTO sales_order_lines (sales_order_id, product_id, quantity, unit_price, subtotal)
            VALUES (%s, %s, 5, 10.00, 50.00)
            RETURNING id;
        """, (so_hq_id, dup_id))

        # 6. Create Branch Sales Order & line referencing dup_id
        so_branch_id = execute_returning_id("""
            INSERT INTO sales_orders (order_number, customer_id, branch_id, status, total_amount)
            VALUES ('SO-TEST-BR-01', %s, 1, 'Completed', 30.00)
            RETURNING id;
        """, (c_id,))
        sol_br_id = execute_returning_id("""
            INSERT INTO sales_order_lines (sales_order_id, product_id, quantity, unit_price, subtotal)
            VALUES (%s, %s, 3, 10.00, 30.00)
            RETURNING id;
        """, (so_branch_id, dup_id))

        # 7. Execute merge
        res = execute_product_merge(master_id, [dup_id])
        self.assertTrue(res['success'])
        self.assertEqual(res['sales_orders_relinked'], 2)

        # 8. Verify sales order lines from BOTH HQ and Branch now reference master_id
        sol_hq_updated = query_one("SELECT product_id FROM sales_order_lines WHERE id = %s", (sol_hq_id,))
        sol_br_updated = query_one("SELECT product_id FROM sales_order_lines WHERE id = %s", (sol_br_id,))
        self.assertEqual(sol_hq_updated['product_id'], master_id)
        self.assertEqual(sol_br_updated['product_id'], master_id)

        # 9. Verify duplicate product was permanently deleted
        deleted_dup = query_one("SELECT id FROM products WHERE id = %s", (dup_id,))
        self.assertIsNone(deleted_dup)

        # 10. Verify master product kept its category
        master_updated = query_one("SELECT category_id FROM products WHERE id = %s", (master_id,))
        self.assertEqual(master_updated['category_id'], cat_id)

        # Clean up test rows
        execute("DELETE FROM sales_order_lines WHERE id IN (%s, %s)", (sol_hq_id, sol_br_id))
        execute("DELETE FROM sales_orders WHERE id IN (%s, %s)", (so_hq_id, so_branch_id))
        execute("DELETE FROM products WHERE id = %s", (master_id,))
        execute("DELETE FROM categories WHERE id = %s", (cat_id,))

    def test_bulk_merge_all_endpoint(self):
        """
        Verify that /api/products/bulk-merge-all executes successfully, returns JSON
        with counts of merged groups, deleted products, and relinked orders.
        """
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        resp = client.post('/api/products/bulk-merge-all', json={
            'threshold': 0.85,
            'only_category_master': False
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('merged_groups_count', data)
        self.assertIn('deleted_products_count', data)
        self.assertIn('total_sales_orders_relinked', data)


if __name__ == '__main__':
    unittest.main()
