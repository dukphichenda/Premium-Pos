import unittest
from flask import render_template
from app import create_app

class TestInvoiceA5Fit(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True

    def test_invoice_has_a5_pdf_styles_and_smart_fit(self):
        with self.app.test_request_context():
            html = render_template(
                'sales/invoice_print.html',
                order={
                    'order_number': 'SO-2026-0001',
                    'order_date': '2026-10-15',
                    'total_amount': 150.0,
                    'paid_amount': 150.0,
                    'balance_due': 0.0
                },
                lines=[
                    {
                        'product_name': 'Test Item 1',
                        'product_sku': 'SKU-001',
                        'quantity': 2,
                        'unit_price': 50.0,
                        'discount_percent': 0,
                        'subtotal': 100.0
                    },
                    {
                        'product_name': 'Test Item 2',
                        'product_sku': 'SKU-002',
                        'quantity': 1,
                        'unit_price': 50.0,
                        'discount_percent': 0,
                        'subtotal': 50.0
                    }
                ],
                company={'name': 'Test Company'},
                inv_settings={
                    'font_family': 'Kantumruy Pro',
                    'enable_khr_total': True,
                    'show_signature': True,
                    'qr_code_url': 'https://example.com/qr.png'
                },
                doc_type='invoice',
                khr_rate=4100,
                total_khr=615000,
                paid_khr=615000,
                balance_khr=0
            )

            # 1. Check A5 dimensions and margin specifications
            self.assertIn('size: A5 portrait;', html)
            self.assertIn('margin: [4, 5, 4, 5]', html)
            self.assertIn("format: 'a5'", html)
            self.assertIn("orientation: 'portrait'", html)

            # 1b. Check scrollbar elimination rules in print
            self.assertIn('::-webkit-scrollbar', html)
            self.assertIn('display: none !important;', html)
            self.assertIn('scrollbar-width: none !important;', html)
            self.assertIn('overflow-y: hidden !important;', html)
            self.assertIn('height: auto !important;', html)
            self.assertIn('printInvoiceDocument', html)

            # 2. Check compact A5 classes and container styles
            self.assertIn('class="inv-khqr-card"', html)
            self.assertIn('class="inv-bank-card"', html)
            self.assertIn('inv-bottom-grid', html)
            self.assertIn('body.exporting-pdf .inv-khqr-card', html)
            self.assertIn('body.exporting-pdf .totals-card', html)

            # 3. Check page break prevention rules
            self.assertIn('page-break-inside: avoid !important;', html)
            self.assertIn('break-inside: avoid !important;', html)
            self.assertIn("pagebreak:", html)
            self.assertIn("'.inv-header'", html)
            self.assertIn("'.inv-parties-card'", html)
            self.assertIn("'tr'", html)
            self.assertIn("'.totals-card'", html)
            self.assertIn("'.inv-khqr-card'", html)
            self.assertIn("'.signature-section'", html)

            # 4. Check Smart Auto-Fit scaling engine
            self.assertIn('maxSinglePageHeight', html)
            self.assertIn('scaledCanvas', html)
            self.assertIn('maxSinglePageHeight * 1.16', html)

            # 6. Check Khmer Font & Typography Protection
            self.assertIn("'Khmer OS Battambang'", html)
            self.assertIn("body.exporting-pdf .shop-name-kh", html)
            self.assertIn("line-height: 1.6 !important;", html)
            self.assertIn("body.exporting-pdf .inv-badge-title", html)
            self.assertIn("letter-spacing: normal !important;", html)

if __name__ == '__main__':
    unittest.main()
