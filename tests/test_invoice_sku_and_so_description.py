import unittest
from flask import render_template
from app import create_app

class TestInvoiceSkuAndSoDescription(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True

    def test_invoice_shows_sku_before_product_name(self):
        with self.app.test_request_context():
            rendered = render_template(
                'sales/invoice_print.html',
                order={'order_number': 'SO-9999', 'order_date': '2026-10-15', 'total_amount': 50.0, 'paid_amount': 0, 'balance_due': 50.0},
                lines=[
                    {
                        'line_num': 1,
                        'product_name': 'ប្រអប់បាយ1ថត 500ចាន/កេស',
                        'product_sku': 'HT17-1-TTK',
                        'quantity': 2,
                        'unit_price': 25.0,
                        'discount_percent': 0,
                        'subtotal': 50.0,
                        'line_description': 'Food grade paper box'
                    }
                ],
                company={'name': 'Test Company'},
                inv_settings={'font_family': 'Kantumruy Pro'},
                doc_type='invoice',
                khr_rate=4100,
                total_khr=205000,
                paid_khr=0,
                balance_khr=205000
            )
            # Check SKU is rendered before the product name
            self.assertIn('HT17-1-TTK', rendered)
            self.assertIn('ប្រអប់បាយ1ថត 500ចាន/កេស', rendered)
            self.assertIn('class="item-sku"', rendered)
            # Ensure no dedicated SKU column header was added
            self.assertNotIn('>SKU<', rendered)
            self.assertNotIn('>Product SKU<', rendered)

    def test_sales_order_detail_shows_description_column(self):
        with self.app.test_request_context():
            rendered = render_template(
                'sales/detail.html',
                order={'id': 1, 'order_number': 'SO-1001', 'order_date': '2026-10-15', 'status': 'OPEN', 'payment_status': 'UNPAID', 'location_id': 1},
                lines=[
                    {
                        'product_id': 101,
                        'product_sku': 'HT17-1-TTK',
                        'product_name': 'ប្រអប់បាយ1ថត 500ចាន/កេស',
                        'description': 'Food grade container 500pcs',
                        'display_qty': 3,
                        'display_uom': 'ctn',
                        'unit_price': 15.0,
                        'discount_percent': 0,
                        'subtotal': 45.0,
                        'stock_on_hand': 100,
                        'is_backordered': False
                    }
                ],
                pricing_schemes=[{'id': 100, 'name': 'Retail 1'}],
                all_products=[],
                product_prices_map={},
                categories=[],
                customers=[],
                locations=[],
                sidebar_orders=[],
                is_paid=False,
                can_edit_prices=True,
                payment_types=[]
            )
            # Check Description column header exists
            self.assertIn('<th style="width: 20%;">Description</th>', rendered)
            # Check Description input field is rendered with line's description
            self.assertIn('name="lines[0][description]"', rendered)
            self.assertIn('value="Food grade container 500pcs"', rendered)
            self.assertIn('id="newItemDescInput"', rendered)

if __name__ == '__main__':
    unittest.main()
