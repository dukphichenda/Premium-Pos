import unittest
import os
import re

class TestProductImageSaveAndExit(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.catalog_path = os.path.join(self.base_dir, 'templates', 'products', 'catalog.html')
        self.detail_path = os.path.join(self.base_dir, 'templates', 'products', 'detail.html')
        self.routes_path = os.path.join(self.base_dir, 'routes', 'products.py')

    def test_catalog_html_staged_image_and_save_guard(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Must have stagedProductImageFile and originalProductImageUrl
        self.assertIn('stagedProductImageFile', content)
        self.assertIn('originalProductImageUrl', content)

        # stageProductImage should set dirty state and NOT fetch /upload_picture immediately
        stage_fn_idx = content.find('function stageProductImage(file, id)')
        self.assertNotEqual(stage_fn_idx, -1, "stageProductImage function must exist")
        stage_body = content[stage_fn_idx:stage_fn_idx + 600]
        self.assertNotIn('fetch(', stage_body, "stageProductImage must not call fetch immediately")
        self.assertIn('stagedProductImageFile = file;', stage_body)
        self.assertIn('setDirtyState(true);', stage_body)

        # saveProductChanges must upload stagedProductImageFile before finishing save
        self.assertIn('if (stagedProductImageFile) {', content)
        self.assertIn('/upload_picture', content)

        # discardAndNavigate must revert preview and clear stagedProductImageFile
        discard_fn_idx = content.find('function discardAndNavigate()')
        self.assertNotEqual(discard_fn_idx, -1, "discardAndNavigate function must exist")
        discard_body = content[discard_fn_idx:discard_fn_idx + 800]
        self.assertIn('stagedProductImageFile = null', discard_body)
        self.assertIn('originalProductImageUrl', discard_body)

        # Unsaved modal must exist
        self.assertIn('id="unsavedChangesModal"', content)
        self.assertIn('discardAndNavigate()', content)
        self.assertIn('saveAndNavigate()', content)
        self.assertIn('closeUnsavedModal()', content)

        # Exit interception
        self.assertIn('window.handleTabCloseAttempt', content)
        self.assertIn('targetNavigationUrl = href;', content)
        self.assertIn('openUnsavedModal();', content)

    def test_detail_html_staged_image_and_exit_modal(self):
        with open(self.detail_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # setPastedImageToDetail must not execute immediate fetch /upload_picture
        paste_fn_idx = content.find('function setPastedImageToDetail(file)')
        self.assertNotEqual(paste_fn_idx, -1, "setPastedImageToDetail function must exist")
        paste_body = content[paste_fn_idx:paste_fn_idx + 1500]
        self.assertNotIn('fetch(', paste_body, "setPastedImageToDetail must not immediately fetch /upload_picture")
        self.assertIn('markDetailDirty()', paste_body)

        # Unsaved modal for detail.html must exist
        self.assertIn('id="unsavedChangesModalDetail"', content)
        self.assertIn('discardAndNavigateDetail()', content)
        self.assertIn('saveAndNavigateDetail()', content)
        self.assertIn('closeUnsavedModalDetail()', content)

        # Exit guards
        self.assertIn('closeProductDetailView', content)
        self.assertIn('isDirtyDetail', content)
        self.assertIn('window.handleTabCloseAttempt', content)

    def test_routes_next_url_support(self):
        with open(self.routes_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Both create_product and edit_product should support next_url redirect
        self.assertIn("next_url = request.form.get('next_url')", content)
        self.assertIn("if next_url:\n            return redirect(next_url)", content)

    def test_showcase_uses_top_save_button(self):
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Verify showcase toolbar does not contain separate Save button
        showcase_toolbar_idx = content.find('class="inflow-price-showcase-actions"')
        self.assertNotEqual(showcase_toolbar_idx, -1)
        toolbar_snippet = content[showcase_toolbar_idx:showcase_toolbar_idx + 3500]
        self.assertNotIn('onclick="savePriceCardSettings()"', toolbar_snippet)
        self.assertNotIn('💾 Save', toolbar_snippet)
        self.assertNotIn('💾 រក្សាទុក', toolbar_snippet)

        # Verify tier changes call markFieldDirty
        self.assertIn("markFieldDirty('tier_qty_' + idx, qty)", content)
        self.assertIn("markFieldDirty('tier_price_' + idx, tot)", content)

if __name__ == '__main__':
    unittest.main()
