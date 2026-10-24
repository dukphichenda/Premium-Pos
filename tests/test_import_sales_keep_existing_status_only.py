import io
import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from services.csv_exchange import preview_import_data, execute_import_data

class TestImportSalesKeepExistingStatusOnly(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_preview_keep_mode_shows_only_new_and_status_updated_orders(self):
        """
        User requirement: 'show preview only new update too'
        When Keep mode is selected, orders_summary MUST contain only:
        1. New SOs
        2. Existing SOs with status changes
        Unchanged SOs MUST NOT appear in orders_summary.
        """
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-BRAND-NEW,2026-10-24,Customer Alpha,OPEN,Widget 1,2,10.00,20.00
SO-TO-PAID,2026-10-24,Customer Beta,PAID,Widget 2,1,50.00,50.00
SO-TO-INVOICED,2026-10-24,Customer Gamma,INVOICED,Widget 3,3,15.00,45.00
SO-SAME-OPEN,2026-10-24,Customer Delta,OPEN,Widget 4,1,30.00,30.00
SO-SAME-PAID,2026-10-24,Customer Epsilon,PAID,Widget 5,2,25.00,50.00
"""
        mock_db_records = [
            {'order_number': 'SO-TO-PAID', 'status': 'OPEN', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-TO-INVOICED', 'status': 'OPEN', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-SAME-OPEN', 'status': 'OPEN', 'payment_status': 'UNPAID'},
            {'order_number': 'SO-SAME-PAID', 'status': 'PAID', 'payment_status': 'PAID'},
        ]

        with patch('services.csv_exchange.query_all', return_value=mock_db_records):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='keep')

        self.assertTrue(res['success'] if 'success' in res else True)
        self.assertEqual(res['total_file_orders'], 5)
        self.assertEqual(res['total_orders'], 3)  # Only 3 actionable orders in preview!
        self.assertEqual(res['new_orders_count'], 1)
        self.assertEqual(res['status_changed_count'], 2)
        self.assertEqual(res['unchanged_orders_count'], 2)
        self.assertEqual(len(res['orders_summary']), 3)

        preview_order_nums = [o['order_number'] for o in res['orders_summary']]
        self.assertIn('SO-BRAND-NEW', preview_order_nums)
        self.assertIn('SO-TO-PAID', preview_order_nums)
        self.assertIn('SO-TO-INVOICED', preview_order_nums)
        self.assertNotIn('SO-SAME-OPEN', preview_order_nums)
        self.assertNotIn('SO-SAME-PAID', preview_order_nums)

    def test_execute_keep_mode_effects_new_so_or_new_update_status_only(self):
        """
        User requirement: 'effect new so or new update status only the rest don't care'
        1. Existing SO with status change -> ONLY update status in sales_orders. Do not touch lines!
        2. Existing SO with same status -> Skipped completely.
        3. New SO -> Inserted with lines.
        """
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-NEW-1,2026-10-24,New Customer,OPEN,Product A,1,20.00,20.00
SO-UPDATE-1,2026-10-24,Old Customer,PAID,Product B,2,40.00,80.00
SO-UNCHANGED-1,2026-10-24,Old Customer 2,OPEN,Product C,1,10.00,10.00
"""
        existing_db_orders = [
            {'id': 101, 'order_number': 'SO-UPDATE-1', 'branch_id': None, 'status': 'OPEN', 'payment_status': 'UNPAID', 'total_amount': 80.0, 'paid_amount': 0.0, 'balance_due': 80.0, 'invoiced_date': None},
            {'id': 102, 'order_number': 'SO-UNCHANGED-1', 'branch_id': None, 'status': 'OPEN', 'payment_status': 'UNPAID', 'total_amount': 10.0, 'paid_amount': 0.0, 'balance_due': 10.0, 'invoiced_date': None}
        ]

        executed_queries = []

        with patch('services.csv_exchange.query_all', return_value=[]), \
             patch('services.csv_exchange.get_db_cursor') as mock_cursor:

            mock_cur = mock_cursor.return_value.__enter__.return_value
            mock_cur.fetchone.return_value = {'id': 999}
            mock_cur.fetchall.return_value = existing_db_orders

            def track_execute(query, params=None):
                executed_queries.append((query.strip(), params))
                return None

            mock_cur.execute.side_effect = track_execute

            res = execute_import_data(
                'sales_order',
                csv_data.encode('utf-8'),
                has_headers=True,
                import_mode='keep',
                selected_orders=['SO-NEW-1', 'SO-UPDATE-1']
            )

        self.assertTrue(res['success'])
        self.assertEqual(res['imported'], 1)  # SO-NEW-1
        self.assertEqual(res['updated'], 1)   # SO-UPDATE-1
        self.assertEqual(res['skipped'], 1)   # SO-UNCHANGED-1

        # Verify NO bulk delete of sales_order_lines was ever executed!
        for q, p in executed_queries:
            self.assertNotIn("DELETE FROM sales_order_lines", q, "Existing order lines must NEVER be deleted in Keep mode!")

        # Verify that for SO-UPDATE-1, ONLY UPDATE sales_orders SET status ... was run
        status_updates = [q for q, p in executed_queries if "UPDATE sales_orders" in q and "SET status" in q]
        self.assertEqual(len(status_updates), 1, "Must execute exactly one status-only update for SO-UPDATE-1")
        self.assertIn("payment_status = 'PAID'", status_updates[0])
        self.assertIn("paid_amount = total_amount", status_updates[0])

        # Verify that for SO-NEW-1, an INSERT into sales_orders was run
        inserts = [q for q, p in executed_queries if "INSERT INTO sales_orders" in q]
        self.assertEqual(len(inserts), 1, "Must execute exactly one insert for SO-NEW-1")

    def test_erase_mode_still_shows_all_orders_in_preview(self):
        """Verify Erase mode shows all orders in preview since everything is replaced"""
        csv_data = """Order Number,Order Date,Customer,OrderStatus,Item Name,Quantity,Unit Price,Subtotal
SO-E1,2026-10-24,Client 1,OPEN,Item 1,1,10.00,10.00
SO-E2,2026-10-24,Client 2,PAID,Item 2,2,20.00,40.00
"""
        with patch('services.csv_exchange.query_all', return_value=[{'order_number': 'SO-E1', 'status': 'OPEN'}]):
            res = preview_import_data('sales_order', csv_data.encode('utf-8'), has_headers=True, import_mode='erase')

        self.assertEqual(res['total_orders'], 2)
        self.assertEqual(len(res['orders_summary']), 2)
        for o in res['orders_summary']:
            self.assertTrue(o['is_auto_selected'])

if __name__ == '__main__':
    unittest.main()
