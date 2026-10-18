import io
import json
import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from services.csv_exchange import (
    resolve_order_line_uom,
    preview_import_data,
    execute_import_data,
    build_product_matcher,
    match_catalog_product
)


class TestImportUomAndProductReplacement(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_uom_pcs_is_never_overridden_by_contextual_case_detection(self):
        """
        Verify that explicit 'pcs' or 'pc' is NEVER converted to 'cases',
        even when product has case packaging (e.g. 500 pcs/case) and unit price is high.
        """
        mock_p = {
            'id': 101,
            'sku': 'BOX-01',
            'name': 'Lunch Box 500 pcs/case',
            'default_price': 25.0,
            'sales_uom': 'cases',
            'sales_uom_ratio_std': 500.0,
            'uom': 'pcs.'
        }
        # Order line says: 50 pcs at $0.05 or $15.00
        uom, disp_qty, std_qty = resolve_order_line_uom(
            raw_uom='pcs',
            item_name='Lunch Box 500 pcs/case',
            desc='(500/case)',
            p_info=mock_p,
            unit_price=15.0,
            qty=50.0
        )
        self.assertEqual(uom, 'pcs.')
        self.assertEqual(disp_qty, 50.0)
        self.assertEqual(std_qty, 50.0)

        # Also test 'pc' and 'pieces'
        uom2, disp2, std2 = resolve_order_line_uom('pc', 'Box', '', mock_p, 10.0, 10.0)
        self.assertEqual(uom2, 'pcs.')
        self.assertEqual(std2, 10.0)

    def test_uom_ea_is_preserved_as_ea(self):
        """Verify that explicit 'ea' or 'ea.' remains 'ea.' with ratio 1.0"""
        mock_p = {
            'id': 102,
            'sku': 'SHIRT-M',
            'name': 'T-Shirt',
            'default_price': 12.0,
            'sales_uom': 'cases',
            'sales_uom_ratio_std': 24.0,
            'uom': 'pcs.'
        }
        uom, disp_qty, std_qty = resolve_order_line_uom('ea', 'T-Shirt', '', mock_p, 12.0, 3.0)
        self.assertEqual(uom, 'ea.')
        self.assertEqual(disp_qty, 3.0)
        self.assertEqual(std_qty, 3.0)

        uom2, disp2, std2 = resolve_order_line_uom('ea.', 'T-Shirt', '', mock_p, 12.0, 2.0)
        self.assertEqual(uom2, 'ea.')
        self.assertEqual(disp2, 2.0)
        self.assertEqual(std2, 2.0)

    def test_uom_case_and_box_converted_with_ratio(self):
        """Verify that explicit case/cases/box converts standard inventory qty using ratio"""
        mock_p = {
            'id': 103,
            'sku': 'CUP-100',
            'name': 'Paper Cup 1000/case',
            'default_price': 30.0,
            'sales_uom': 'cases',
            'sales_uom_ratio_std': 1000.0,
            'uom': 'pcs.'
        }
        # Explicit 'case'
        uom, disp_qty, std_qty = resolve_order_line_uom('case', 'Paper Cup', '', mock_p, 30.0, 2.0)
        self.assertEqual(uom, 'cases')
        self.assertEqual(disp_qty, 2.0)
        self.assertEqual(std_qty, 2000.0)

        # Explicit 'box'
        uom2, disp2, std2 = resolve_order_line_uom('box', 'Paper Cup', '', mock_p, 30.0, 3.0)
        self.assertEqual(uom2, 'box')
        self.assertEqual(disp2, 3.0)
        self.assertEqual(std_qty, 2000.0)
        self.assertEqual(std2, 3000.0)

    def test_uom_custom_other_preserved_literally(self):
        """Verify that custom/other UOMs like roll, set, bottle, kg are preserved literally"""
        mock_p = {
            'id': 104,
            'sku': 'TAPE-01',
            'name': 'Packing Tape',
            'default_price': 1.5,
            'sales_uom': '',
            'sales_uom_ratio_std': 1.0,
            'uom': 'pcs.'
        }
        uom, disp_qty, std_qty = resolve_order_line_uom('roll', 'Packing Tape', '', mock_p, 1.5, 12.0)
        self.assertEqual(uom, 'roll')
        self.assertEqual(disp_qty, 12.0)
        self.assertEqual(std_qty, 12.0)

    def test_preview_detects_unmatched_products(self):
        """Verify preview_import_data returns unmatched_products and catalog_products"""
        csv_content = (
            "OrderNumber,OrderDate,Customer,ItemCode,ItemName,ItemQuantity,ItemUnitPrice,ItemSubtotal,ItemQuantityUOM\n"
            "SO-101,2026-03-01,Customer A,SKU-FOUND,Existing Product,5,2.00,10.00,pcs\n"
            "SO-101,2026-03-01,Customer A,SKU-UNKNOWN-99,Brand New Mystery Item,2,15.00,30.00,case\n"
        ).encode('utf-8')

        with patch('services.csv_exchange.query_all') as mock_qa:
            def side_effect(query, params=None):
                q = query.lower()
                if 'from products' in q:
                    return [
                        {
                            'id': 1,
                            'sku': 'SKU-FOUND',
                            'name': 'Existing Product',
                            'default_price': 2.0,
                            'standard_cost': 1.0,
                            'average_cost': 1.0,
                            'uom': 'pcs.',
                            'sales_uom': 'pcs.',
                            'sales_uom_ratio_std': 1.0,
                            'purchasing_uom': 'pcs.',
                            'purchasing_uom_ratio_std': 1.0,
                            'packs_per_case': None,
                            'pcs_per_pack': None
                        },
                        {
                            'id': 2,
                            'sku': 'SKU-ALT',
                            'name': 'Alternative Product',
                            'default_price': 15.0,
                            'standard_cost': 10.0,
                            'average_cost': 10.0,
                            'uom': 'pcs.',
                            'sales_uom': 'cases',
                            'sales_uom_ratio_std': 50.0,
                            'purchasing_uom': 'pcs.',
                            'purchasing_uom_ratio_std': 1.0,
                            'packs_per_case': None,
                            'pcs_per_pack': None
                        }
                    ]
                if 'from sales_orders' in q:
                    return []
                return []
            mock_qa.side_effect = side_effect

            res = preview_import_data('sales_order', csv_content, has_headers=True)
            self.assertIn('unmatched_products', res)
            self.assertIn('catalog_products', res)

            unmatched = res['unmatched_products']
            self.assertEqual(len(unmatched), 1)
            self.assertEqual(unmatched[0]['item_code'], 'SKU-UNKNOWN-99')
            self.assertEqual(unmatched[0]['item_name'], 'Brand New Mystery Item')

            cat_prods = res['catalog_products']
            self.assertEqual(len(cat_prods), 2)
            self.assertTrue(any(p['id'] == 2 for p in cat_prods))

    def test_execute_import_data_applies_product_replacement(self):
        """Verify execute_import_data replaces unmatched product with mapped catalog product"""
        csv_content = (
            "OrderNumber,OrderDate,Customer,ItemCode,ItemName,ItemQuantity,ItemUnitPrice,ItemSubtotal,ItemQuantityUOM\n"
            "SO-999,2026-03-01,Test Customer,OLD-CODE,Discontinued Item,4,10.00,40.00,pcs\n"
        ).encode('utf-8')

        with patch('services.csv_exchange.query_all') as mock_qa, \
             patch('services.csv_exchange.query_one') as mock_qo, \
             patch('services.csv_exchange.get_db_cursor') as mock_cursor, \
             patch('services.csv_exchange.resync_all_sequences'):

            def side_effect(query, params=None):
                q = query.lower()
                if 'from products' in q:
                    return [
                        {
                            'id': 88,
                            'sku': 'NEW-REPLACEMENT',
                            'name': 'Replaced Modern Item',
                            'default_price': 10.0,
                            'standard_cost': 6.0,
                            'average_cost': 6.0,
                            'uom': 'pcs.',
                            'sales_uom': 'pcs.',
                            'sales_uom_ratio_std': 1.0,
                            'purchasing_uom': 'pcs.',
                            'purchasing_uom_ratio_std': 1.0,
                            'packs_per_case': None,
                            'pcs_per_pack': None
                        }
                    ]
                if 'from customers' in q:
                    return [{'id': 5, 'name': 'Test Customer', 'contact_name': '', 'phone': '', 'default_addr': ''}]
                if 'from locations' in q:
                    return [{'id': 1, 'name': 'Default Location'}]
                return []
            mock_qa.side_effect = side_effect
            mock_qo.return_value = None

            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [
                None,          # SELECT id, branch_id FROM sales_orders (not existing)
                {'id': 123},   # INSERT INTO sales_orders RETURNING id
                None
            ]
            mock_cursor.return_value.__enter__.return_value = mock_cur

            # User mapped 'OLD-CODE:::Discontinued Item' -> 88
            replacements = {
                'OLD-CODE:::Discontinued Item': 88
            }

            res = execute_import_data(
                data_type='sales_order',
                file_content=csv_content,
                has_headers=True,
                import_mode='keep',
                product_replacements=replacements
            )

            self.assertTrue(res['success'])
            self.assertEqual(res['imported'], 1)

            # Check lines inserted into sales_order_lines
            line_insert_call = None
            for call in mock_cur.execute.call_args_list:
                args, _ = call
                if args and 'INSERT INTO sales_order_lines' in args[0]:
                    line_insert_call = args
                    break

            self.assertIsNotNone(line_insert_call)
            params = line_insert_call[1]
            # Params: (so_id, l_idx, pline['prod_id'], pline['desc'], pline['std_qty'], pline['unit_price'], ...)
            so_id, line_num, prod_id, desc, std_qty, unit_p, disc, sub, cost, uom, disp_qty = params
            self.assertEqual(prod_id, 88)
            self.assertEqual(uom, 'pcs.')
            self.assertEqual(disp_qty, 4.0)
            self.assertEqual(std_qty, 4.0)


if __name__ == '__main__':
    unittest.main()
