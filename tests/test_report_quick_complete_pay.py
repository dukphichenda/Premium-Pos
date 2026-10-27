import unittest
import json
from app import app
from database import query_one, get_db_cursor

class TestReportQuickCompletePay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_templates_contain_refresh_and_quick_pay(self):
        # 1. Check viewer.html content
        with open('templates/reports/viewer.html', 'r', encoding='utf-8') as f:
            viewer_html = f.read()
        self.assertIn('btnReportFilterRefresh', viewer_html)
        self.assertIn('btnReportRightRefresh', viewer_html)
        self.assertIn('refreshReportViewer', viewer_html)
        self.assertIn('rep-quick-complete-btn', viewer_html)
        self.assertIn('reportQuickPayModal', viewer_html)
        self.assertIn('repQuickPayCompletedByInput', viewer_html)
        self.assertIn('openReportQuickPayModal', viewer_html)
        self.assertIn('confirmReportQuickPay', viewer_html)

        # 2. Check sales/list.html content
        with open('templates/sales/list.html', 'r', encoding='utf-8') as f:
            list_html = f.read()
        self.assertIn('Refresh', list_html)
        self.assertIn('salesListQuickPayModal', list_html)
        self.assertIn('openSalesListQuickPay', list_html)
        self.assertIn('confirmListQuickPay', list_html)
        self.assertIn('listQuickPayCompletedByInput', list_html)

        # 3. Check sales/detail.html content
        with open('templates/sales/detail.html', 'r', encoding='utf-8') as f:
            detail_html = f.read()
        self.assertIn('btnRefreshSoList', detail_html)
        self.assertIn('btn-so-refresh', detail_html)
        self.assertIn('refreshSalesOrderView', detail_html)
        self.assertIn('completePayCompletedByInput', detail_html)

    def test_complete_pay_api_endpoint(self):
        # Find an open sales order or create a temporary one for testing
        test_order = query_one("""
            SELECT id, order_number, total_amount, status, payment_status 
            FROM sales_orders 
            WHERE status != 'CANCELLED' 
            ORDER BY id DESC LIMIT 1
        """)
        if not test_order:
            self.skipTest("No sales orders in database to test complete_pay endpoint")

        order_id = test_order['id']
        orig_status = test_order['status']
        orig_pay_status = test_order['payment_status']

        try:
            with self.client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['username'] = 'test_agent'
                sess['display_name'] = 'Agent Tester'
                sess['role'] = 'main_admin'

            # Test complete_pay via JSON
            res = self.client.post(
                f'/sales/{order_id}/complete_pay',
                data=json.dumps({
                    'payment_method': 'ABA Bank',
                    'completed_by': 'Chenda Pos Cashier'
                }),
                content_type='application/json'
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))
            self.assertEqual(data.get('status'), 'PAID')
            self.assertEqual(data.get('payment_status'), 'PAID')
            self.assertEqual(data.get('payment_method'), 'ABA Bank')
            self.assertEqual(data.get('completed_by'), 'Chenda Pos Cashier')

            # Verify in DB
            db_order = query_one("SELECT status, payment_status, payment_method, completed_by, balance_due FROM sales_orders WHERE id = %s", (order_id,))
            self.assertEqual(db_order['status'], 'PAID')
            self.assertEqual(db_order['payment_status'], 'PAID')
            self.assertEqual(db_order['payment_method'], 'ABA Bank')
            self.assertEqual(db_order['completed_by'], 'Chenda Pos Cashier')
            self.assertEqual(float(db_order['balance_due']), 0.0)

        finally:
            # Revert order to original state so test does not dirty state
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE sales_orders 
                    SET status = %s, payment_status = %s 
                    WHERE id = %s
                """, (orig_status, orig_pay_status, order_id))

    def test_sales_order_profit_report_view(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'test_agent'
            sess['role'] = 'main_admin'

        res = self.client.get('/reports/view/sales-order-profit')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Sales Order Profit Report', html)
        self.assertIn('btnReportFilterRefresh', html)
        self.assertIn('reportQuickPayModal', html)
        self.assertIn('repQuickPayCompletedByInput', html)

    def test_sales_orders_list_and_detail_views(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'test_agent'
            sess['role'] = 'main_admin'

        # 1. Test sales list page (workspace with modern sidebar)
        res = self.client.get('/sales', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('btn-so-refresh', html)
        self.assertIn('completePayCompletedByInput', html)

        # 2. Test sales detail page if order exists
        test_order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if test_order:
            res_det = self.client.get(f"/sales/{test_order['id']}")
            self.assertEqual(res_det.status_code, 200)
            det_html = res_det.get_data(as_text=True)
            self.assertIn('btn-so-refresh', det_html)
            self.assertIn('completePayCompletedByInput', det_html)

if __name__ == '__main__':
    unittest.main()
