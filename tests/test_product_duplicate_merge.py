import unittest
import sys
sys.path.insert(0, '.')
from app import app
from database import query_one, query_all, execute, get_db_cursor
from services.product_merge import clean_text, calculate_similarity, execute_product_merge, find_duplicate_groups, search_products_for_merge

class TestProductDuplicateMerge(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_clean_text_khmer_and_english(self):
        # 1. Zero-width space removal
        text_with_zwsp = "ភ្នំពេញ\u200b សូរិយា"
        cleaned = clean_text(text_with_zwsp)
        self.assertNotIn('\u200b', cleaned)
        self.assertEqual(cleaned, "ភ្នំពេញ សូរិយា")

        # 2. Packaging units normalized
        text_pkg1 = "ដបមូលកធំ (Roud Bottle 500 ml) 200ដប/ដុំ"
        text_pkg2 = "ដបមូលកធំ (Roud Bottle 500 ml)"
        c1 = clean_text(text_pkg1)
        c2 = clean_text(text_pkg2)
        self.assertEqual(c1, c2)

    def test_calculate_similarity_high_match(self):
        p1 = {'name': 'ដបមូលកធំ (Roud Bottle 500 ml) 200ដប/ដុំ', 'sku': 'SKU-001'}
        p2 = {'name': 'ដបមូលកធំ (Roud Bottle 500 ml)', 'sku': 'PR0006'}
        sim = calculate_similarity(p1, p2)
        self.assertGreaterEqual(sim, 0.90)

    def test_calculate_similarity_different_sizes_lowered(self):
        # 500ml vs 1000ml are distinct products and should not have high similarity
        p1 = {'name': 'ដបមូល 500ml (Round Bottle 500ml)', 'sku': 'BOT-500'}
        p2 = {'name': 'ដបមូល 1000ml (Round Bottle 1000ml)', 'sku': 'BOT-1000'}
        sim = calculate_similarity(p1, p2)
        self.assertLess(sim, 0.50)

    def test_merge_duplicates_view_status_200(self):
        res = self.client.get('/products/merge-duplicates')
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn('Merge Duplicate Products', content)
        self.assertIn('Safe Duplicate Product Consolidation Engine', content)

    def test_api_duplicate_candidates(self):
        res = self.client.get('/api/products/duplicate-candidates?threshold=0.85&limit=5')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('groups', data)

    def test_api_search_for_merge(self):
        res = self.client.get('/api/products/search-for-merge?q=ដប')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('results', data)

    def test_execute_product_merge_relinks_so_po_and_consolidates_inventory(self):
        """
        Verify that merging product B into product A:
        1. Mixes sales order lines into product A without deleting any sales orders.
        2. Mixes purchase order lines into product A without deleting any purchase orders.
        3. Consolidates stock quantities across locations.
        4. Cleans up product B.
        """
        with get_db_cursor(commit=True) as cur:
            # 1. Create Master Product A
            cur.execute("""
                INSERT INTO products (sku, name, default_price, standard_cost, is_active)
                VALUES ('MERGE-TEST-A', 'Master Bottle Product 500ml', 1.50, 0.80, TRUE)
                RETURNING id
            """)
            master_id = cur.fetchone()['id']

            # 2. Create Duplicate Product B
            cur.execute("""
                INSERT INTO products (sku, name, barcode, default_price, standard_cost, is_active)
                VALUES ('MERGE-TEST-B', 'Master Bottle Product 500ml (Duplicate)', '8850012345', 1.50, 0.80, TRUE)
                RETURNING id
            """)
            dup_id = cur.fetchone()['id']

            # 3. Create dummy sales order
            cur.execute("""
                INSERT INTO sales_orders (order_number, order_date, status, payment_status, total_amount, balance_due)
                VALUES ('SO-MERGE-TEST', CURRENT_DATE, 'OPEN', 'UNPAID', 30.00, 30.00)
                RETURNING id
            """)
            so_id = cur.fetchone()['id']

            # Create line for Product A and line for Product B
            cur.execute("""
                INSERT INTO sales_order_lines (sales_order_id, product_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, 10, 1.50, 15.00),
                       (%s, %s, 10, 1.50, 15.00)
            """, (so_id, master_id, so_id, dup_id))

            # 4. Create dummy purchase order
            cur.execute("""
                INSERT INTO purchase_orders (order_number, order_date, status, total_amount)
                VALUES ('PO-MERGE-TEST', CURRENT_DATE, 'ISSUED', 16.00)
                RETURNING id
            """)
            po_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO purchase_order_lines (purchase_order_id, product_id, quantity, unit_cost, subtotal)
                VALUES (%s, %s, 20, 0.80, 16.00)
            """, (po_id, dup_id))

            # 5. Create inventory records
            cur.execute("""
                INSERT INTO inventory (product_id, location_id, quantity)
                VALUES (%s, 100, 50),
                       (%s, 100, 30)
            """, (master_id, dup_id))

        try:
            # Execute merge via service
            result = execute_product_merge(master_id, [dup_id])
            self.assertTrue(result['success'])
            self.assertEqual(result['master_id'], master_id)
            self.assertEqual(result['sales_orders_relinked'], 1)
            self.assertEqual(result['purchase_orders_relinked'], 1)
            self.assertEqual(result['stock_units_consolidated'], 30.0)

            # Verify Sales Order still exists with 2 lines, BOTH pointing to master_id
            so_check = query_one("SELECT * FROM sales_orders WHERE id = %s", (so_id,))
            self.assertIsNotNone(so_check, "Sales order must NOT be deleted!")
            lines = query_all("SELECT product_id, quantity, subtotal FROM sales_order_lines WHERE sales_order_id = %s", (so_id,))
            self.assertEqual(len(lines), 2)
            for line in lines:
                self.assertEqual(line['product_id'], master_id, "All lines must now point to master_id")

            # Verify Purchase Order still exists and line points to master_id
            po_check = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
            self.assertIsNotNone(po_check, "Purchase order must NOT be deleted!")
            po_lines = query_all("SELECT product_id, quantity FROM purchase_order_lines WHERE purchase_order_id = %s", (po_id,))
            self.assertEqual(len(po_lines), 1)
            self.assertEqual(po_lines[0]['product_id'], master_id)

            # Verify consolidated inventory: 50 + 30 = 80 units
            inv_check = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = 100", (master_id,))
            self.assertEqual(float(inv_check['quantity']), 80.0)

            # Verify duplicate product B is deleted from products
            dup_check = query_one("SELECT id FROM products WHERE id = %s", (dup_id,))
            self.assertIsNone(dup_check, "Duplicate product B should be removed from products table")

            # Verify master product has merged barcode or notes
            master_check = query_one("SELECT barcode, remarks FROM products WHERE id = %s", (master_id,))
            self.assertIn('8850012345', (master_check['barcode'] or '') + (master_check['remarks'] or ''))

        finally:
            # Clean up dummy test data
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = %s", (so_id,))
                cur.execute("DELETE FROM sales_orders WHERE id = %s", (so_id,))
                cur.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = %s", (po_id,))
                cur.execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
                cur.execute("DELETE FROM inventory WHERE product_id IN (%s, %s)", (master_id, dup_id))
                cur.execute("DELETE FROM products WHERE id IN (%s, %s)", (master_id, dup_id))

if __name__ == '__main__':
    unittest.main()
