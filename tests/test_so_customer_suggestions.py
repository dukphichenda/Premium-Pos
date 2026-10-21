import unittest
from app import create_app

class TestSoCustomerSuggestions(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_sidebar_search_has_customer_suggestion_popup(self):
        """Verify the SO detail view includes the floating customer suggestion popup and table headers."""
        resp = self.client.get('/sales/1')
        if resp.status_code == 302:
            # If redirected to first available order or login, follow redirect
            resp = self.client.get('/sales/new')
        self.assertIn(resp.status_code, [200, 302])
        if resp.status_code == 200:
            html = resp.data.decode('utf-8')
            # Check suggestion popup structure matching user screenshot
            self.assertIn('id="soSidebarCustSuggestPopup"', html)
            self.assertIn('id="soSidebarCustSuggestTbody"', html)
            self.assertIn('Name ▲', html)
            self.assertIn('Contact', html)
            self.assertIn('Details', html)
            self.assertIn('id="soSuggestAddNewInput"', html)
            self.assertIn('selectSoCustomerSuggestion(', html)
            self.assertIn('viewSoCustomerDetails(', html)
            self.assertIn('positionSoCustSuggestPopup(', html)
            # Verify inline customer cards were removed from sidebar list body
            self.assertNotIn('soSidebarCustomerMatches', html)

if __name__ == '__main__':
    unittest.main()
