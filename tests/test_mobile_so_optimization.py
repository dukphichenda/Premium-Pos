import unittest
import os
import re

class TestMobileSaleOrderOptimization(unittest.TestCase):
    def setUp(self):
        self.canvas_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', '_detail_canvas.html')
        self.detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'sales', 'detail.html')
        self.styles_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'styles.css')
        with open(self.canvas_path, 'r', encoding='utf-8') as f:
            self.canvas_html = f.read()
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            self.detail_html = f.read()
        with open(self.styles_path, 'r', encoding='utf-8') as f:
            self.styles_css = f.read()

    def test_mobile_top_section_cards(self):
        """Test the 3 structured mobile top cards: Order Info, Customer Selection, Order Settings & Delivery."""
        self.assertIn('so-mobile-info-card', self.canvas_html)
        self.assertIn('so-mobile-cust-card', self.canvas_html)
        self.assertIn('so-mobile-settings-card', self.canvas_html)
        self.assertIn('mobileSettingsDrawer', self.canvas_html)
        self.assertIn('toggleMobileSettingsDrawer', self.canvas_html)
        self.assertIn('mobileLogisticsSummary', self.canvas_html)

    def test_all_12_mobile_slots_exist(self):
        """Verify that all 12 mobile slots defined in SO_MOBILE_SLOT_MAP exist in canvas DOM."""
        slots = [
            'slotMobileCustomer',
            'slotMobileDate',
            'slotMobileOrderNumber',
            'slotMobileStatus',
            'slotMobilePhone',
            'slotMobileSalesRep',
            'slotMobileAddress',
            'slotMobileBranch',
            'slotMobileLocation',
            'slotMobileDeliveryBy',
            'slotMobileDeliveryFee',
            'slotMobileDeliveryNotes'
        ]
        for slot in slots:
            self.assertIn(f'id="{slot}"', self.canvas_html, f"Missing slot: {slot}")

    def test_quantity_stepper_controls(self):
        """Verify stepper buttons [-] and [+] exist in canvas template and detail JS."""
        self.assertIn('so-qty-btn-minus', self.canvas_html)
        self.assertIn('so-qty-btn-plus', self.canvas_html)
        self.assertIn('stepLineQty(this, -1)', self.canvas_html)
        self.assertIn('stepLineQty(this, 1)', self.canvas_html)
        self.assertIn('function stepLineQty', self.canvas_html)
        self.assertIn('stepLineQty', self.detail_html)

    def test_empty_items_notice_and_add_row(self):
        """Verify empty state notice and mobile add row button exist."""
        self.assertIn('id="soEmptyItemsNotice"', self.canvas_html)
        self.assertIn('No products added yet', self.canvas_html)
        self.assertIn('id="soMobileAddRowBar"', self.canvas_html)
        self.assertIn('addNewBlankLine()', self.canvas_html)

    def test_sticky_bottom_bar_and_drawer(self):
        """Verify sticky bottom bar and expandable summary drawer."""
        self.assertIn('id="mobileStickyBottomBar"', self.canvas_html)
        self.assertIn('id="mobileStickyItemsCount"', self.canvas_html)
        self.assertIn('id="mobileStickyGrandTotal"', self.canvas_html)
        self.assertIn('id="mobileStickyPayBtn"', self.canvas_html)
        self.assertIn('id="mobileSummaryDrawer"', self.canvas_html)
        self.assertIn('id="mobileSummaryBackdrop"', self.canvas_html)
        self.assertIn('toggleMobileSummaryDrawer', self.canvas_html)

    def test_mobile_payment_workflow_modal(self):
        """Verify dedicated mobile payment modal with ABA, Cash, ACLEDA, KB PRASAC, Other Payment tiles."""
        self.assertIn('id="mobilePaymentModal"', self.canvas_html)
        self.assertIn('id="mobilePaymentModalBackdrop"', self.canvas_html)
        self.assertIn('id="mobileModalBalanceDue"', self.canvas_html)
        self.assertIn('id="mobileModalPaidInput"', self.canvas_html)
        self.assertIn('id="mobileConfirmPayBtn"', self.canvas_html)
        self.assertIn('ABA Bank', self.canvas_html)
        self.assertIn('Cash', self.canvas_html)
        self.assertIn('ACLEDA', self.canvas_html)
        self.assertIn('KB PRASAC', self.canvas_html)
        self.assertIn('Other Payment', self.canvas_html)
        self.assertIn('selectMobilePayMethod', self.canvas_html)
        self.assertIn('fillMobileFullAmount', self.canvas_html)
        self.assertIn('confirmMobilePaymentAndComplete', self.canvas_html)

    def test_brown_palette_styling(self):
        """Verify brown palette colors (#795548, #4E342E, #EFEBE9) are defined in CSS."""
        self.assertIn('#795548', self.canvas_html)
        self.assertIn('#4E342E', self.canvas_html)
        self.assertIn('#EFEBE9', self.canvas_html)
        self.assertIn('background: #4E342E;', self.detail_html)

    def test_totals_recalculation_sync(self):
        """Verify recalculateTotals synchronizes mobile elements and toggles empty notice."""
        self.assertIn('mobileStickyItemsCount', self.detail_html)
        self.assertIn('mobileStickyGrandTotal', self.detail_html)
        self.assertIn('mobileStickyPayBtnTotal', self.detail_html)
        self.assertIn('soEmptyItemsNotice', self.detail_html)

    def test_item_adding_box_full_width_stretch(self):
        """Verify that the item adding box and .so-main-left stretch 100% without 268px squishing."""
        self.assertIn('html.is-mobile-view .so-main-left', self.canvas_html)
        self.assertIn('html.is-mobile-view .so-card-items', self.canvas_html)
        self.assertIn('@media (max-width: 1024px)', self.canvas_html)
        self.assertIn('@media (max-width: 1024px)', self.detail_html)
        # Verify min-width 720px is not constraining mobile in styles.css
        self.assertIn('html.is-mobile-view #lineItemsTable {\n  min-width: 0 !important;', self.styles_css)

if __name__ == '__main__':
    unittest.main()
