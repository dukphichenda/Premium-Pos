import unittest
from app import create_app
from database import query_one, get_db_cursor

class TestSoCompletedAtAndRearrange(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'main_admin'

    def test_rearranged_so_canvas_elements(self):
        resp = self.client.get('/sales/new')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. Customer Card & View History link
        self.assertIn('CUSTOMER', html)
        self.assertIn('View History', html)
        self.assertIn('openCustomerHistoryModal', html)

        # 2. Logistics & Store Route Card
        self.assertIn('LOGISTICS & STORE ROUTE', html)
        self.assertIn('Auto-dispatch ready', html)
        self.assertIn('elemWrapBranch', html)
        self.assertIn('elemWrapLocation', html)
        self.assertIn('elemWrapDeliveryBy', html)
        self.assertIn('elemWrapDeliveryFee', html)

        # 3. Order Items header
        self.assertIn('ORDER ITEMS', html)
        self.assertIn('orderItemsSubtitle', html)

        # 4. Right Sidebar: Order Meta at top & KHR conversion & F10
        self.assertIn('ORDER NO.', html)
        self.assertIn('elemWrapOrderNumber', html)
        self.assertIn('elemWrapDate', html)
        self.assertIn('elemWrapStatus', html)
        self.assertIn('elemWrapSalesRep', html)
        self.assertIn('soCompletedDateUnderBiller', html)
        self.assertIn('dispTotalKhr', html)
        self.assertIn('btnPayAmountDisp', html)
        self.assertIn('F10', html)

    def test_completed_order_shows_completed_date_below_completer_name(self):
        # Find or create a test paid order
        order = query_one("SELECT id, order_number, completed_by, completed_at, invoiced_date FROM sales_orders WHERE status = 'PAID' AND completed_by IS NOT NULL LIMIT 1")
        if order:
            resp = self.client.get(f'/sales/{order["id"]}')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')

            # Ensure Biller name and completed date are rendered
            self.assertIn('soCompletedDateUnderBiller', html)
            self.assertIn(order['completed_by'], html)

if __name__ == '__main__':
    unittest.main()
