import unittest
import os

class TestPOSummaryReport(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.routes_path = os.path.join(self.base_dir, 'routes', 'reports.py')
        self.viewer_path = os.path.join(self.base_dir, 'templates', 'reports', 'viewer.html')

        with open(self.routes_path, 'r', encoding='utf-8') as f:
            self.routes_content = f.read()
        with open(self.viewer_path, 'r', encoding='utf-8') as f:
            self.viewer_content = f.read()

    def test_po_summary_queries_vendor_name_and_totals(self):
        """Verify purchase-order-summary selects vendor_name and includes total_amount in totals"""
        self.assertIn("COALESCE(v.name, 'N/A') as vendor_name", self.routes_content)
        self.assertIn("'total_amount': float(t['total_po'] or 0)", self.routes_content)
        self.assertIn("selected_vendor_name", self.routes_content)

    def test_viewer_renders_vendor_name_header_and_cell(self):
        """Verify viewer.html displays VENDOR NAME in header and r.vendor_name in table cell"""
        self.assertIn("VENDOR NAME", self.viewer_content)
        self.assertIn("r.vendor_name", self.viewer_content)

    def test_viewer_renders_total_of_all_po_amount_in_tfoot(self):
        """Verify viewer.html renders Total of All PO Amount at the bottom in tfoot"""
        self.assertIn("Total of All PO Amount", self.viewer_content)
        self.assertIn("<tfoot>", self.viewer_content)

    def test_po_summary_csv_export_includes_total_row(self):
        """Verify purchase-order-summary export includes Total of All PO Amount row"""
        self.assertIn("writer.writerow(['Total of All PO Amount',", self.routes_content)

if __name__ == '__main__':
    unittest.main()
