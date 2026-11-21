import unittest
import os
import re
import shutil
import subprocess

class TestJsSyntaxIntegrity(unittest.TestCase):
    def test_sales_detail_template_no_duplicate_lastSearchBranch(self):
        """Verify templates/sales/detail.html does not declare lastSearchBranch multiple times with let"""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        tpl_path = os.path.join(base_dir, 'templates', 'sales', 'detail.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            content = f.read()

        matches = re.findall(r'\blet\s+lastSearchBranch\b', content)
        self.assertEqual(len(matches), 1, f"Found {len(matches)} declarations of 'let lastSearchBranch' in detail.html (must be exactly 1)")

    def test_sales_detail_page_has_no_js_syntax_errors(self):
        """Render /sales/new and verify all <script> blocks pass Node syntax check if node is available"""
        node_bin = shutil.which('node')
        if not node_bin:
            self.skipTest("Node.js is not installed on this system")

        from app import app
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

        res = client.get('/sales/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        for i, js in enumerate(scripts):
            if not js.strip() or js.strip().startswith('{'):
                continue
            tmp_path = f"test_tmp_script_{i}.js"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(js)
            try:
                proc = subprocess.run([node_bin, '-c', tmp_path], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"Script tag {i} failed syntax check: {proc.stderr[:400]}")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

if __name__ == '__main__':
    unittest.main()
