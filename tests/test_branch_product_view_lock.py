import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database import query_one, execute, execute_returning_id
from routes.auth import user_can_edit_product

class TestBranchProductViewLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Ensure a branch exists
        execute("INSERT INTO branches (id, code, name, is_active) VALUES (1, 'STM', 'Premium STM', TRUE) ON CONFLICT (id) DO NOTHING;")

        # Ensure a test product exists
        cls.prod_id = execute_returning_id("""
            INSERT INTO products (name, sku, default_price, standard_cost, uom, is_active)
            VALUES ('Branch Lock Test Product', 'SKU-LOCK-99', 12.50, 8.00, 'pcs.', TRUE)
            RETURNING id;
        """)

    @classmethod
    def tearDownClass(cls):
        execute("DELETE FROM product_boms WHERE product_id = %s;", (cls.prod_id,))
        execute("DELETE FROM product_combine_options WHERE product_id = %s;", (cls.prod_id,))
        execute("DELETE FROM products WHERE id = %s;", (cls.prod_id,))

    def test_permission_helper_function(self):
        with self.app.test_request_context():
            from flask import session

            # HQ Admin -> can edit
            session['user_id'] = 1
            session['role'] = 'main_admin'
            session['branch_id'] = None
            session['active_branch_id'] = None
            self.assertTrue(user_can_edit_product())

            # Branch Admin -> CANNOT edit
            session['role'] = 'branch_admin'
            session['branch_id'] = 1
            self.assertFalse(user_can_edit_product())

            # Cashier -> CANNOT edit
            session['role'] = 'cashier'
            session['branch_id'] = 1
            self.assertFalse(user_can_edit_product())

            # Sales -> CANNOT edit
            session['role'] = 'sales'
            session['branch_id'] = 1
            self.assertFalse(user_can_edit_product())

            # Main admin viewing in branch mode (?branch=1 or active_branch_id=1) -> CANNOT edit product master
            session['role'] = 'main_admin'
            session['branch_id'] = None
            session['active_branch_id'] = 1
            self.assertFalse(user_can_edit_product())

    def test_branch_user_view_catalog_ui_locked(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1
            sess['active_branch_id'] = 1

        res = self.client.get(f'/products/{self.prod_id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 1. Product details still visible normally
        self.assertIn('Branch Lock Test Product', html)
        self.assertIn('SKU-LOCK-99', html)

        # 2. View Only (Branch) badge must be present
        self.assertIn('View Only (Branch)', html)

        # 3. View-Only Banner explaining HQ management
        self.assertIn('Branch View-Only Mode', html)

        # 4. Save button must NOT be rendered for branch user
        self.assertNotIn('id="btnSaveProduct"', html)

        # 5. Dangerous action buttons must NOT be rendered for branch user
        self.assertNotIn('id="btnToggleActive"', html)
        self.assertNotIn('onclick="deleteCurrentProduct(', html)
        self.assertNotIn('+ Combined Kit', html)
        self.assertNotIn('Merge Duplicate', html)

        # 6. Title and SKU must be contenteditable="false"
        self.assertIn('contenteditable="false"', html)

        # 7. window.CAN_EDIT_PRODUCT must be false in JS
        self.assertIn('window.CAN_EDIT_PRODUCT = false;', html)

    def test_backend_endpoints_return_403_for_branch(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['role'] = 'branch_admin'
            sess['branch_id'] = 1
            sess['active_branch_id'] = 1

        # 1. update_ajax
        res = self.client.post(f'/products/{self.prod_id}/update_ajax',
                               json={'name': 'Hacked Product Name'},
                               headers={'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.get_json().get('success'))

        # 2. upload_picture
        res = self.client.post(f'/products/{self.prod_id}/upload_picture')
        self.assertEqual(res.status_code, 403)

        # 3. toggle_active
        res = self.client.post(f'/products/toggle_active/{self.prod_id}')
        self.assertEqual(res.status_code, 403)

        # 4. delete product
        res = self.client.post(f'/products/{self.prod_id}/delete')
        self.assertEqual(res.status_code, 403)

        # 5. combine type
        res = self.client.post(f'/api/products/{self.prod_id}/combine-type', json={'combine_type': 'multi'})
        self.assertEqual(res.status_code, 403)

        # 6. BOM add component
        res = self.client.post(f'/products/{self.prod_id}/boms/add', json={'component_product_id': 1, 'quantity': 1})
        self.assertEqual(res.status_code, 403)

        # Verify product was NOT modified
        prod = query_one("SELECT name FROM products WHERE id = %s", (self.prod_id,))
        self.assertEqual(prod['name'], 'Branch Lock Test Product')

    def test_hq_main_admin_can_edit_normally(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['branch_id'] = None
            sess['active_branch_id'] = None

        res = self.client.get(f'/products/{self.prod_id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Save button and actions present for HQ
        self.assertIn('id="btnSaveProduct"', html)
        self.assertIn('window.CAN_EDIT_PRODUCT = true;', html)
        self.assertNotIn('Branch View-Only Mode', html)

        # Update ajax succeeds for HQ
        res2 = self.client.post(f'/products/{self.prod_id}/update_ajax',
                                json={'barcode': 'BARCODE-HQ-123'},
                                headers={'Content-Type': 'application/json'})
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json().get('success'))

        # Verify change was applied
        prod = query_one("SELECT barcode FROM products WHERE id = %s", (self.prod_id,))
        self.assertEqual(prod['barcode'], 'BARCODE-HQ-123')

if __name__ == '__main__':
    unittest.main()
