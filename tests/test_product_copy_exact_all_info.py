import unittest
import json
from app import create_app
from database import query_one, query_all, execute, execute_returning_id
from psycopg2.extras import Json

class ProductCopyExactAllInfoTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'Admin'

        # Create vendor for testing
        vend = query_one("SELECT id FROM vendors LIMIT 1")
        if not vend:
            self.vend_id = execute_returning_id("INSERT INTO vendors (name) VALUES ('Test Vendor Copy') RETURNING id;")
        else:
            self.vend_id = vend['id']

        # Create a component product for BOM testing
        comp = query_one("SELECT id FROM products WHERE sku = 'COMP-PART-01'")
        if not comp:
            self.comp_id = execute_returning_id("INSERT INTO products (sku, name, default_price, standard_cost) VALUES ('COMP-PART-01', 'Component Part 1', 5.0, 3.0) RETURNING id;")
        else:
            self.comp_id = comp['id']

    def tearDown(self):
        # Cleanup
        for p in query_all("SELECT id FROM products WHERE sku LIKE 'TEST-COPY-%%'"):
            pid = p['id']
            execute("DELETE FROM product_versions WHERE product_id = %s", (pid,))
            execute("DELETE FROM product_prices WHERE product_id = %s", (pid,))
            execute("DELETE FROM product_vendors WHERE product_id = %s", (pid,))
            execute("DELETE FROM product_boms WHERE product_id = %s", (pid,))
            execute("DELETE FROM product_attachments WHERE product_id = %s", (pid,))
            execute("DELETE FROM product_combine_options WHERE product_id = %s", (pid,))
            execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
            execute("DELETE FROM products WHERE id = %s", (pid,))

    def test_copy_standalone_product_exact_all_info(self):
        """Verify that copying a standalone product preserves exact all specs, dimensions, packaging, pricing tiers, and costing sheet formulas"""
        prod_id = execute_returning_id("""
            INSERT INTO products (
                sku, name, description, barcode, uom,
                master_pack_qty, inner_pack_qty,
                reorder_point, reorder_quantity, min_stock, max_stock,
                standard_cost, average_cost, last_purchase_cost, default_price,
                is_sellable, is_purchaseable, is_active,
                item_type, tax_code, costing_method, image_url,
                custom1, custom2, custom3, custom4, custom5,
                default_sublocation, last_vendor_id,
                sales_uom, sales_uom_ratio, sales_uom_ratio_std,
                purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
                length, width, height, weight, remarks,
                price_decimals, cost_decimals, qty_decimals,
                brand, color, country_of_origin, material, whmis_number, scent,
                capacity, amps, warranty_expiry, qa_passed, custom_attributes,
                packs_per_case, pcs_per_pack,
                tier_qty_1, tier_qty_2, tier_qty_3,
                tier_price_1, tier_price_2, tier_price_3,
                price_card_notes, price_card_color, price_card_font,
                price_card_unit, price_card_custom_detail, price_card_is_custom_detail,
                cost_formula, factory_cost, factory_cost_formula,
                cost_rate, cost_rate_formula,
                shipping_cost, shipping_cost_formula,
                costing_sheet_pcs, costing_sheet_pcs_formula,
                costing_sheet_cost, costing_sheet_formula,
                combine_type
            ) VALUES (
                'TEST-COPY-STANDALONE', 'Eco Kraft Bowl 750ml / Brown', 'Full description with specs', '8859912345678', 'cases',
                20.0, 5.0,
                50.0, 100.0, 10.0, 500.0,
                15.50, 15.20, 15.00, 25.00,
                TRUE, TRUE, TRUE,
                'Stockable', 'Standard', 'Average', '/static/uploads/products/sample.png',
                'CustVal1', 'CustVal2', 'CustVal3', 'CustVal4', 'CustVal5',
                'Shelf-A2', %s,
                'cases', 1.0, 500.0,
                'cases', 1.0, 500.0,
                32.5, 24.0, 18.5, 1.25, 'Fragile - handle with care',
                2, 4, 0,
                'MasterBrand', 'Kraft Brown', 'Cambodia', 'Kraft Paper', 'WHMIS-99', 'Natural',
                '750 ml', 'N/A', '12 Months', TRUE, %s,
                10.0, 50.0,
                50, 100, 200,
                24.00, 22.50, 20.00,
                'Call for wholesale discounts', '#00A3E0', 'Kantumruy Pro',
                'Pack', '50 pcs per pack x 10 packs per case', TRUE,
                '0.04+0.01', 0.04, '0.03+0.01',
                4100.0, '4050+50',
                0.02, '0.015+0.005',
                500.0, '50*10',
                0.07, '0.04+0.02+0.01',
                'single'
            ) RETURNING id;
        """, (self.vend_id, Json({'origin_batch': 'B-2026', 'grade': 'A+'})))

        # Add price tiers (product_prices)
        scheme = query_one("SELECT id FROM pricing_schemes WHERE is_active = TRUE ORDER BY is_default DESC, id ASC LIMIT 1")
        if scheme:
            execute("INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price) VALUES (%s, %s, %s) ON CONFLICT (product_id, pricing_scheme_id) DO UPDATE SET unit_price = EXCLUDED.unit_price",
                    (prod_id, scheme['id'], 23.50))

        # Add vendor item
        execute("INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost) VALUES (%s, %s, %s, %s)",
                (prod_id, self.vend_id, 'VEND-CODE-XYZ', 14.75))

        # Add product attachment
        execute("INSERT INTO product_attachments (product_id, file_name, file_path, file_size) VALUES (%s, %s, %s, %s)",
                (prod_id, 'spec_sheet.pdf', '/static/uploads/attachments/sample.pdf', 1048576))

        res = self.client.get(f'/products/{prod_id}/copy', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        copied = query_one("SELECT * FROM products WHERE sku = 'TEST-COPY-STANDALONE-Copy'")
        self.assertIsNotNone(copied, "Copied product must exist with SKU TEST-COPY-STANDALONE-Copy")
        copied_id = copied['id']

        # 1. Basic & Identity
        self.assertEqual(copied['name'], 'Eco Kraft Bowl 750ml / Brown - Copy')
        self.assertEqual(copied['barcode'], '8859912345678')
        self.assertEqual(copied['description'], 'Full description with specs')
        self.assertEqual(copied['uom'], 'cases')
        self.assertEqual(copied['image_url'], '/static/uploads/products/sample.png')
        self.assertEqual(copied['combine_type'], 'single')

        # 2. Dimensions & Physical Specs
        self.assertEqual(float(copied['length']), 32.5)
        self.assertEqual(float(copied['width']), 24.0)
        self.assertEqual(float(copied['height']), 18.5)
        self.assertEqual(float(copied['weight']), 1.25)
        self.assertEqual(copied['brand'], 'MasterBrand')
        self.assertEqual(copied['color'], 'Kraft Brown')
        self.assertEqual(copied['country_of_origin'], 'Cambodia')
        self.assertEqual(copied['material'], 'Kraft Paper')
        self.assertEqual(copied['whmis_number'], 'WHMIS-99')
        self.assertEqual(copied['scent'], 'Natural')
        self.assertEqual(copied['capacity'], '750 ml')
        self.assertEqual(copied['warranty_expiry'], '12 Months')
        self.assertTrue(copied['qa_passed'])
        self.assertEqual(copied['remarks'], 'Fragile - handle with care')
        self.assertEqual(copied['custom_attributes'].get('origin_batch'), 'B-2026')

        # 3. Packaging & UOM Breakdown
        self.assertEqual(float(copied['packs_per_case']), 10.0)
        self.assertEqual(float(copied['pcs_per_pack']), 50.0)
        self.assertEqual(copied['sales_uom'], 'cases')
        self.assertEqual(float(copied['sales_uom_ratio_std']), 500.0)
        self.assertEqual(copied['purchasing_uom'], 'cases')
        self.assertEqual(float(copied['purchasing_uom_ratio_std']), 500.0)
        self.assertEqual(copied['default_sublocation'], 'Shelf-A2')
        self.assertEqual(copied['last_vendor_id'], self.vend_id)

        # 4. Pricing, Schemes & Tiers
        self.assertEqual(float(copied['default_price']), 25.00)
        self.assertEqual(copied['tier_qty_1'], 50)
        self.assertEqual(copied['tier_qty_2'], 100)
        self.assertEqual(copied['tier_qty_3'], 200)
        self.assertEqual(float(copied['tier_price_1']), 24.00)
        self.assertEqual(float(copied['tier_price_2']), 22.50)
        self.assertEqual(float(copied['tier_price_3']), 20.00)
        self.assertEqual(copied['price_card_notes'], 'Call for wholesale discounts')
        self.assertEqual(copied['price_card_color'], '#00A3E0')
        self.assertEqual(copied['price_card_font'], 'Kantumruy Pro')
        self.assertEqual(copied['price_card_unit'], 'Pack')
        self.assertEqual(copied['price_card_custom_detail'], '50 pcs per pack x 10 packs per case')
        self.assertTrue(copied['price_card_is_custom_detail'])

        # 5. Costing Sheet & Formulas
        self.assertEqual(copied['cost_formula'], '0.04+0.01')
        self.assertEqual(float(copied['factory_cost']), 0.04)
        self.assertEqual(copied['factory_cost_formula'], '0.03+0.01')
        self.assertEqual(float(copied['cost_rate']), 4100.0)
        self.assertEqual(copied['cost_rate_formula'], '4050+50')
        self.assertEqual(float(copied['shipping_cost']), 0.02)
        self.assertEqual(copied['shipping_cost_formula'], '0.015+0.005')
        self.assertEqual(float(copied['costing_sheet_pcs']), 500.0)
        self.assertEqual(copied['costing_sheet_pcs_formula'], '50*10')
        self.assertEqual(float(copied['costing_sheet_cost']), 0.07)
        self.assertEqual(copied['costing_sheet_formula'], '0.04+0.02+0.01')

        # 6. Decimals & Custom Fields
        self.assertEqual(copied['price_decimals'], 2)
        self.assertEqual(copied['cost_decimals'], 4)
        self.assertEqual(copied['qty_decimals'], 0)
        self.assertEqual(copied['custom1'], 'CustVal1')
        self.assertEqual(copied['custom2'], 'CustVal2')
        self.assertEqual(copied['custom3'], 'CustVal3')
        self.assertEqual(copied['custom4'], 'CustVal4')
        self.assertEqual(copied['custom5'], 'CustVal5')

        # 7. Child Records: Prices, Vendors, Attachments, Versions
        source_prices = query_all("SELECT pricing_scheme_id, unit_price FROM product_prices WHERE product_id = %s", (prod_id,))
        copied_prices = query_all("SELECT pricing_scheme_id, unit_price FROM product_prices WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(copied_prices), len(source_prices))
        for sp in source_prices:
            matching = [cp for cp in copied_prices if cp['pricing_scheme_id'] == sp['pricing_scheme_id']]
            self.assertEqual(len(matching), 1)
            self.assertEqual(float(matching[0]['unit_price']), float(sp['unit_price']))

        c_vendors = query_all("SELECT * FROM product_vendors WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(c_vendors), 1)
        self.assertEqual(c_vendors[0]['vendor_item_code'], 'VEND-CODE-XYZ')
        self.assertEqual(float(c_vendors[0]['cost']), 14.75)

        c_attach = query_all("SELECT * FROM product_attachments WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(c_attach), 1)
        self.assertEqual(c_attach[0]['file_name'], 'spec_sheet.pdf')
        self.assertEqual(c_attach[0]['file_path'], '/static/uploads/attachments/sample.pdf')

        c_vers = query_all("SELECT * FROM product_versions WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(c_vers), 1)
        self.assertEqual(c_vers[0]['version_number'], 1)

    def test_copy_bundle_product_with_boms_and_options(self):
        """Verify that copying a bundle product preserves BOM components and multi-product combine options"""
        bundle_id = execute_returning_id("""
            INSERT INTO products (sku, name, default_price, standard_cost, combine_type)
            VALUES ('TEST-COPY-BUNDLE', 'Eco Set Combo', 30.0, 15.0, 'multi')
            RETURNING id;
        """)

        # Add BOM
        execute("""
            INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
            VALUES (%s, %s, 'Base Component Part', 2.0, 3.0);
        """, (bundle_id, self.comp_id))

        # Add Combine Option
        execute("""
            INSERT INTO product_combine_options (
                product_id, option_name, component_product_id, component_quantity,
                price_modifier, selling_price, is_default, sort_order, notes
            ) VALUES (%s, 'With Plastic Lid', %s, 1.0, 1.5, 31.5, TRUE, 1, 'Clear PET lid');
        """, (bundle_id, self.comp_id))

        res = self.client.get(f'/products/{bundle_id}/copy', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        copied = query_one("SELECT * FROM products WHERE sku = 'TEST-COPY-BUNDLE-Copy'")
        self.assertIsNotNone(copied)
        copied_id = copied['id']

        # Verify BOM copied
        boms = query_all("SELECT * FROM product_boms WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(boms), 1)
        self.assertEqual(boms[0]['component_product_id'], self.comp_id)
        self.assertEqual(boms[0]['description'], 'Base Component Part')
        self.assertEqual(float(boms[0]['quantity']), 2.0)
        self.assertEqual(float(boms[0]['cost']), 3.0)

        # Verify Combine Option copied (including selling_price!)
        options = query_all("SELECT * FROM product_combine_options WHERE product_id = %s", (copied_id,))
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['option_name'], 'With Plastic Lid')
        self.assertEqual(options[0]['component_product_id'], self.comp_id)
        self.assertEqual(float(options[0]['component_quantity']), 1.0)
        self.assertEqual(float(options[0]['price_modifier']), 1.5)
        self.assertEqual(float(options[0]['selling_price']), 31.5)
        self.assertTrue(options[0]['is_default'])
        self.assertEqual(options[0]['notes'], 'Clear PET lid')

if __name__ == '__main__':
    unittest.main()
