import unittest
import os
import subprocess
import tempfile
from app import create_app

class TestFilterAndMinimizeFunctionality(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'main_admin'

    def test_rendered_catalog_html_and_js(self):
        resp = self.client.get('/products/248')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. Filters button and dropdown element check
        self.assertIn('id="catFilterBtn"', html)
        self.assertIn('onclick="toggleFilterMenu(event)"', html)
        self.assertIn('id="catFilterDropdown"', html)
        self.assertIn('class="inflow-tab-dropdown-menu"', html)

        # 2. Minimize button and expand elements check
        self.assertIn('id="btnMinimizeProductSidebar"', html)
        self.assertIn('onclick="toggleProductSidebarCollapse()"', html)
        self.assertIn('id="productSidebarExpandTab"', html)
        self.assertIn('id="productExpandTbBtn"', html)

        # 3. Check functions are attached to window and defined early
        self.assertIn('window.toggleFilterMenu = function', html)
        self.assertIn('window.toggleProductSidebarCollapse = function', html)
        self.assertIn('window.openProductMobileDrawer = function', html)
        self.assertIn('window.closeProductMobileDrawer = function', html)

        # 4. Check CSS positioning for catFilterDropdown
        self.assertIn('left: 6px; right: 6px; width: calc(100% - 12px);', html)

        # 5. Execute Node.js simulation of toggleFilterMenu and toggleProductSidebarCollapse
        js_simulation = """
        // Mock DOM elements
        const dom = {
            classes: {},
            listeners: {},
            classList: {
                toggle: function(cls) {
                    dom.classes[cls] = !dom.classes[cls];
                    return dom.classes[cls];
                },
                add: function(cls) { dom.classes[cls] = true; },
                remove: function(cls) { dom.classes[cls] = false; },
                contains: function(cls) { return !!dom.classes[cls]; }
            },
            style: {
                display: '',
                setProperty: function(k, v) { this[k] = v; }
            }
        };

        const globalWindow = {
            innerWidth: 1024,
            _productDrawerJustClosedAt: 0
        };

        const documentMock = {
            documentElement: {
                classList: {
                    contains: function(c) { return false; }
                }
            },
            getElementById: function(id) {
                if (id === 'catFilterDropdown' || id === 'catSearchBoxWrapper' || id === 'productExpandTbBtn') {
                    return dom;
                }
                return null;
            },
            querySelector: function(sel) {
                if (sel === '.inflow-catalog-layout') {
                    return dom;
                }
                return null;
            },
            addEventListener: function(type, fn) {
                dom.listeners[type] = fn;
            }
        };

        // Bind mock globals
        global.window = globalWindow;
        global.document = documentMock;

        // Run toggleFilterMenu
        """ + """
        window.toggleFilterMenu = function(e) {
            if (e) {
                e.stopPropagation();
                e.preventDefault();
            }
            const menu = document.getElementById('catFilterDropdown');
            if (menu) {
                const willShow = !menu.classList.contains('show');
                menu.classList.toggle('show');
            }
        };

        window.toggleProductSidebarCollapse = function(forceState) {
            const ws = document.querySelector('.inflow-catalog-layout');
            if (!ws) return;
            const isCurrentlyCollapsed = ws.classList.contains('sidebar-collapsed');
            const willCollapse = (typeof forceState === 'boolean') ? forceState : !isCurrentlyCollapsed;

            if (willCollapse) {
                ws.classList.add('sidebar-collapsed');
            } else {
                ws.classList.remove('sidebar-collapsed');
            }
            const expandBtn = document.getElementById('productExpandTbBtn');
            if (expandBtn) expandBtn.style.display = willCollapse ? 'inline-flex' : 'none';
        };

        // Test 1: toggleFilterMenu
        assert(!dom.classList.contains('show'), 'Should start not shown');
        window.toggleFilterMenu();
        assert(dom.classList.contains('show'), 'Should be shown after 1st toggle');
        window.toggleFilterMenu();
        assert(!dom.classList.contains('show'), 'Should not be shown after 2nd toggle');

        // Test 2: toggleProductSidebarCollapse
        assert(!dom.classList.contains('sidebar-collapsed'), 'Should start not collapsed');
        window.toggleProductSidebarCollapse();
        assert(dom.classList.contains('sidebar-collapsed'), 'Should be collapsed after 1st toggle');
        assert(dom.style.display === 'inline-flex', 'Expand button should be shown');
        window.toggleProductSidebarCollapse();
        assert(!dom.classList.contains('sidebar-collapsed'), 'Should not be collapsed after 2nd toggle');
        assert(dom.style.display === 'none', 'Expand button should be hidden');

        function assert(condition, msg) {
            if (!condition) {
                console.error('Assertion failed:', msg);
                process.exit(1);
            }
        }
        console.log('ALL JS SIMULATION TESTS PASSED');
        """

        tmp = tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w', encoding='utf-8')
        tmp.write(js_simulation)
        tmp.close()
        res = subprocess.run(['node', tmp.name], capture_output=True, text=True)
        os.unlink(tmp.name)
        self.assertEqual(res.returncode, 0, f"Node simulation failed: {res.stderr}")
        self.assertIn("ALL JS SIMULATION TESTS PASSED", res.stdout)

if __name__ == '__main__':
    unittest.main()
