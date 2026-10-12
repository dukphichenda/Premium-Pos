import unittest
from app import create_app
from database import query_one, execute

class TestExtraInfoFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_product_301_extra_info_rendering(self):
        resp = self.client.get('/products/301?tab=tabExtraInfo')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        
        # Verify sections from inFlow screenshot media_1791385732091_cbf4b599.png
        self.assertIn("Storage Info", html)
        self.assertIn("Unit of Measure", html)
        self.assertIn("Remarks", html)
        self.assertIn("Bill of Materials", html)
        self.assertIn("Measurements", html)
        
        # Verify vendor HUNUFA is present
        self.assertIn("HUNUFA", html)
        
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
        # Update product 301 measurements and remarks
        form_data = {
            'sku': 'SKU-0301',
            'name': 'N3500G-QP Test Extra Info',
            'barcode': '8936000001',
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
        resp = self.client.post('/products/301/save', data=form_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        # Verify in DB
        prod = query_one("SELECT barcode, length, width, height, weight, remarks FROM products WHERE id = 301")
        self.assertEqual(prod['barcode'], '8936000001')
        self.assertAlmostEqual(float(prod['length']), 25.5)
        self.assertAlmostEqual(float(prod['width']), 18.2)
        self.assertAlmostEqual(float(prod['height']), 12.0)
        self.assertAlmostEqual(float(prod['weight']), 0.75)
        self.assertEqual(prod['remarks'], 'Testing authentic inFlow Extra Info replication')

    def test_bom_component_addition(self):
        # Add a BOM row for product 301
        component = query_one("SELECT id FROM products WHERE id != 301 AND is_active = TRUE LIMIT 1")
        if component:
            comp_id = component['id']
            form_data = {
                'sku': 'SKU-0301',
                'name': 'N3500G-QP Test Extra Info',
                'uom': 'pcs.',
                'new_bom_component_id': str(comp_id),
                'new_bom_quantity': '5',
                'active_tab': 'tabExtraInfo'
            }
            resp = self.client.post('/products/301/save', data=form_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            
            bom_row = query_one("SELECT * FROM product_boms WHERE product_id = 301 AND component_product_id = %s", (comp_id,))
            self.assertIsNotNone(bom_row)
            self.assertAlmostEqual(float(bom_row['quantity']), 5.0)

            # Clean up test BOM row
            execute("DELETE FROM product_boms WHERE product_id = 301 AND component_product_id = %s", (comp_id,))

if __name__ == '__main__':
    unittest.main()
