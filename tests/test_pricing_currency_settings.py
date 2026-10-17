import unittest
from app import app
from database import query_one, execute

class TestPricingCurrencySettings(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'
            sess['is_admin'] = True

    def test_pricing_currency_tab_renders(self):
        resp = self.client.get('/settings?tab=tabPricing')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('btnTabPricing', html)
        self.assertIn('tabPricing', html)
        self.assertIn('Pricing Schemes', html)
        self.assertIn('KHR Exchange Rate', html)
        self.assertIn('pricingSchemeModalOverlay', html)

    def test_update_currency_settings(self):
        resp = self.client.post('/settings/currency/update', data={
            'currency_code': 'USD',
            'currency_symbol': '$',
            'khr_exchange_rate': '4080',
            'enable_khr_total': 'true',
            'decimal_places_price': '2',
            'decimal_places_cost': '3',
            'decimal_places_markup': '2'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    def test_pricing_scheme_crud(self):
        # Create
        scheme_name = 'Automated Test Tier'
        execute("DELETE FROM pricing_schemes WHERE name = %s", (scheme_name,))
        resp = self.client.post('/settings/pricing-schemes/create', data={
            'name': scheme_name,
            'currency': 'US Dollar ($)',
            'is_default': ''
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        row = query_one("SELECT id, name, currency, is_active FROM pricing_schemes WHERE name = %s", (scheme_name,))
        self.assertIsNotNone(row)
        sid = row['id']

        # Toggle Active
        resp = self.client.post(f'/settings/pricing-schemes/{sid}/toggle-active')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])

        # Update
        resp = self.client.post(f'/settings/pricing-schemes/{sid}/update', json={
            'name': 'Automated Test Tier Updated',
            'currency': 'Cambodian Riel (KHR)'
        })
        self.assertEqual(resp.status_code, 200)

        # Delete
        resp = self.client.post(f'/settings/pricing-schemes/{sid}/delete', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        execute("DELETE FROM pricing_schemes WHERE id = %s", (sid,))

if __name__ == '__main__':
    unittest.main()
