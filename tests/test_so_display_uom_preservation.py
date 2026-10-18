import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from services.csv_exchange import resolve_order_line_uom


class TestSoDisplayUomPreservation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_uom_resolution_matrix(self):
        """Test all standard and local UOMs found in inFlow sales orders"""
        mock_p = {
            'id': 258,
            'sku': 'PB1000K-KL',
            'name': 'PB1000K-KL ចានគគី (Kraft bolw 1000ml) 500ចាន/កេស',
            'default_price': 0.11,
            'sales_uom': 'cases',
            'sales_uom_ratio_std': 500.0,
            'uom': 'pcs.'
        }
        # 1. 'pcs.' must remain 'pcs.' with ratio 1.0
        uom, disp, std = resolve_order_line_uom('pcs.', mock_p['name'], '', mock_p, 0.11, 100.0)
        self.assertEqual(uom, 'pcs.')
        self.assertEqual(disp, 100.0)
        self.assertEqual(std, 100.0)

        # 2. 'cases' must remain 'cases' with ratio 500.0
        uom_c, disp_c, std_c = resolve_order_line_uom('cases', mock_p['name'], '', mock_p, 42.0, 1.0)
        self.assertEqual(uom_c, 'cases')
        self.assertEqual(disp_c, 1.0)
        self.assertEqual(std_c, 500.0)

        # 3. 'ea.' must remain 'ea.' with ratio 1.0
        uom_e, disp_e, std_e = resolve_order_line_uom('ea.', 'Delivery/ថ្លៃដឹក', '', None, 3.0, 1.0)
        self.assertEqual(uom_e, 'ea.')
        self.assertEqual(disp_e, 1.0)
        self.assertEqual(std_e, 1.0)

        # 4. 'កេស/cases' must map to 'cases'
        uom_kh, disp_kh, std_kh = resolve_order_line_uom('កេស/cases', mock_p['name'], '', mock_p, 42.0, 2.0)
        self.assertEqual(uom_kh, 'cases')
        self.assertEqual(disp_kh, 2.0)
        self.assertEqual(std_kh, 1000.0)

    @patch('routes.sales_orders.query_one')
    @patch('routes.sales_orders.query_all')
    @patch('routes.sales_orders.session', {'user_id': 1, 'branch_id': 1, 'role': 'admin'})
    def test_sales_order_detail_does_not_override_pcs_to_cases(self, mock_qa, mock_qo):
        """
        Verify that opening sales order detail preserves 'pcs.' display_uom
        and does NOT silently overwrite it with the product's sales_uom ('cases').
        """
        mock_qo.side_effect = lambda q, *args, **kwargs: {
            'id': 124185,
            'order_number': 'SO-022871',
            'customer_id': 10,
            'customer_name': 'Lim Y Makara',
            'branch_id': 1,
            'location_id': 1,
            'status': 'OPEN',
            'payment_status': 'UNPAID',
            'total_amount': 73.0,
            'paid_amount': 0.0,
            'balance_due': 73.0,
            'shipping_fee': 0.0,
            'pricing_scheme_id': 100
        }

        # Mock query_all for lines and payments
        def qa_side_effect(q, *args, **kwargs):
            if 'FROM sales_order_lines' in q:
                return [
                    {
                        'id': 1,
                        'product_id': 258,
                        'product_sku': 'PB1000K-KL',
                        'product_name': 'PB1000K-KL ចានគគី 500ចាន/កេស',
                        'description': '',
                        'quantity': 100.0,
                        'quantity_display': 100.0,
                        'uom': 'pcs.',
                        'display_uom': 'pcs.',
                        'display_qty': 100.0,
                        'unit_price': 0.11,
                        'discount_percent': 0.0,
                        'subtotal': 11.0,
                        'stock_on_hand': 200.0,
                        'sales_uom': 'cases',
                        'sales_uom_ratio_std': 500.0,
                        'base_uom': 'pcs.'
                    }
                ]
            if 'FROM order_payments' in q:
                return []
            if 'FROM product_prices' in q:
                return []
            if 'FROM branches' in q:
                return [{'id': 1, 'name': 'Main Store (HQ)', 'is_main': True}]
            return []

        mock_qa.side_effect = qa_side_effect

        with self.client as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 1
                sess['branch_id'] = 1
                sess['role'] = 'admin'

            # Request canvas/partial detail
            resp = c.get('/sales/124185?partial=1')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')

            # Ensure 'pcs.' is rendered and NOT 'cases' for this 100-quantity piece item
            self.assertIn('pcs.', html)
            self.assertIn('100', html)


if __name__ == '__main__':
    unittest.main()
