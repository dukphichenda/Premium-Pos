import io
import unittest
from unittest.mock import patch
from app import create_app
from services.csv_exchange import preview_import_data, execute_import_data, build_product_matcher, match_catalog_product

class TestSaleCsvImportNoCreateProduct(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_matcher_matches_sku_and_name_variations(self):
        mock_products = [
            {
                'id': 101,
                'sku': 'HT17-1-TTK',
                'name': 'ប្រអប់បាយ1ថត 500ចាន/កេស',
                'default_price': 15.0,
                'standard_cost': 10.0,
                'sales_uom': 'cases',
                'sales_uom_ratio_std': 500.0,
                'uom': 'pcs.'
            },
            {
                'id': 457,
                'sku': 'LB A4',
                'name': 'ប្រអប់ភ្លើង',
                'default_price': 25.0,
                'standard_cost': 18.0,
                'sales_uom': 'pcs.',
                'sales_uom_ratio_std': 1.0,
                'uom': 'pcs.'
            }
        ]
        matcher = build_product_matcher(mock_products)

        # 1. Match by SKU
        p1 = match_catalog_product(matcher, item_code='HT17-1-TTK', item_name='')
        self.assertIsNotNone(p1)
        self.assertEqual(p1['id'], 101)

        # 2. Match by clean Name
        p2 = match_catalog_product(matcher, item_code='', item_name='ប្រអប់បាយ1ថត 500ចាន/កេស')
        self.assertIsNotNone(p2)
        self.assertEqual(p2['id'], 101)

        # 3. Match by old combined (SKU + Name) in ItemName column
        p3 = match_catalog_product(matcher, item_code='', item_name='HT17-1-TTK ប្រអប់បាយ1ថត 500ចាន/កេស')
        self.assertIsNotNone(p3)
        self.assertEqual(p3['id'], 101)

        # 4. Match by both ItemCode and ItemName
        p4 = match_catalog_product(matcher, item_code='HT17-1-TTK', item_name='ប្រអប់បាយ1ថត 500ចាន/កេស')
        self.assertIsNotNone(p4)
        self.assertEqual(p4['id'], 101)

        # 5. Non-existent product returns None (never auto-creates)
        p5 = match_catalog_product(matcher, item_code='UNKNOWN-999', item_name='Random Nonexistent Item')
        self.assertIsNone(p5)

    def test_execute_import_sales_never_creates_product_and_no_description(self):
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price
SO-99901,2026-10-14,Test Cust,OPEN,HT17-1-TTK ប្រអប់បាយ1ថត 500ចាន/កេស,2,15.00
SO-99901,2026-10-14,Test Cust,OPEN,Nonexistent Item 123,1,10.00
"""
        mock_products = [
            {
                'id': 101,
                'sku': 'HT17-1-TTK',
                'name': 'ប្រអប់បាយ1ថត 500ចាន/កេស',
                'default_price': 15.0,
                'standard_cost': 10.0,
                'average_cost': 10.0,
                'sales_uom': 'cases',
                'sales_uom_ratio_std': 500.0,
                'uom': 'pcs.'
            }
        ]

        inserted_lines = []
        product_inserts = []

        def mock_query_all(sql, params=None):
            if 'FROM products' in sql:
                return mock_products
            if 'FROM customers' in sql:
                return [{'id': 1, 'name': 'Test Cust'}]
            if 'FROM locations' in sql:
                return [{'id': 1, 'name': 'Main Warehouse'}]
            return []

        def mock_query_one(sql, params=None):
            return None

        class MockCursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, sql, params=None):
                if 'INSERT INTO products' in sql:
                    product_inserts.append((sql, params))
                elif 'INSERT INTO sales_order_lines' in sql:
                    inserted_lines.append(params)
            def fetchone(self):
                return {'id': 999}
            def fetchall(self):
                return []
            @property
            def connection(self):
                class DummyConn:
                    def commit(self): pass
                return DummyConn()

        with patch('services.csv_exchange.query_all', side_effect=mock_query_all), \
             patch('services.csv_exchange.query_one', side_effect=mock_query_one), \
             patch('services.csv_exchange.get_db_cursor', return_value=MockCursor()):

            res = execute_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertTrue(res['success'])
        # CRITICAL ASSERTION 1: No product should EVER be inserted
        self.assertEqual(len(product_inserts), 0, "No new product should be inserted during sales order import!")

        # CRITICAL ASSERTION 2: Matched product line must have description = None
        self.assertEqual(len(inserted_lines), 2)
        so_id1, line_num1, prod_id1, desc1, std_qty1, unit_price1, discount1, subtotal1, cost_price1, uom1, disp_qty1, *extra1 = inserted_lines[0]
        self.assertEqual(prod_id1, 101, "Matched product should have prod_id = 101")
        self.assertIsNone(desc1, "Matched product line should have description = None (no need description)")

        # Unmatched line has prod_id = None
        so_id2, line_num2, prod_id2, desc2, std_qty2, unit_price2, discount2, subtotal2, cost_price2, uom2, disp_qty2, *extra2 = inserted_lines[1]
        self.assertIsNone(prod_id2, "Unmatched item should have prod_id = None")
        self.assertEqual(desc2, "Nonexistent Item 123")

if __name__ == '__main__':
    unittest.main()
