import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import query_one, query_all, execute, init_db

class TestDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_schema_tables_exist(self):
        """Verify that all core tables exist in PostgreSQL"""
        tables = query_all("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        table_names = [t['tablename'] for t in tables]
        expected_tables = [
            'companies', 'categories', 'locations', 'sublocations', 'pricing_schemes',
            'products', 'product_prices', 'inventory', 'inventory_logs',
            'customers', 'vendors', 'sales_orders', 'sales_order_lines',
            'purchase_orders', 'purchase_order_lines', 'stock_transfers',
            'stock_transfer_lines', 'stock_adjustments', 'stock_adjustment_lines'
        ]
        for et in expected_tables:
            self.assertIn(et, table_names, f"Expected table {et} not found in database")

    def test_unicode_khmer_support(self):
        """Verify that Khmer Unicode text inserts, retrieves, and updates without corruption"""
        khmer_name = "តេស្តប្រអប់បាយ 500 pcs/Case"
        test_sku = "TEST-KHMER-001"
        
        # Clean up if existed
        execute("DELETE FROM products WHERE sku = %s", (test_sku,))

        execute("""
            INSERT INTO products (sku, name, default_price)
            VALUES (%s, %s, 19.99);
        """, (test_sku, khmer_name))

        prod = query_one("SELECT name, default_price FROM products WHERE sku = %s", (test_sku,))
        self.assertIsNotNone(prod)
        self.assertEqual(prod['name'], khmer_name)
        self.assertEqual(float(prod['default_price']), 19.99)

        # Clean up
        execute("DELETE FROM products WHERE sku = %s", (test_sku,))

if __name__ == '__main__':
    unittest.main()
