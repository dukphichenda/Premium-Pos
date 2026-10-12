import unittest
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def test_health_check(self):
        """Verify /health endpoint returns healthy and PostgreSQL version"""
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertIn('PostgreSQL', data['database'])

    def test_dashboard_page(self):
        """Verify dashboard page loads with 200 OK"""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Executive Inventory Overview', res.data)

    def test_dashboard_charts_api(self):
        """Verify dashboard chart data API returns JSON with valid series"""
        res = self.client.get('/api/dashboard/charts')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('monthly_labels', data)
        self.assertIn('monthly_revenue', data)
        self.assertIn('category_labels', data)

    def test_product_search_api(self):
        """Verify /api/products/search autocomplete endpoint returns matches"""
        res = self.client.get('/api/products/search?q=HT')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)

    def test_customer_search_api(self):
        """Verify /api/customers/search autocomplete endpoint returns matches"""
        res = self.client.get('/api/customers/search?q=a')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)

    def test_routes_accessible(self):
        """Verify all primary pages render without errors"""
        routes = [
            '/products',
            '/inventory',
            '/inventory/adjustments',
            '/inventory/transfers',
            '/inventory/reorder',
            '/sales',
            '/sales/create',
            '/purchases',
            '/purchases/create',
            '/customers',
            '/vendors',
            '/locations',
            '/reports/valuation',
            '/reports/sales',
            '/reports/movement-log',
            '/settings',
            '/settings/migration'
        ]
        for route in routes:
            res = self.client.get(route, follow_redirects=True)
            self.assertEqual(res.status_code, 200, f"Route {route} failed with status {res.status_code}")

if __name__ == '__main__':
    unittest.main()
