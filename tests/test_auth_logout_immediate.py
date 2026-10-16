import unittest
from app import create_app

class AuthLogoutImmediateTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def test_standard_logout_redirects_to_login(self):
        """Standard browser navigation to /logout redirects directly to /login."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'

        res = self.client.get('/logout')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

        # Session must be completely cleared
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)

    def test_embedded_iframe_logout_returns_frame_buster(self):
        """If logout is invoked from an iframe (embed=1), returns frame-buster navigating window.top."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        res = self.client.get('/logout?embed=1')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("window.top.location.href", html)
        self.assertIn("/login", html)

    def test_json_ajax_logout_returns_json_redirect(self):
        """If logout is called via fetch/ajax, returns redirect_url for immediate top window navigation."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        res = self.client.get('/logout', headers={'Accept': 'application/json'})
        self.assertEqual(res.status_code, 200)
        import json
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['redirect_url'], '/login')

    def test_login_page_safe_in_iframe(self):
        """Login page must not render inside an iframe, safely redirecting iframe to dashboard."""
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("window.self !== window.top", html)
        self.assertIn("login", html)

    def test_login_persistence_no_auto_logout(self):
        """Logged in session accessing dashboard stays logged in without redirecting to login."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['display_name'] = 'Dok Chenda'
            sess['role'] = 'main_admin'

        res = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(res.status_code, 200)

if __name__ == '__main__':
    unittest.main()
