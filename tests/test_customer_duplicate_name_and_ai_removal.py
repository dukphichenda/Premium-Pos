import unittest
from app import app
from database import query_one, execute, check_duplicate_customer_name

class TestCustomerDuplicateNameAndAiRemoval(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            sess['username'] = 'admin'

        # Ensure a test customer with English name exists
        self.eng_cust = query_one("SELECT id, name FROM customers WHERE name = 'Xiao Long' AND is_active = TRUE LIMIT 1")
        if not self.eng_cust:
            execute("INSERT INTO customers (name, phone, is_active) VALUES ('Xiao Long', '012345678', TRUE)")
            self.eng_cust = query_one("SELECT id, name FROM customers WHERE name = 'Xiao Long' AND is_active = TRUE LIMIT 1")

        # Ensure a test customer with Khmer name exists
        self.kh_name = "តេស្ត អតិថិជន ខ្មែរ"
        self.kh_cust = query_one("SELECT id, name FROM customers WHERE name = %s AND is_active = TRUE LIMIT 1", (self.kh_name,))
        if not self.kh_cust:
            execute("INSERT INTO customers (name, phone, is_active) VALUES (%s, '098765432', TRUE)", (self.kh_name,))
            self.kh_cust = query_one("SELECT id, name FROM customers WHERE name = %s AND is_active = TRUE LIMIT 1", (self.kh_name,))

    def tearDown(self):
        # Clean up any transient test customers
        execute("DELETE FROM customers WHERE name IN ('Unique Test Customer 8888', 'តេស្ត អតិថិជន ខ្មែរ')")

    def test_check_duplicate_customer_name_english(self):
        """Test English duplicate detection (case-insensitive, trims, collapsed spaces)"""
        # Exact match
        dup1 = check_duplicate_customer_name('Xiao Long')
        self.assertIsNotNone(dup1)
        self.assertEqual(dup1['name'], 'Xiao Long')

        # Lowercase
        dup2 = check_duplicate_customer_name('xiao long')
        self.assertIsNotNone(dup2)
        self.assertEqual(dup2['id'], dup1['id'])

        # Extra whitespace
        dup3 = check_duplicate_customer_name('   Xiao    Long   ')
        self.assertIsNotNone(dup3)
        self.assertEqual(dup3['id'], dup1['id'])

        # Exclude self id
        dup4 = check_duplicate_customer_name('Xiao Long', exclude_id=dup1['id'])
        self.assertIsNone(dup4)

    def test_check_duplicate_customer_name_khmer(self):
        """Test Khmer duplicate detection (exact, zero-width space, spacing variance)"""
        # Exact match
        dup1 = check_duplicate_customer_name(self.kh_name)
        self.assertIsNotNone(dup1)
        self.assertEqual(dup1['name'], self.kh_name)

        # Khmer with zero-width space
        zws_name = "តេស្ត\u200b អតិថិជន\u200b ខ្មែរ"
        dup2 = check_duplicate_customer_name(zws_name)
        self.assertIsNotNone(dup2)
        self.assertEqual(dup2['id'], dup1['id'])

        # Khmer without internal spaces
        nospc_name = "តេស្តអតិថិជនខ្មែរ"
        dup3 = check_duplicate_customer_name(nospc_name)
        self.assertIsNotNone(dup3)
        self.assertEqual(dup3['id'], dup1['id'])

    def test_quick_add_customer_duplicate_rejection(self):
        """Test POST /api/customers/quick-add blocks duplicate customer names"""
        resp = self.client.post('/api/customers/quick-add', json={
            'name': 'Xiao Long',
            'phone': '011222333',
            'address': 'Phnom Penh'
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertTrue(data.get('duplicate'))
        self.assertIn('Xiao Long', data['message'])

    def test_quick_add_customer_khmer_duplicate_rejection(self):
        """Test POST /api/customers/quick-add blocks Khmer duplicate customer names"""
        resp = self.client.post('/api/customers/quick-add', json={
            'name': 'តេស្តអតិថិជនខ្មែរ',
            'phone': '011222333',
            'address': 'Phnom Penh'
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertTrue(data.get('duplicate'))

    def test_quick_add_customer_success_for_unique_name(self):
        """Test POST /api/customers/quick-add allows unique customer name"""
        unique_name = 'Unique Test Customer 8888'
        resp = self.client.post('/api/customers/quick-add', json={
            'name': unique_name,
            'phone': '099887766',
            'address': 'Tuol Kork'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['customer']['name'], unique_name)

    def test_api_check_duplicate_name_endpoint(self):
        """Test GET /api/customers/check-duplicate-name endpoint"""
        # Duplicate
        resp = self.client.get('/api/customers/check-duplicate-name?name=Xiao+Long')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['duplicate'])
        self.assertEqual(data['existing_name'], 'Xiao Long')

        # Non-duplicate
        resp2 = self.client.get('/api/customers/check-duplicate-name?name=NonExistentCust999999')
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertFalse(data2['duplicate'])

    def test_ai_scan_deleted_from_sales_detail_page(self):
        """Verify AI Scan & Auto-Fill is deleted from sales detail page"""
        so = query_one("SELECT id FROM sales_orders LIMIT 1")
        so_id = so['id'] if so else 1
        resp = self.client.get(f'/sales/{so_id}', follow_redirects=True)
        html = resp.data.decode('utf-8', errors='ignore')

        # Verify AI Scan card is removed
        self.assertNotIn('id="quickAddAiUploadCard"', html)
        self.assertNotIn('AI Scan & Auto-Fill', html)
        self.assertNotIn('id="modalAiKeyConfig"', html)

        # Verify duplicate check UI is present
        self.assertIn('id="quickAddCustDupNotice"', html)
        self.assertIn('checkQuickAddNameDuplicate', html)
        self.assertIn('findClientSideDuplicateCustomer', html)

if __name__ == '__main__':
    unittest.main()
