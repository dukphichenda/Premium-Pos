import unittest
import re
from app import create_app
import database

class TestInvoiceUnitPrice3Digits(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_invoice_print_renders_3_digit_unit_price_when_item_has_3_decimals(self):
        """Verify that items with 3 decimals (e.g. $0.088 or $0.175) display 3 digits in invoice print."""
        with self.app.test_request_context():
            from flask import render_template
            mock_order = {
                'id': 99999,
                'order_number': 'SO-TEST-001',
                'order_date': '2026-10-19',
                'due_date': '2026-10-19',
                'customer_name': 'Test Customer',
                'status': 'INVOICED',
                'subtotal': 88.00,
                'total_amount': 88.00,
                'paid_amount': 88.00,
                'balance_due': 0.00,
            }
            mock_lines = [
                {
                    'line_num': 1,
                    'product_name': 'Kraft Bowl 500ML',
                    'product_sku': 'PB-500K',
                    'quantity': 1000,
                    'quantity_display': 1000,
                    'uom': 'pcs',
                    'unit_price': 0.088,
                    'subtotal': 88.00
                },
                {
                    'line_num': 2,
                    'product_name': 'Eco Straw 8mm',
                    'product_sku': 'STR-PLA8',
                    'quantity': 100,
                    'quantity_display': 100,
                    'uom': 'pcs',
                    'unit_price': 35.00,
                    'subtotal': 3500.00
                }
            ]
            company = {'decimal_places_price': 2}
            inv_settings = {'unit_price_decimals': 2}

            html = render_template('sales/invoice_print.html',
                                   order=mock_order,
                                   lines=mock_lines,
                                   company=company,
                                   inv_settings=inv_settings,
                                   doc_type='invoice',
                                   khr_rate=4100.0,
                                   total_khr=360800,
                                   paid_khr=360800,
                                   balance_khr=0)
            
            # The 0.088 unit price should NOT be rounded to $0.09 - it should be $0.088!
            self.assertIn('$0.088', html)
            self.assertIn('$35.00', html)

    def test_invoice_print_renders_3_digits_when_setting_is_3(self):
        """Verify that when unit_price_decimals=3, standard items (e.g. $35) format to $35.000."""
        with self.app.test_request_context():
            from flask import render_template
            mock_order = {
                'id': 99999,
                'order_number': 'SO-TEST-002',
                'order_date': '2026-10-19',
                'due_date': '2026-10-19',
                'customer_name': 'Test Customer',
                'status': 'INVOICED',
                'subtotal': 700.00,
                'total_amount': 700.00,
                'paid_amount': 700.00,
                'balance_due': 0.00,
            }
            mock_lines = [
                {
                    'line_num': 1,
                    'product_name': 'Kraft Bowl 500ML',
                    'product_sku': 'PB-500K',
                    'quantity': 20,
                    'quantity_display': 20,
                    'uom': 'pcs',
                    'unit_price': 35.00,
                    'subtotal': 700.00
                }
            ]
            company = {'decimal_places_price': 3}
            inv_settings = {'unit_price_decimals': 3}

            html = render_template('sales/invoice_print.html',
                                   order=mock_order,
                                   lines=mock_lines,
                                   company=company,
                                   inv_settings=inv_settings,
                                   doc_type='invoice',
                                   khr_rate=4100.0,
                                   total_khr=2870000,
                                   paid_khr=2870000,
                                   balance_khr=0)
            
            self.assertIn('$35.000', html)

    def test_branch_settings_preview_contains_price_decimals_control(self):
        """Verify branch settings template has unit_price_decimals selector and prev-mock-price cells."""
        branch = database.query_one("SELECT * FROM branches LIMIT 1")
        if not branch:
            return
        
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

        resp = self.client.get(f'/branches/{branch["id"]}/settings?tab=tabInvoice')
        if resp.status_code == 200:
            html = resp.data.decode('utf-8')
            self.assertIn('invUnitPriceDecimals', html)
            self.assertIn('prev-mock-price', html)
            self.assertIn('$35.000', html)

if __name__ == '__main__':
    unittest.main()
