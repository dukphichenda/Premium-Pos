import unittest
from app import create_app
from database import query_one, execute

class TestExtraInfoFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        # Clean up any leftover test product
        execute("DELETE FROM product_boms WHERE product_id IN (SELECT id FROM products WHERE sku = 'TEST-TEMP-EXTRAINFO-999');")
        execute("DELETE FROM products WHERE sku = 'TEST-TEMP-EXTRAINFO-999';")
        # Create dedicated isolated test product
        execute("""
            INSERT INTO products (sku, name, barcode, uom, sales_uom, sales_uom_ratio, sales_uom_ratio_std, is_active)
            VALUES ('TEST-TEMP-EXTRAINFO-999', 'Test Extra Info Product', '8936999999', 'pcs.', 'cases', 1, 200, TRUE);
        """)
        row = query_one("SELECT id FROM products WHERE sku = 'TEST-TEMP-EXTRAINFO-999'")
        cls.test_prod_id = row['id']

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'test_prod_id'):
            execute("DELETE FROM product_boms WHERE product_id = %s", (cls.test_prod_id,))
            execute("DELETE FROM products WHERE id = %s", (cls.test_prod_id,))

    def test_product_extra_info_rendering(self):
        resp = self.client.get(f'/products/{self.test_prod_id}?tab=tabExtraInfo')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        # Verify sections
        self.assertIn("Storage Info", html)
        self.assertIn("Unit of Measure", html)
        self.assertIn("Remarks", html)
        self.assertIn("Bill of Materials", html)
        self.assertIn("Measurements", html)
        
        # Verify UoM values and conversion
        self.assertIn("pcs.", html)
        self.assertIn("cases", html)
        self.assertIn("200", html)
        
        # Verify tab navigation buttons
        self.assertIn("btnTabExtraInfo", html)
        self.assertIn("btnTabProductInfo", html)
        self.assertIn("btnTabProductVendors", html)
        self.assertIn("btnTabMovementHistory", html)
        self.assertIn("btnTabOrderHistory", html)

    def test_update_extra_info_fields(self):
        form_data = {
            'sku': 'TEST-TEMP-EXTRAINFO-999',
            'name': 'Test Extra Info Product Updated',
            'barcode': '8936999999',
            'uom': 'pcs.',
            'sales_uom': 'cases',
            'sales_uom_ratio': '1',
            'sales_uom_ratio_std': '200',
            'purchasing_uom': 'cases',
            'purchasing_uom_ratio': '1',
            'purchasing_uom_ratio_std': '1',
            'length': '25.5',
            'width': '18.2',
            'height': '12.0',
            'weight': '0.75',
            'remarks': 'Testing authentic inFlow Extra Info replication',
            'active_tab': 'tabExtraInfo'
        }
        resp = self.client.post(f'/products/{self.test_prod_id}/save', data=form_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        # Verify in DB
        prod = query_one("SELECT barcode, length, width, height, weight, remarks FROM products WHERE id = %s", (self.test_prod_id,))
        self.assertEqual(prod['barcode'], '8936999999')
        self.assertAlmostEqual(float(prod['length']), 25.5)
        self.assertAlmostEqual(float(prod['width']), 18.2)
        self.assertAlmostEqual(float(prod['height']), 12.0)
        self.assertAlmostEqual(float(prod['weight']), 0.75)
        self.assertEqual(prod['remarks'], 'Testing authentic inFlow Extra Info replication')

    def test_bom_component_addition(self):
        component = query_one("SELECT id FROM products WHERE id != %s AND is_active = TRUE LIMIT 1", (self.test_prod_id,))
        if component:
            comp_id = component['id']
            form_data = {
                'sku': 'TEST-TEMP-EXTRAINFO-999',
                'name': 'Test Extra Info Product Updated',
                'uom': 'pcs.',
                'new_bom_component_id': str(comp_id),
                'new_bom_quantity': '5',
                'active_tab': 'tabExtraInfo'
            }
            resp = self.client.post(f'/products/{self.test_prod_id}/save', data=form_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            
            bom_row = query_one("SELECT * FROM product_boms WHERE product_id = %s AND component_product_id = %s", (self.test_prod_id, comp_id))
            self.assertIsNotNone(bom_row)
            self.assertAlmostEqual(float(bom_row['quantity']), 5.0)

            # Clean up test BOM row
            execute("DELETE FROM product_boms WHERE product_id = %s AND component_product_id = %s", (self.test_prod_id, comp_id))

if __name__ == '__main__':
    unittest.main()
