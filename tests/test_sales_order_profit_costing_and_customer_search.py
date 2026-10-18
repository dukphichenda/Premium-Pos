import unittest
import csv
import io
from app import create_app
from database import query_one, query_all

class TestSalesOrderProfitReport(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_sales_order_profit_page_and_costing_column(self):
        """Verify the report loads with 200 OK and contains the COSTING column and searchable customer combobox."""
        resp = self.client.get('/reports/view/sales-order-profit')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check column headers
        self.assertIn('COSTING', html)
        self.assertIn('SALES AMOUNT', html)
        self.assertIn('GROSS PROFIT', html)

        # Check searchable customer combobox
        self.assertIn('id="repCustomerSearchInput"', html)
        self.assertIn('id="repCustomerId"', html)
        self.assertIn('id="repCustomerDropdownMenu"', html)
        self.assertIn('openRepCustomerDropdown()', html)
        self.assertIn('filterRepCustomerDropdown(', html)
        self.assertIn('selectRepCustomer(', html)

    def test_customer_filtering_by_id_and_search(self):
        """Verify report filtering works with customer_id and customer_search."""
        # Find a customer that has sales orders
        order = query_one("""
            SELECT so.customer_id, c.name 
            FROM sales_orders so 
            JOIN customers c ON so.customer_id = c.id 
            WHERE so.status != 'CANCELLED' 
            ORDER BY so.id DESC LIMIT 1
        """)
        if not order:
            self.skipTest("No sales orders with customer found in DB")

        cust_id = order['customer_id']
        cust_name = order['name']

        # 1. Test filtering by customer_id
        resp_id = self.client.get(f'/reports/view/sales-order-profit?customer_id={cust_id}&date_range=All')
        self.assertEqual(resp_id.status_code, 200)
        html_id = resp_id.data.decode('utf-8')
        self.assertIn(cust_name, html_id)

        # 2. Test filtering by customer_search (partial name)
        part = cust_name.split()[0]
        resp_search = self.client.get(f'/reports/view/sales-order-profit?customer_search={part}&date_range=All')
        self.assertEqual(resp_search.status_code, 200)
        html_search = resp_search.data.decode('utf-8')
        self.assertIn(part, html_search)

    def test_csv_export_has_costing_column(self):
        """Verify the CSV export contains 'Costing ($)' and exports correct columns."""
        resp = self.client.get('/reports/export/sales-order-profit?date_range=All')
        self.assertEqual(resp.status_code, 200)
        content = resp.data.decode('utf-8')

        reader = csv.reader(io.StringIO(content))
        header = next(reader)
        self.assertIn('Costing ($)', header)
        self.assertIn('Sales Amount ($)', header)
        self.assertIn('Gross Profit ($)', header)
        # Costing ($) should be right near Gross Profit ($)
        costing_idx = header.index('Costing ($)')
        profit_idx = header.index('Gross Profit ($)')
        self.assertEqual(costing_idx + 1, profit_idx)

if __name__ == '__main__':
    unittest.main()
