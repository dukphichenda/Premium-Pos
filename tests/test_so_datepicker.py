import unittest
import re
from app import app
from database import query_one, execute_returning_id

class TestSoDatePicker(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_so_detail_has_datepicker_and_clickable_icon(self):
        """SO detail page must render the datepicker input and clickable calendar icon."""
        order = query_one("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")
        if not order:
            cust = query_one("SELECT id FROM customers LIMIT 1")
            cust_id = cust['id'] if cust else 1
            oid = execute_returning_id(
                "INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-DP-1', %s, 100, 'OPEN', 'UNPAID', '2026-09-21') RETURNING id",
                (cust_id,)
            )
        else:
            oid = order['id']

        resp = self.client.get(f'/sales/{oid}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check date input and gs-datepicker classes
        self.assertIn('id="orderDateInput"', html)
        self.assertIn('gs-datepicker-input', html)
        self.assertIn('gs-datepicker-icon', html)
        # Check onclick handler triggers GoogleSheetDatePicker
        self.assertIn('GoogleSheetDatePicker.open', html)

    def test_save_sales_order_with_inflow_date_format(self):
        """Saving SO with DD-MMM-YY format (e.g. 21-Sep-26) correctly parses and saves."""
        cust = query_one("SELECT id FROM customers LIMIT 1")
        cust_id = cust['id'] if cust else 1
        import time
        t_str = str(int(time.time() * 1000))
        oid = execute_returning_id(
            f"INSERT INTO sales_orders (order_number, customer_id, total_amount, status, payment_status, order_date) VALUES ('TEST-DP-{t_str}', %s, 100, 'OPEN', 'UNPAID', '2026-09-20') RETURNING id",
            (cust_id,)
        )

        resp = self.client.post(
            f'/sales/{oid}/save',
            data={
                'customer_id': str(cust_id),
                'order_date': '21-Sep-26',
                'lines': '[]'
            },
            follow_redirects=False
        )
        self.assertIn(resp.status_code, (200, 302))

        updated = query_one("SELECT order_date FROM sales_orders WHERE id = %s", (oid,))
        self.assertIsNotNone(updated)
        self.assertEqual(str(updated['order_date']), '2026-09-21')

    def test_datepicker_js_has_icon_click_and_fixed_positioning(self):
        """Google sheets datepicker JS includes support for existing icon and fixed viewport position."""
        with open('static/js/google_sheets_datepicker.js', 'r', encoding='utf-8') as f:
            js_content = f.read()

        self.assertIn("pickerPopup.style.position = 'fixed'", js_content)
        self.assertIn('wrapper.querySelector(\'.gs-datepicker-icon\')', js_content)
        self.assertIn('activeWrapper.contains(e.target)', js_content)
        # Google Sheets header title and nav buttons
        self.assertIn('gs-dp-title', js_content)
        self.assertIn('gs-dp-nav-group', js_content)
        self.assertIn('gsDpPrevBtn', js_content)
        self.assertIn('gsDpNextBtn', js_content)
        # Google Sheets footer only has Today button
        self.assertIn('gsDpTodayBtn', js_content)
        self.assertNotIn('gsDpCloseBtn', js_content)
        # Exactly 42 day cells (6 rows)
        self.assertIn('42 - totalRendered', js_content)
        # Single day typing parsing
        self.assertIn('singleDayMatch', js_content)

    def test_datepicker_css_has_google_sheets_classes(self):
        """Styles.css contains Google Sheets circular outline today and solid blue selected."""
        with open('static/css/styles.css', 'r', encoding='utf-8') as f:
            css_content = f.read()

        self.assertIn('.gs-dp-title', css_content)
        self.assertIn('.gs-dp-day-today', css_content)
        self.assertIn('.gs-dp-day-selected', css_content)
        self.assertIn('.gs-dp-btn-today', css_content)
        self.assertIn('#1A73E8', css_content)

if __name__ == '__main__':
    unittest.main()
