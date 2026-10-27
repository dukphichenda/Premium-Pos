import unittest
import json
from app import create_app
from database import query_one, query_all
from routes.settings import get_mobile_app_config

class TestMobileAppSettings(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_settings_tab_renders_mobile_app_section(self):
        resp = self.client.get('/settings?tab=tabMobileApp')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="tabMobileApp"', html)
        self.assertIn('btnTabMobileApp', html)
        self.assertIn('Android App &amp; Mobile UI Designer', html)
        self.assertIn('id="phoneMockupFrame"', html)
        self.assertIn('id="mockupAppHeader"', html)
        self.assertIn('id="mockupBottomNav"', html)
        self.assertIn('inFlow-Premium.apk', html)
        self.assertIn('/settings/mobile-app/update', html)

        # Step-by-Step Wizard assertions
        self.assertIn('id="mobileStep1"', html)
        self.assertIn('id="mobileStep2"', html)
        self.assertIn('id="mobileStep3"', html)
        self.assertIn('id="mobileStep4"', html)
        self.assertIn('id="mobileStep5"', html)
        self.assertIn('id="mobileStep6"', html)
        self.assertIn('id="wizardPill1"', html)
        self.assertIn('id="wizardPill6"', html)
        self.assertIn('Continue to Step 2: Colors', html)
        self.assertIn('goToWizardStep(1)', html)
        self.assertIn('toggleWizardMode()', html)

        # Interactive Simulator assertions
        self.assertIn('id="simScreen_nav_delivery"', html)
        self.assertIn('id="simScreen_nav_orders"', html)
        self.assertIn('id="simScreen_nav_reports"', html)
        self.assertIn('id="simScreen_nav_scanner"', html)
        self.assertIn('id="simScreen_nav_more"', html)
        self.assertIn('id="simOrderModal"', html)
        self.assertIn('id="simCallOverlay"', html)
        self.assertIn('switchSimulatorTab', html)
        self.assertIn('triggerSimCall', html)
        self.assertIn('toggleSimOrderPaid', html)
        # Real system data assertions
        self.assertIn('Real System Invoices', html)
        self.assertIn('Recent Sales (Last 7 Days)', html)
        self.assertIn('SIM_SAMPLE_PRODUCT', html)

    def test_mobile_simulator_real_data(self):
        from routes.settings import get_mobile_simulator_real_data
        # Ensure products baseline count
        p_cnt_before = query_one("SELECT COUNT(*) as cnt FROM products")['cnt']
        data = get_mobile_simulator_real_data()
        self.assertIn('orders_dict', data)
        self.assertIn('orders_list', data)
        self.assertIn('driver_stats', data)
        self.assertIn('recent_summary', data)
        self.assertIn('sample_product', data)
        self.assertTrue(isinstance(data['orders_list'], list))
        p_cnt_after = query_one("SELECT COUNT(*) as cnt FROM products")['cnt']
        self.assertEqual(p_cnt_before, p_cnt_after)

    def test_api_mobile_config(self):
        resp = self.client.get('/api/mobile-config')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.get_data(as_text=True))
        self.assertIn('app_name', data)
        self.assertIn('theme_color', data)
        self.assertIn('accent_color', data)
        self.assertIn('bottom_nav_shortcuts', data)

    def test_mobile_app_settings_update(self):
        # Product catalog baseline before test
        p_cnt_before = query_one("SELECT COUNT(*) as cnt FROM products")['cnt']

        payload = {
            'app_name': 'inFlow Staff Mobile',
            'theme_color': '#1D4ED8',
            'accent_color': '#06B6D4',
            'app_icon_emoji': '🚀',
            'header_style': 'solid',
            'default_landing': 'delivery',
            'layout_density': 'comfortable',
            'font_size_scale': '100%',
            'border_radius': 'rounded',
            'enable_bottom_nav': '1',
            'hide_cost_profit_mobile': '1',
            'enable_tel_dialer': '1',
            'enable_quick_pay': '1',
            'enable_pull_refresh': '1',
            'shortcut_nav_delivery_title': 'Deliveries',
            'shortcut_nav_delivery_icon': '🛵',
            'shortcut_nav_delivery_url': '/reports/view/delivery-person-assign',
            'shortcut_nav_delivery_enabled': '1',
            'shortcut_nav_orders_title': 'Orders',
            'shortcut_nav_orders_icon': '📦',
            'shortcut_nav_orders_url': '/sales',
            'shortcut_nav_orders_enabled': '1',
            'shortcut_nav_reports_title': 'Reports',
            'shortcut_nav_reports_icon': '📊',
            'shortcut_nav_reports_url': '/reports',
            'shortcut_nav_reports_enabled': '1',
            'shortcut_nav_scanner_title': 'Scan',
            'shortcut_nav_scanner_icon': '📷',
            'shortcut_nav_scanner_url': '/sales/new',
            'shortcut_nav_scanner_enabled': '1',
            'shortcut_nav_more_title': 'Settings',
            'shortcut_nav_more_icon': '⚙️',
            'shortcut_nav_more_url': '/settings',
            'shortcut_nav_more_enabled': '1',
            'custom_mobile_css': '.staff-test { color: red; }'
        }

        resp = self.client.post('/settings/mobile-app/update', data=payload, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify config saved in DB
        cfg = get_mobile_app_config()
        self.assertEqual(cfg['app_name'], 'inFlow Staff Mobile')
        self.assertEqual(cfg['theme_color'], '#1D4ED8')
        self.assertEqual(cfg['accent_color'], '#06B6D4')
        self.assertEqual(cfg['app_icon_emoji'], '🚀')
        self.assertEqual(cfg['header_style'], 'solid')
        self.assertTrue(cfg['hide_cost_profit_mobile'])
        self.assertEqual(cfg['custom_mobile_css'], '.staff-test { color: red; }')

        # Product Catalog Protection: strictly zero product mutations
        p_cnt_after = query_one("SELECT COUNT(*) as cnt FROM products")['cnt']
        self.assertEqual(p_cnt_before, p_cnt_after)

if __name__ == '__main__':
    unittest.main()
