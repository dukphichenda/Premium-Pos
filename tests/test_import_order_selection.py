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
        """Verify import.html template includes order selection table, notice banner, checkboxes, and buttons"""
        response = self.client.get('/data/import?type=sales_order')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')

        self.assertIn('id="orderSelectionCard"', html)
        self.assertIn('id="orderSelectionNotice"', html)
        self.assertIn('btnAutoSelectRecommended', html)
        self.assertIn('id="orderSelectionTable"', html)
        self.assertIn('id="masterOrderCheckbox"', html)
        self.assertIn('id="selectedOrdersCount"', html)
        self.assertIn('id="totalOrdersCount"', html)
        self.assertIn('selectAllOrders(true)', html)
        self.assertIn('selectAllOrders(false)', html)
        self.assertIn('selectAutoRecommendedOrders()', html)
        self.assertIn('orderSearchInput', html)
        self.assertIn('chipFilterAll', html)
        self.assertIn('chipFilterNew', html)
        self.assertIn('chipFilterChanged', html)
        self.assertIn('chipFilterUnchanged', html)
        self.assertIn('badge-status-changed', html)
        self.assertIn('badge-unchanged', html)
        self.assertIn('btnToggleRawPreview', html)
        self.assertIn('id="unmatchedProductsAlertModal"', html)
        self.assertIn('showUnmatchedProductsAlertModal', html)
        self.assertIn('id="orderPaginationBar"', html)
        self.assertIn('notice-pill', html)
        self.assertIn('closeUnmatchedAlertAndFocusTable', html)
        self.assertIn('closeUnmatchedAlertAndKeepCustom', html)

    def test_keep_existing_auto_selects_new_and_status_changed_open_or_paid(self):
        """Verify preview_import_data in keep mode only auto-selects new orders or orders changing status to/from Open/Paid"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-NEW,2026-10-22,New Client,OPEN,Widget A,1,10.00,10.00
SO-OPEN-TO-PAID,2026-10-22,Client B,PAID,Widget B,1,20.00,20.00
SO-QUOTE-TO-OPEN,2026-10-22,Client C,OPEN,Widget C,1,30.00,30.00
SO-UNCHANGED-OPEN,2026-10-22,Client D,OPEN,Widget D,1,40.00,40.00
SO-UNCHANGED-PAID,2026-10-22,Client E,PAID,Widget E,1,50.00,50.00
"""
        # Mock existing database records:
        # SO-OPEN-TO-PAID has DB status 'OPEN'
        # SO-QUOTE-TO-OPEN has DB status 'QUOTE'
        # SO-UNCHANGED-OPEN has DB status 'OPEN'
        # SO-UNCHANGED-PAID has DB status 'PAID'
        mock_db_orders = [
            {'order_number': 'SO-OPEN-TO-PAID', 'status': 'OPEN', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-QUOTE-TO-OPEN', 'status': 'QUOTE', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-UNCHANGED-OPEN', 'status': 'OPEN', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-UNCHANGED-PAID', 'status': 'PAID', 'payment_status': 'PAID'},
        ]

        with patch('services.csv_exchange.query_all', return_value=mock_db_orders):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertEqual(res['total_orders'], 5)
        self.assertEqual(res['new_orders_count'], 1)
        self.assertEqual(res['status_changed_count'], 2)  # SO-OPEN-TO-PAID and SO-QUOTE-TO-OPEN
        self.assertEqual(res['unchanged_orders_count'], 2)  # SO-UNCHANGED-OPEN and SO-UNCHANGED-PAID
        self.assertEqual(res['auto_selected_count'], 3)  # 1 new + 2 changed

        orders = {o['order_number']: o for o in res['orders_summary']}

        # 1. New order -> MUST be auto-selected
        so_new = orders['SO-NEW']
        self.assertFalse(so_new['is_existing'])
        self.assertTrue(so_new['is_auto_selected'])
        self.assertEqual(so_new['status_change_type'], 'new')

        # 2. Existing order with status change OPEN -> PAID -> MUST be auto-selected
        so_paid = orders['SO-OPEN-TO-PAID']
        self.assertTrue(so_paid['is_existing'])
        self.assertTrue(so_paid['status_changed'])
        self.assertEqual(so_paid['db_status'], 'OPEN')
        self.assertEqual(so_paid['status'], 'PAID')
        self.assertEqual(so_paid['status_change_type'], 'open_or_paid_change')
        self.assertTrue(so_paid['is_auto_selected'])

        # 3. Existing order with status change QUOTE -> OPEN -> MUST be auto-selected
        so_quote_open = orders['SO-QUOTE-TO-OPEN']
        self.assertTrue(so_quote_open['is_existing'])
        self.assertTrue(so_quote_open['status_changed'])
        self.assertEqual(so_quote_open['db_status'], 'QUOTE')
        self.assertEqual(so_quote_open['status'], 'OPEN')
        self.assertEqual(so_quote_open['status_change_type'], 'open_or_paid_change')
        self.assertTrue(so_quote_open['is_auto_selected'])

        # 4. Existing order with unchanged OPEN status -> MUST NOT be auto-selected
        so_unch_open = orders['SO-UNCHANGED-OPEN']
        self.assertTrue(so_unch_open['is_existing'])
        self.assertFalse(so_unch_open['status_changed'])
        self.assertEqual(so_unch_open['db_status'], 'OPEN')
        self.assertEqual(so_unch_open['status'], 'OPEN')
        self.assertEqual(so_unch_open['status_change_type'], 'unchanged')
        self.assertFalse(so_unch_open['is_auto_selected'])

        # 5. Existing order with unchanged PAID status -> MUST NOT be auto-selected
        so_unch_paid = orders['SO-UNCHANGED-PAID']
        self.assertTrue(so_unch_paid['is_existing'])
        self.assertFalse(so_unch_paid['status_changed'])
        self.assertEqual(so_unch_paid['db_status'], 'PAID')
        self.assertEqual(so_unch_paid['status'], 'PAID')
        self.assertEqual(so_unch_paid['status_change_type'], 'unchanged')
        self.assertFalse(so_unch_paid['is_auto_selected'])

    def test_erase_mode_selects_all_orders(self):
        """Verify preview_import_data in erase mode selects all orders regardless of status"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-EXIST-1,2026-10-22,Client 1,OPEN,Item 1,1,10.00,10.00
SO-EXIST-2,2026-10-22,Client 2,PAID,Item 2,1,20.00,20.00
"""
        mock_db_orders = [
            {'order_number': 'SO-EXIST-1', 'status': 'OPEN'},
            {'order_number': 'SO-EXIST-2', 'status': 'PAID'},
        ]
        with patch('services.csv_exchange.query_all', return_value=mock_db_orders):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='erase')

        self.assertEqual(res['auto_selected_count'], 2)
        for o in res['orders_summary']:
            self.assertTrue(o['is_auto_selected'])

    def test_smart_header_autodetection_when_has_headers_false(self):
        """Verify preview_import_data auto-detects header row and generates orders_summary even when has_headers=False"""
        csv_data = """OrderNumber,OrderStatus,Customer,ContactName,Phone,Email,BillingAddress1,BillingAddress2,BillingCity,ItemCode,ItemName,ItemQuantity,ItemUnitPrice,ItemSubtotal
SO-99001,Paid,John Doe,John Doe,012345678,john@example.com,Phnom Penh,,Phnom Penh,SKU-001,Product 1,2,10.00,20.00
SO-99002,Open,Jane Smith,Jane Smith,098765432,jane@example.com,Siem Reap,,Siem Reap,SKU-002,Product 2,1,15.00,15.00
"""
        with patch('services.csv_exchange.query_all', return_value=[]):
            # Explicitly pass has_headers=False as might happen if checkbox is unticked
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=False, import_mode='keep')

        self.assertEqual(res['data_type'], 'sales_order')
        self.assertIn('orders_summary', res)
        self.assertEqual(len(res['orders_summary']), 2)
        ord_nums = [o['order_number'] for o in res['orders_summary']]
        self.assertIn('SO-99001', ord_nums)
        self.assertIn('SO-99002', ord_nums)
        # Verify first row headers were properly recognized and not treated as an order
        self.assertNotIn('OrderNumber', ord_nums)

    def test_unmatched_products_detected_for_unknown_items(self):
        """Verify preview_import_data detects unmatched products when CSV items do not exist in catalog"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Code,Item Name,Quantity,Unit Price,Subtotal
SO-801,2026-10-23,Client X,PAID,UNKNOWN-01,Rare Gadget,3,25.00,75.00
SO-802,2026-10-23,Client Y,OPEN,KNOWN-01,Standard Widget,1,10.00,10.00
"""
        mock_catalog_products = [
            {'id': 10, 'sku': 'KNOWN-01', 'name': 'Standard Widget', 'uom': 'pcs.', 'default_price': 10.0}
        ]
        with patch('services.csv_exchange.query_all', side_effect=[[], mock_catalog_products]):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertIn('unmatched_products', res)
        self.assertEqual(len(res['unmatched_products']), 1)
        unmatched = res['unmatched_products'][0]
        self.assertEqual(unmatched['item_code'], 'UNKNOWN-01')
        self.assertEqual(unmatched['item_name'], 'Rare Gadget')
        self.assertEqual(unmatched['count'], 1)
        self.assertIn('SO-801', unmatched['sample_orders'])


if __name__ == '__main__':
    unittest.main()

