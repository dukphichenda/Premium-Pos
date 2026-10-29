# -*- coding: utf-8 -*-
"""
Unit tests for Mobile View Simulation in Settings
Verifies template markup, navigation links, iframe embedding, and device presets.
"""

import unittest
import os
import re

class TestMobileViewSimulation(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.general_html_path = os.path.join(self.base_dir, 'templates', 'settings', 'general.html')
        self.base_html_path = os.path.join(self.base_dir, 'templates', 'base.html')
        self.routes_settings_path = os.path.join(self.base_dir, 'routes', 'settings.py')

        with open(self.general_html_path, 'r', encoding='utf-8') as f:
            self.general_html = f.read()

        with open(self.base_html_path, 'r', encoding='utf-8') as f:
            self.base_html = f.read()

        with open(self.routes_settings_path, 'r', encoding='utf-8') as f:
            self.routes_settings = f.read()

    def test_sidebar_flyout_has_mobile_sim_link(self):
        """Ensure templates/base.html has the Mobile View Simulation link under flyout-settings."""
        self.assertIn("tab='tabMobileSim'", self.base_html)
        self.assertTrue("Mobile View & Android App" in self.base_html or "Mobile View Simulation" in self.base_html)

    def test_settings_sidebar_has_tab_button(self):
        """Ensure templates/settings/general.html has Tab 8 navigation button for Mobile View Simulation."""
        self.assertIn('id="btnTabMobileSim"', self.general_html)
        self.assertIn("switchSettingsTab('tabMobileSim', this)", self.general_html)
        self.assertTrue("Mobile View & Android App" in self.general_html or "Mobile View Simulation" in self.general_html)

    def test_tab_pane_container_exists(self):
        """Ensure id='tabMobileSim' settings-tab-pane container exists."""
        self.assertIn('id="tabMobileSim"', self.general_html)
        self.assertIn('class="settings-tab-pane"', self.general_html)

    def test_interactive_iframe_and_chassis(self):
        """Ensure the phone hardware mockup chassis and iframe screen are present."""
        self.assertIn('id="simDeviceChassis"', self.general_html)
        self.assertIn('id="simScreenViewport"', self.general_html)
        self.assertIn('id="simDeviceIframe"', self.general_html)
        self.assertIn('id="simDeviceStatusBar"', self.general_html)
        self.assertIn('id="simDeviceHomeBar"', self.general_html)
        self.assertIn('/sales/new?embed=1', self.general_html)

    def test_device_presets_available(self):
        """Ensure key device presets exist: iPhone 15/16 (390x844), Galaxy S24 (360x780), Compact (320x568), Tablet (768x1024)."""
        self.assertIn('applySimDevicePreset(390, 844', self.general_html)
        self.assertIn('applySimDevicePreset(360, 780', self.general_html)
        self.assertIn('applySimDevicePreset(320, 568', self.general_html)
        self.assertIn('applySimDevicePreset(768, 1024', self.general_html)

    def test_hardware_controls_available(self):
        """Ensure rotate, zoom, and reload controls exist."""
        self.assertIn('toggleSimOrientation()', self.general_html)
        self.assertIn('reloadSimIframe()', self.general_html)
        self.assertIn('setSimZoom(0.75', self.general_html)
        self.assertIn('setSimZoom(1.0', self.general_html)
        self.assertIn('openMobileSimPopup()', self.general_html)

    def test_desktop_mobile_toggle_button(self):
        """Ensure 1-click toggle to switch desktop session to mobile view mode exists."""
        self.assertIn('toggleDesktopMobileModeFromSim()', self.general_html)
        self.assertIn('id="btnSimToggleGlobalView"', self.general_html)

    def test_routes_settings_extracts_latest_so(self):
        """Ensure routes/settings.py extracts latest_so_id and passes to general.html."""
        self.assertIn('latest_so_id', self.routes_settings)
        self.assertIn('latest_so_title', self.routes_settings)

    def test_javascript_controller_functions(self):
        """Ensure JS controller functions are defined in general.html."""
        functions = [
            'function initMobileSimulator()',
            'function toggleDesktopMobileModeFromSim()',
            'function loadSimPage(',
            'function applySimDevicePreset(',
            'function toggleSimOrientation()',
            'function reloadSimIframe()',
            'function onSimIframeLoaded()'
        ]
        for fn in functions:
            self.assertIn(fn, self.general_html)

if __name__ == '__main__':
    unittest.main()

