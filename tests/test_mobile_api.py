import unittest
import time
from app import app
from database import query_one, execute_returning_id, get_db_cursor, resync_all_sequences
from routes.mobile_api import generate_mobile_token


class TestMobileApi(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_so_ids = []
        self.token = generate_mobile_token(1, 'admin')
        self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        if self.created_so_ids:
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM order_payments WHERE order_type = 'SO' AND order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_order_lines WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_order_versions WHERE sales_order_id = ANY(%s)", (self.created_so_ids,))
                cur.execute("DELETE FROM sales_orders WHERE id = ANY(%s)", (self.created_so_ids,))
            resync_all_sequences()

    def test_mobile_bootstrap_requires_auth_and_succeeds_with_token(self):
        res_unauth = self.client.get('/api/mobile/bootstrap')
        self.assertEqual(res_unauth.status_code, 401)

        res = self.client.get('/api/mobile/bootstrap', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('branches', data)
        self.assertIn('pricing_schemes', data)
        self.assertIn('default_khr_rate', data)

    def test_mobile_sales_list_and_search(self):
        res = self.client.get('/api/mobile/sales?status=Open&branch=main', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('orders', data)
        self.assertIn('counts', data)

    def test_mobile_customers_and_products_readonly(self):
        res_c = self.client.get('/api/mobile/customers?q=a', headers=self.headers)
        self.assertEqual(res_c.status_code, 200)
        self.assertTrue(res_c.get_json()['success'])

        res_p = self.client.get('/api/mobile/products?q=a', headers=self.headers)
        self.assertEqual(res_p.status_code, 200)
        self.assertTrue(res_p.get_json()['success'])

    def test_mobile_create_detail_complete_reopen_cancel_so(self):
        cust = query_one("SELECT id, branch_id FROM customers WHERE branch_id IS NULL LIMIT 1") or query_one("SELECT id, branch_id FROM customers LIMIT 1")
        prod = query_one("SELECT id, default_price, uom FROM products WHERE is_active = TRUE LIMIT 1")
        self.assertIsNotNone(cust)
        self.assertIsNotNone(prod)

        save_payload = {
            'customer_id': cust['id'],
            'branch_id': cust.get('branch_id') or '',
            'order_date': '2026-11-26',
            'notes': 'Mobile API test SO',
            'pricing_scheme_id': 100,
            'lines': [
                {
                    'product_id': prod['id'],
                    'quantity': 2,
                    'unit_price': float(prod.get('default_price') or 5.0),
                    'discount_percent': 0,
                    'uom': prod.get('uom') or 'pcs.'
                }
            ]
        }
        res_save = self.client.post('/api/mobile/sales/save', json=save_payload, headers=self.headers)
        self.assertEqual(res_save.status_code, 200)
        save_data = res_save.get_json()
        self.assertTrue(save_data['success'])
        oid = save_data['order_id']
        self.created_so_ids.append(oid)

        res_detail = self.client.get(f'/api/mobile/sales/{oid}', headers=self.headers)
        self.assertEqual(res_detail.status_code, 200)
        detail = res_detail.get_json()
        self.assertTrue(detail['success'])
        self.assertEqual(len(detail['lines']), 1)
        self.assertIn('/sales/', detail['print_url'])

        res_pay = self.client.post(f'/api/mobile/sales/{oid}/complete_pay', json={'payment_method': 'ABA Bank'}, headers=self.headers)
        self.assertEqual(res_pay.status_code, 200)
        self.assertEqual(res_pay.get_json()['status'], 'PAID')

        res_reopen = self.client.post(f'/api/mobile/sales/{oid}/reopen', json={}, headers=self.headers)
        self.assertEqual(res_reopen.status_code, 200)
        self.assertTrue(res_reopen.get_json()['success'])

        res_cancel = self.client.post(f'/api/mobile/sales/{oid}/cancel', json={}, headers=self.headers)
        self.assertEqual(res_cancel.status_code, 200)
        self.assertTrue(res_cancel.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
