# -*- coding: utf-8 -*-
"""
Unit tests for verification of Mobile View removal and PC mode enforcement.
Ensures:
1. Mobile View settings tab and simulator are removed from Settings.
2. Bottom-left sidebar view switch button is removed.
3. Mobile drawer view switch buttons are removed.
4. Settings route redirects tabMobileSim and tabMobileApp to tabCompany.
5. base.html and inflow_tabs.js enforce desktop view mode.
"""

import unittest
import os

class TestMobileViewSimulationRemoval(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.general_html_path = os.path.join(self.base_dir, 'templates', 'settings', 'general.html')
        self.base_html_path = os.path.join(self.base_dir, 'templates', 'base.html')
        self.routes_settings_path = os.path.join(self.base_dir, 'routes', 'settings.py')
        self.inflow_tabs_path = os.path.join(self.base_dir, 'static', 'js', 'inflow_tabs.js')

        with open(self.general_html_path, 'r', encoding='utf-8') as f:
            self.general_html = f.read()

        with open(self.base_html_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()

        with open(self.routes_settings_path, 'r', encoding='utf-8') as f:
            self.routes_settings = f.read()

        with open(self.inflow_tabs_path, 'r', encoding='utf-8') as f:
            self.inflow_tabs = f.read()

    def test_sidebar_flyout_no_mobile_sim_link(self):
        """Ensure templates/base.html has removed the Mobile View Simulation link."""
        self.assertNotIn("tab='tabMobileSim'", self.base_html)
        self.assertNotIn("Mobile View & Android App", self.base_html)

    def test_settings_sidebar_no_mobile_tab_button(self):
        """Ensure templates/settings/general.html has removed Tab button for Mobile View Simulation."""
        self.assertNotIn('id="btnTabMobileSim"', self.general_html)
        self.assertNotIn('id="btnTabMobileApp"', self.general_html)

    def test_tab_pane_mobile_containers_removed(self):
        """Ensure tabMobileSim and tabMobileApp panes are removed from general.html."""
        self.assertNotIn('id="tabMobileSim"', self.general_html)
        self.assertNotIn('id="tabMobileApp"', self.general_html)
        self.assertNotIn('id="simDeviceChassis"', self.general_html)
        self.assertNotIn('id="simScreenViewport"', self.general_html)

    def test_sidebar_view_mode_toggle_removed(self):
        """Ensure the dual device switcher button is removed from templates/base.html."""
        self.assertNotIn('id="sidebarViewModeItem"', self.base_html)
        self.assertNotIn('id="sidebarViewModeBtn"', self.base_html)
        self.assertNotIn('id="flyout-integrations"', self.base_html)

    def test_mobile_drawer_view_mode_switch_removed(self):
        """Ensure 1-click switch buttons for display mode are removed from drawer."""
        self.assertNotIn('id="drawerBtnMobileView"', self.base_html)
        self.assertNotIn('id="drawerBtnDesktopView"', self.base_html)

    def test_routes_settings_redirects_mobile_tab_to_company(self):
        """Ensure routes/settings.py redirects tabMobileSim or tabMobileApp to tabCompany."""
        self.assertIn("if active_tab in ('tabMobileApp', 'tabMobileSim'):", self.routes_settings)
        self.assertIn("active_tab = 'tabCompany'", self.routes_settings)

    def test_always_pc_desktop_mode(self):
        """Ensure base.html always returns desktop mode."""
        self.assertIn("function inflowDetectDeviceViewMode() {\n            return 'desktop';", self.base_html)
        self.assertIn("function getCurrentViewMode() {\n            return 'desktop';", self.base_html)
        self.assertIn("const curViewMode = 'desktop';", self.inflow_tabs)

if __name__ == '__main__':
    unittest.main()
