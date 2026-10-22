import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
import json
from app import create_app

class TestPosRedesignFavorites(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_branch_pos_color_scheme_stm(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'admin'
        res = self.client.get('/branches/1/pos')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8', errors='ignore')
        # Check dynamic branch primary color for STM (#10B981)
        self.assertIn('--pos-primary: #10B981', html)
        # Check View By Tab bar elements
        self.assertIn('pos-viewby-bar', html)
        self.assertIn('viewTab-all', html)
        self.assertIn('viewTab-frequent', html)
        self.assertIn('viewTab-favorite', html)
        # Check Star button on product cards
        self.assertIn('starBtn-', html)

    def test_branch_pos_color_scheme_sk(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'admin'
        res = self.client.get('/branches/2/pos')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8', errors='ignore')
        # Check dynamic branch primary color for SK (#EC4899)
        self.assertIn('--pos-primary: #EC4899', html)

    def test_toggle_favorite_endpoint(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'chenda'
            sess['role'] = 'admin'
        
        # Explicit toggle on
        res1 = self.client.post('/branches/1/pos/toggle_favorite',
                                data=json.dumps({'product_id': 99999, 'is_favorite': True}),
                                content_type='application/json')
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1.get('success'))
        self.assertTrue(data1.get('is_favorite'))
        self.assertIn(99999, data1.get('favorite_product_ids', []))

        # Explicit toggle off
        res2 = self.client.post('/branches/1/pos/toggle_favorite',
                                data=json.dumps({'product_id': 99999, 'is_favorite': False}),
                                content_type='application/json')
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2.get('success'))
        self.assertFalse(data2.get('is_favorite'))
        self.assertNotIn(99999, data2.get('favorite_product_ids', []))

if __name__ == '__main__':
    unittest.main()
