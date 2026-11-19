import unittest
import csv
import io
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, query_all

class TestReportPaymentMethodFilter(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

    def test_ui_payment_method_elements_exist(self):
        """Verify the Paid By / Payment Method chip, popover, drawer select, hidden input, and JS function exist."""
        resp = self.client.get('/reports/view/sales-order-profit')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('id="formPaymentMethodInput"', html)
        self.assertIn('id="chipWrapPaymentMethod"', html)
        self.assertIn('id="popoverPaymentMethod"', html)
        self.assertIn('id="drawerPaymentMethodSelect"', html)
        self.assertIn('selectFilterPaymentMethod(', html)
        self.assertIn('payment_method=', html)

    def test_payment_method_filtering_aba(self):
        """Verify that filtering by ABA Bank returns matching orders."""
        order_aba = query_one("""
            SELECT so.id, so.order_number, so.payment_method
            FROM sales_orders so
            WHERE so.status != 'CANCELLED'
              AND (
                so.payment_method ILIKE '%%ABA%%'
                OR EXISTS (
                    SELECT 1 FROM order_payments op 
                    WHERE op.order_type = 'SO' AND op.order_id = so.id AND op.payment_method ILIKE '%%ABA%%'
                )
              )
            ORDER BY so.order_number ASC LIMIT 1
        """)
        if not order_aba:
            self.skipTest("No ABA orders found in database")

        target_num = order_aba['order_number']
        resp = self.client.get('/reports/view/sales-order-profit?date_range=All&status=All&payment_method=ABA+Bank')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn(target_num, html)

    def test_payment_method_filtering_cash(self):
        """Verify that filtering by Cash returns matching orders."""
        order_cash = query_one("""
            SELECT so.id, so.order_number, so.payment_method
            FROM sales_orders so
            WHERE so.status != 'CANCELLED'
              AND (
                so.payment_method ILIKE '%%Cash%%'
                OR so.payment_method ILIKE '%%សាច់ប្រាក់%%'
                OR EXISTS (
                    SELECT 1 FROM order_payments op 
                    WHERE op.order_type = 'SO' AND op.order_id = so.id AND (op.payment_method ILIKE '%%Cash%%' OR op.payment_method ILIKE '%%សាច់ប្រាក់%%')
                )
              )
            ORDER BY so.order_number ASC LIMIT 1
        """)
        if not order_cash:
            self.skipTest("No Cash orders found in database")

        target_num = order_cash['order_number']
        resp = self.client.get('/reports/view/sales-order-profit?date_range=All&status=All&payment_method=Cash')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn(target_num, html)

    def test_payment_method_export_csv(self):
        """Verify that CSV export works with payment_method parameter."""
        resp = self.client.get('/reports/export/sales-order-profit?date_range=All&status=All&payment_method=ABA+Bank')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.headers.get('Content-Type', ''))
        content = resp.data.decode('utf-8')
        self.assertIn('Order Number', content)
        self.assertIn('Sales Amount ($)', content)

if __name__ == '__main__':
    unittest.main()
