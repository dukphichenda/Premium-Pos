import io
import unittest
from unittest.mock import patch
from app import create_app
from services.csv_exchange import preview_import_data, execute_import_data

class TestImportOrderSelection(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_sales_order_preview_groups_and_summarizes_orders(self):
        """Verify preview_import_data extracts orders_summary with order grouping and totals"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-101,2026-10-14,Acme Corp,OPEN,Box 1600ML,2,10.00,20.00
SO-101,2026-10-14,Acme Corp,OPEN,Cup 500ML,1,5.00,5.00
SO-102,2026-10-15,Global Retail,PAID,Plate 9-inch,3,4.00,12.00
"""
        with patch('services.csv_exchange.query_all', return_value=[{'order_number': 'SO-101'}]):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertEqual(res['data_type'], 'sales_order')
        self.assertIn('orders_summary', res)
        self.assertEqual(len(res['orders_summary']), 2)

        # SO-101 checks
        so101 = next(o for o in res['orders_summary'] if o['order_number'] == 'SO-101')
        self.assertEqual(so101['party_name'], 'Acme Corp')
        self.assertEqual(so101['status'], 'OPEN')
        self.assertEqual(so101['item_count'], 2)
        self.assertEqual(so101['total_amount'], 25.0)
        self.assertTrue(so101['is_existing'])  # Matched mock in DB

        # SO-102 checks
        so102 = next(o for o in res['orders_summary'] if o['order_number'] == 'SO-102')
        self.assertEqual(so102['party_name'], 'Global Retail')
        self.assertEqual(so102['status'], 'PAID')
        self.assertEqual(so102['item_count'], 1)
        self.assertEqual(so102['total_amount'], 12.0)
        self.assertFalse(so102['is_existing'])  # Not in DB

    def test_purchase_order_preview_groups_and_summarizes_orders(self):
        """Verify preview_import_data extracts orders_summary for purchase orders"""
        csv_data = """Order Number,Order Date,Vendor,OrderStatus,Item Name,Quantity,Unit Cost,Subtotal
PO-901,2026-10-10,Asia Packaging,DRAFT,Raw Material A,10,2.50,25.00
PO-902,2026-10-11,Supplier X,OPEN,Raw Material B,5,8.00,40.00
"""
        with patch('services.csv_exchange.query_all', return_value=[]):
            res = preview_import_data('purchase_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertEqual(res['data_type'], 'purchase_order')
        self.assertIn('orders_summary', res)
        self.assertEqual(len(res['orders_summary']), 2)

        po901 = next(o for o in res['orders_summary'] if o['order_number'] == 'PO-901')
        self.assertEqual(po901['party_name'], 'Asia Packaging')
        self.assertEqual(po901['status'], 'DRAFT')
        self.assertEqual(po901['item_count'], 1)
        self.assertEqual(po901['total_amount'], 25.0)
        self.assertFalse(po901['is_existing'])

    def test_preview_api_endpoint_returns_orders_summary(self):
        """Verify POST /data/import/preview endpoint returns orders_summary in JSON"""
        csv_data = b"Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price\nSO-201,2026-10-14,Test Customer,OPEN,Product 1,1,15.00\n"
        with patch('services.csv_exchange.query_all', return_value=[]):
            response = self.client.post('/data/import/preview', data={
                'data_type': 'sales_order',
                'has_headers': '1',
                'import_mode': 'keep',
                'file': (io.BytesIO(csv_data), 'test_orders.csv')
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('orders_summary', data)
        self.assertEqual(len(data['orders_summary']), 1)
        self.assertEqual(data['orders_summary'][0]['order_number'], 'SO-201')

    def test_execute_import_data_skips_unselected_orders(self):
        """Verify execute_import_data imports only selected_orders and skips others"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price
SO-301,2026-10-14,Cust A,OPEN,Item 1,1,10.00
SO-302,2026-10-14,Cust B,OPEN,Item 2,1,20.00
SO-303,2026-10-14,Cust C,OPEN,Item 3,1,30.00
"""
        with patch('services.csv_exchange.query_all', return_value=[]), \
             patch('services.csv_exchange.get_db_cursor') as mock_cursor:
            
            mock_cur = mock_cursor.return_value.__enter__.return_value
            mock_cur.fetchone.return_value = {'id': 1}
            mock_cur.fetchall.return_value = [{'id': 1, 'order_number': 'SO-301', 'branch_id': None}, {'id': 2, 'order_number': 'SO-303', 'branch_id': None}]

            res = execute_import_data(
                'sales_order',
                csv_data.encode('utf-8'),
                has_headers=True,
                import_mode='keep',
                selected_orders=['SO-301', 'SO-303']
            )

        self.assertTrue(res['success'])
        self.assertEqual(res['updated'], 2)
        self.assertEqual(res['skipped'], 1)
        self.assertIn("1 skipped", res['message'])

    def test_import_template_contains_order_selection_elements(self):
        """Verify import.html template includes order selection table, checkboxes, and buttons"""
        response = self.client.get('/data/import?type=sales_order')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')

        self.assertIn('id="orderSelectionCard"', html)
        self.assertIn('id="orderSelectionTable"', html)
        self.assertIn('id="masterOrderCheckbox"', html)
        self.assertIn('id="selectedOrdersCount"', html)
        self.assertIn('id="totalOrdersCount"', html)
        self.assertIn('selectAllOrders(true)', html)
        self.assertIn('selectAllOrders(false)', html)
        self.assertIn('orderSearchInput', html)
        self.assertIn('btnToggleRawPreview', html)

if __name__ == '__main__':
    unittest.main()
