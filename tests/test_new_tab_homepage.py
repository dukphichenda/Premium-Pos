import unittest
import os
from app import create_app

class TestNewTabHomepageFeature(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_dashboard_renders_inflow_workflow_and_accent(self):
        """Verify homepage loads with inFlow top accent bar, workflow diagram and nodes"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        
        # Verify accent bar for homepage
        self.assertIn('inflow-top-accent-bar home', html)
        
        # Verify workflow card container
        self.assertIn('inflow-workflow-card', html)
        self.assertIn('inflow-workflow-track', html)
        
        # Verify all 5 workflow map nodes matching inFlow Inventory
        self.assertIn('VENDOR', html)
        self.assertIn('Purchase Order', html)
        self.assertIn('INVENTORY', html)
        self.assertIn('Sales Order', html)
        self.assertIn('CUSTOMER', html)
        
        # Verify tab registration in dashboard script
        self.assertIn("window.initInflowTabs", html)
        self.assertIn("type: 'home'", html)

    def test_inflow_tabs_js_implements_direct_homepage_tab(self):
        """Verify inflow_tabs.js creates Homepage tab directly on '+' click without option dropdown"""
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'inflow_tabs.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Verify DEFAULT_TABS includes Homepage
        self.assertIn("type: 'home'", js_content)
        self.assertIn("title: 'Homepage'", js_content)

        # Verify direct homepage tab addition on '+'
        self.assertIn("window.addNewHomepageTab = function", js_content)
        self.assertIn("id: newId", js_content)
        self.assertIn("type: 'home'", js_content)
        self.assertIn("window.location.href = '/'", js_content)

        # Verify '+' button invokes addNewHomepageTab directly without dropdown menu
        self.assertIn('onclick="window.addNewHomepageTab(event)"', js_content)

        # Verify iframe login intercept prevents login screen in tabs
        self.assertIn("iframe.contentWindow.location.replace('/dashboard?embed=1')", js_content)
        self.assertIn("cleanCurrent.startsWith('/login')", js_content)

    def test_remember_token_generation_and_verification(self):
        """Verify HMAC remember token generates and verifies correctly"""
        from routes.auth import generate_remember_token, verify_remember_token
        tok = generate_remember_token(1, 'admin')
        self.assertTrue(bool(tok))
        verified_uid = verify_remember_token(tok)
        self.assertEqual(verified_uid, 1)

        # Tampered token fails
        bad_tok = tok + 'tampered'
        self.assertIsNone(verify_remember_token(bad_tok))

    def test_login_embed_redirects_to_dashboard(self):
        """Verify /login?embed=1 immediately redirects to /dashboard?embed=1 without rendering login form"""
        response = self.client.get('/login?embed=1')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard?embed=1', response.headers.get('Location', ''))

    def test_authenticated_user_login_get_redirects_to_dashboard(self):
        """Verify logged in user requesting /login is redirected to /dashboard"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers.get('Location', ''))

if __name__ == '__main__':
    unittest.main()
