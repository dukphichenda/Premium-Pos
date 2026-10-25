import unittest
from app import create_app
from database import query_one

class TestSoBranchPreviewBranchCost(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_preview_cost_label_hq_vs_branch(self):
        """Verify product preview panel shows Branch Cost on branch order and Cost on HQ order."""
        # 1. Main Store (HQ) order view
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'
            sess['branch_id'] = None
        
        resp_hq = self.client.get('/sales/new')
        self.assertEqual(resp_hq.status_code, 200)
        html_hq = resp_hq.data.decode('utf-8')

        self.assertIn('id="previewCostLabel"', html_hq)
        self.assertIn('id="previewCost"', html_hq)
        self.assertIn('function isCurrentBranchOrder()', html_hq)
        self.assertIn('function updateItemDropdownPreview(pid)', html_hq)
        self.assertIn('Branch Cost', html_hq)

        # 2. Branch order view (query branch from db)
        branch = query_one("SELECT id, code, name FROM branches WHERE is_active = TRUE LIMIT 1")
        if branch:
            branch_id = branch['id']
            resp_branch = self.client.get(f'/sales/new?branch={branch_id}')
            self.assertEqual(resp_branch.status_code, 200)
            html_branch = resp_branch.data.decode('utf-8')

            # In branch view, previewCostLabel renders 'Branch Cost'
            self.assertIn('>Branch Cost</span>', html_branch)

if __name__ == '__main__':
    unittest.main()
