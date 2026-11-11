import unittest
import os
import re

class TestExpenseNormalZeroFont(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.monthly_html_path = os.path.join(self.base_dir, 'templates', 'expenses', 'monthly.html')
        self.dashboard_html_path = os.path.join(self.base_dir, 'templates', 'expenses', 'dashboard.html')
        self.styles_css_path = os.path.join(self.base_dir, 'static', 'css', 'styles.css')
        self.pos_html_path = os.path.join(self.base_dir, 'templates', 'branches', 'pos.html')

    def test_no_jetbrains_mono_in_expenses(self):
        """Verify JetBrains Mono (which renders dotted 0) is not used in expense templates."""
        with open(self.monthly_html_path, 'r', encoding='utf-8') as f:
            monthly_content = f.read()
        self.assertNotIn('JetBrains Mono', monthly_content, "monthly.html should not use JetBrains Mono for numbers")

        with open(self.dashboard_html_path, 'r', encoding='utf-8') as f:
            dashboard_content = f.read()
        self.assertNotIn('JetBrains Mono', dashboard_content, "dashboard.html should not use JetBrains Mono for numbers")

    def test_css_kpi_and_acc_inputs_use_clean_tabular_fonts(self):
        """Verify CSS .kpi-card-value and .acc-val-input do not use JetBrains Mono or bare monospace."""
        with open(self.styles_css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()

        # Find .kpi-card-value rule block
        kpi_block_match = re.search(r'\.kpi-card-value\s*\{([^}]+)\}', css_content)
        self.assertIsNotNone(kpi_block_match, ".kpi-card-value rule must exist")
        kpi_block = kpi_block_match.group(1)
        self.assertNotIn('JetBrains Mono', kpi_block)
        self.assertIn('tabular-nums', kpi_block)

        # Find .acc-val-input rule block
        acc_block_match = re.search(r'\.acc-val-input\s*\{([^}]+)\}', css_content)
        self.assertIsNotNone(acc_block_match, ".acc-val-input rule must exist")
        acc_block = acc_block_match.group(1)
        self.assertNotIn('JetBrains Mono', acc_block)
        self.assertIn('tabular-nums', acc_block)

    def test_pos_receipt_uses_clean_font_for_order_and_amounts(self):
        """Verify POS receipt order number and totals do not use bare monospace font."""
        with open(self.pos_html_path, 'r', encoding='utf-8') as f:
            pos_content = f.read()

        self.assertNotIn('id="recOrderNum" style="color: #000000; font-family: monospace;', pos_content)
        self.assertNotIn('id="recSubtotal" style="font-family: monospace;', pos_content)
        self.assertNotIn('id="recTotal" style="font-size: 16px; font-family: monospace;', pos_content)

    def test_monthly_kpi_and_inputs_have_embedded_and_inline_clean_fonts(self):
        """Verify monthly.html embeds style block and inline styles for KPI cards and inputs."""
        with open(self.monthly_html_path, 'r', encoding='utf-8') as f:
            monthly_content = f.read()

        # Embedded style block
        self.assertIn('.kpi-card-value,', monthly_content)
        self.assertIn('.acc-val-input,', monthly_content)

        # Inline styles on Clear STM and Media KPI cards
        self.assertIn('class="kpi-card-value teal-text" style="font-family:', monthly_content)
        self.assertIn('class="kpi-card-value green-text" style="font-family:', monthly_content)

        # Inline style on acc-val-input
        self.assertIn('class="acc-val-input"', monthly_content)
        self.assertIn('style="font-family: \'Inter\', \'Segoe UI\'', monthly_content)

if __name__ == '__main__':
    unittest.main()

