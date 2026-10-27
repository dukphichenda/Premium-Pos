import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, execute, execute_returning_id

class TestPurchaseEnhancements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'System Administrator'
            sess['role'] = 'main_admin'

        cls.loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")
        cls.loc_id = cls.loc['id'] if cls.loc else 100

    def test_sidebar_has_vendor_and_date_and_payment_auto_amount(self):
        """Test PO sidebar template and payment modal fields without mutating product catalog"""
        # Fetch an existing purchase order or create a test PO without products
        po = query_one("""
            SELECT po.id, po.order_number, po.total_amount, po.balance_due, po.vendor_id, v.name as vendor_name
            FROM purchase_orders po
            LEFT JOIN vendors v ON po.vendor_id = v.id
            ORDER BY po.id DESC LIMIT 1
        """)
        if not po:
            self.skipTest("No purchase order found to test detail view.")

        res = self.client.get(f"/purchases/{po['id']}")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 1. Requirement 3: Vendor name and order date on sidebar
        self.assertIn('po-card-vendor-row', html)
        self.assertIn('po-card-vendor', html)
        self.assertIn('po-card-date', html)
        self.assertIn('data-order-date', html)

        # 2. Requirement 2: Same-tab attachment popup (Lightbox modal)
        self.assertIn('id="poAttachmentLightboxModal"', html)
        self.assertIn('openPoAttachmentPreview', html)
        self.assertIn('closePoAttachmentPreview', html)

        # 3. Requirement 1: Auto add amount based on PO amount when adding payment
        self.assertIn('id="poRecordPaymentForm"', html)
        self.assertIn('id="poPaymentAmountInput"', html)
        self.assertIn('id="poPaymentDateInput"', html)

    def test_record_payment_backend_route(self):
        """Test payment recording with payment_method, reference_no, payment_notes, and payment_date"""
        # Create a test PO (no products touched)
        vend = query_one("SELECT id FROM vendors WHERE is_active = TRUE LIMIT 1")
        vend_id = vend['id'] if vend else None

        test_po_id = execute_returning_id("""
            INSERT INTO purchase_orders (
                order_number, vendor_id, location_id, order_date, status, payment_status,
                subtotal, total_amount, paid_amount, balance_due, notes
            ) VALUES (
                'PO-TEST-UNIT-PAY', %s, %s, CURRENT_DATE, 'DRAFT', 'UNPAID',
                500.00, 500.00, 0.00, 500.00, 'Test unit pay'
            ) RETURNING id;
        """, (vend_id, self.loc_id))

        try:
            # Post payment
            pay_data = {
                'amount': '250.00',
                'payment_method': 'Bank Transfer (ABA / Prasac)',
                'reference_no': 'REF-123456',
                'payment_notes': 'Half payment unit test',
                'payment_date': '2026-10-27'
            }
            res = self.client.post(f"/purchases/{test_po_id}/pay", data=pay_data, follow_redirects=False)
            self.assertEqual(res.status_code, 302)

            # Verify purchase order balances
            updated_po = query_one("SELECT paid_amount, balance_due, payment_status FROM purchase_orders WHERE id = %s", (test_po_id,))
            self.assertAlmostEqual(float(updated_po['paid_amount']), 250.00, places=2)
            self.assertAlmostEqual(float(updated_po['balance_due']), 250.00, places=2)
            self.assertEqual(updated_po['payment_status'], 'PARTIAL')

            # Verify order_payments record
            pay_rec = query_one("""
                SELECT * FROM order_payments 
                WHERE order_type = 'PO' AND order_id = %s
                ORDER BY id DESC LIMIT 1
            """, (test_po_id,))
            self.assertIsNotNone(pay_rec)
            self.assertAlmostEqual(float(pay_rec['amount']), 250.00, places=2)
            self.assertEqual(pay_rec['payment_method'], 'Bank Transfer (ABA / Prasac)')
            self.assertEqual(pay_rec['reference'], 'REF-123456')
            self.assertEqual(pay_rec['notes'], 'Half payment unit test')

        finally:
            # Clean up test PO and payment record
            execute("DELETE FROM order_payments WHERE order_type = 'PO' AND order_id = %s;", (test_po_id,))
            execute("DELETE FROM purchase_orders WHERE id = %s;", (test_po_id,))

if __name__ == '__main__':
    unittest.main()
