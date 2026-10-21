import unittest
import os
from routes.products import _build_price_card_data

class TestPriceCardCustomDetailToggle(unittest.TestCase):
    def test_build_price_card_data_auto_specs_when_not_custom(self):
        """When price_card_is_custom_detail is False, custom_detail is empty and auto specs are used."""
        mock_product = {
            'name': 'lid 80B lid 80mm',
            'sku': 'lid 80B',
            'price_card_unit': 'កែវ',
            'length': 8.0,
            'width': 8.0,
            'height': 2.0,
            'packs_per_case': 20.0,
            'pcs_per_pack': 50.0,
            'sales_uom_ratio_std': 1000.0,
            'price_card_is_custom_detail': False,
            'price_card_custom_detail': 'Old custom text that was disabled'
        }
        card = _build_price_card_data(mock_product, [], can_view_costs=False)
        self.assertFalse(card['is_custom_detail'])
        self.assertEqual(card['custom_detail'], '')
        self.assertIn('8cm x 8cm x 2cm', card['auto_detail_text'])
        # modern_specs_rows must be derived from auto_detail_text, not the disabled custom text
        rows_text = ' '.join(r['main'] for r in card['modern_specs_rows'])
        self.assertNotIn('Old custom text', rows_text)
        self.assertTrue(any('8cm' in r['main'] for r in card['modern_specs_rows']))

    def test_build_price_card_data_uses_custom_when_enabled(self):
        """When price_card_is_custom_detail is True, custom_detail is preserved and parsed."""
        mock_product = {
            'name': 'lid 80B lid 80mm',
            'sku': 'lid 80B',
            'price_card_unit': 'កែវ',
            'length': 8.0,
            'width': 8.0,
            'height': 2.0,
            'packs_per_case': 20.0,
            'pcs_per_pack': 50.0,
            'sales_uom_ratio_std': 1000.0,
            'price_card_is_custom_detail': True,
            'price_card_custom_detail': '★ ទំហំពិសេស: 80mm\n• 1 កេស មាន 1000 PCS'
        }
        card = _build_price_card_data(mock_product, [], can_view_costs=False)
        self.assertTrue(card['is_custom_detail'])
        self.assertEqual(card['custom_detail'], '★ ទំហំពិសេស: 80mm\n• 1 កេស មាន 1000 PCS')
        rows_text = ' '.join(r['main'] for r in card['modern_specs_rows'])
        self.assertIn('80mm', rows_text)

    def test_catalog_html_no_resurrection_bug(self):
        """Verify catalog.html does not have the old bug where currentCustomVal.length > 0 resurrected custom detail."""
        html_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # The old buggy check must NOT exist
        self.assertNotIn("pendingChanges['price_card_is_custom_detail'] = chkCustomEl.checked || (currentCustomVal.length > 0)", content)
        self.assertNotIn("currentCustomVal.length > 0 && !chkCustomEl.defaultChecked", content)

        # The clean boolean assignment must exist
        self.assertIn("pendingChanges['price_card_is_custom_detail'] = isCustomChecked;", content)
        self.assertIn("pendingChanges['price_card_custom_detail'] = '';", content)

        # Textareas must NOT be pre-filled with auto specs when is_custom_detail is false
        self.assertIn("{{ price_card.custom_detail if (price_card and price_card.is_custom_detail and price_card.custom_detail) else '' }}", content)

        # In toggleCustomPriceCardDetail, disabling must clear textareas and mark custom detail empty
        self.assertIn("markFieldDirty('price_card_is_custom_detail', false);", content)
        self.assertIn("markFieldDirty('price_card_custom_detail', '');", content)

if __name__ == '__main__':
    unittest.main()
