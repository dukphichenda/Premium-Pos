import unittest
from app import create_app

class TestInvoicePreviewZoom(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_invoice_preview_contains_zoom_controls(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        response = self.client.get('/sales/22476/print?type=invoice')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Check zoom toolbar controls
        self.assertIn('id="invoiceZoomSelect"', html)
        self.assertIn('class="zoom-control-box"', html)
        self.assertIn('onclick="adjustZoom(-10)"', html)
        self.assertIn('onclick="adjustZoom(10)"', html)
        self.assertIn('onclick="setInvoiceZoom(100)"', html)

        # Check options
        self.assertIn('<option value="50">50%</option>', html)
        self.assertIn('<option value="100" selected>100%</option>', html)
        self.assertIn('<option value="150">150%</option>', html)
        self.assertIn('<option value="200">200%</option>', html)
        self.assertIn('<option value="fit">Fit Width</option>', html)

        # Check viewport container
        self.assertIn('id="invoiceZoomContainer"', html)

        # Check JavaScript zoom engine & persistence
        self.assertIn('function applyZoomToSheet', html)
        self.assertIn('function setInvoiceZoom', html)
        self.assertIn('function adjustZoom', html)
        self.assertIn('inflow_invoice_zoom', html)

        # Check print query resets zoom
        self.assertIn('zoom: 1 !important;', html)
        self.assertIn('transform: none !important;', html)

if __name__ == '__main__':
    unittest.main()
