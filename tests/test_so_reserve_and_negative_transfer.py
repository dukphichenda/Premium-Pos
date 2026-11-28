import json
import os
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _ensure_psycopg2_stub():
    """Install lightweight psycopg2 stub only if psycopg2 is absent in the local test runtime."""
    try:
        import psycopg2  # noqa: F401
        return
    except ImportError:
        pass

    pg = types.ModuleType('psycopg2')
    pg.OperationalError = type('OperationalError', (Exception,), {})
    pg.Error = type('Error', (Exception,), {})
    pg.connect = lambda *a, **kw: None

    extras = types.ModuleType('psycopg2.extras')
    extras.RealDictCursor = object
    pg.extras = extras

    pool = types.ModuleType('psycopg2.pool')
    pool.ThreadedConnectionPool = object
    pg.pool = pool

    sys.modules['psycopg2'] = pg
    sys.modules['psycopg2.extras'] = extras
    sys.modules['psycopg2.pool'] = pool


_ensure_psycopg2_stub()

from flask import Flask
from routes.sales_orders import _apply_order_backorder_flags, _order_holds_stock_reservation
from routes.inventory import inventory_bp
from routes.mobile_api import mobile_api_bp


class FakeTransferCursor:
    """In-memory cursor simulating stock_transfers, stock_transfer_lines, inventory, and inventory_logs."""

    def __init__(self, initial_inventory):
        # dict[(pid, loc_id)] -> {'id': int, 'quantity': float, 'reserved_quantity': float}
        self.inventory = {k: dict(v) for k, v in initial_inventory.items()}
        self.next_inv_id = 500
        self.transfers = {}
        self.transfer_lines = {}
        self.logs = []
        self._last = None
        self._many = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split())
        params = params or ()
        self._last = None
        self._many = []

        if s.startswith('SELECT status FROM stock_transfers WHERE id = %s'):
            row = self.transfers.get(params[0])
            self._last = {'status': row['status']} if row else None
        elif s.startswith('SELECT COALESCE(quantity, 0) as qty, COALESCE(reserved_quantity, 0) as reserved FROM inventory'):
            row = self.inventory.get((params[0], params[1]))
            self._last = {'qty': row['quantity'], 'reserved': row['reserved_quantity']} if row else None
        elif s.startswith('SELECT sku, name FROM products WHERE id = %s'):
            self._last = {'sku': f'SKU-{params[0]}', 'name': f'Product {params[0]}'}
        elif s.startswith('UPDATE stock_transfers SET'):
            trf_id = params[-1]
            self.transfers[trf_id] = {
                'id': trf_id,
                'transfer_number': params[0],
                'from_location_id': params[1],
                'to_location_id': params[2],
                'status': params[3],
                'transfer_date': params[4],
                'notes': params[5],
            }
            self._last = {'id': trf_id}
        elif s.startswith('INSERT INTO stock_transfers'):
            trf_id = len(self.transfers) + 1
            self.transfers[trf_id] = {
                'id': trf_id,
                'transfer_number': params[0],
                'from_location_id': params[1],
                'to_location_id': params[2],
                'status': params[3],
                'transfer_date': params[4],
                'notes': params[5],
            }
            self._last = {'id': trf_id}
        elif s.startswith('DELETE FROM stock_transfer_lines WHERE transfer_id = %s'):
            self.transfer_lines[params[0]] = []
        elif s.startswith('INSERT INTO stock_transfer_lines'):
            self.transfer_lines.setdefault(params[0], []).append(params[1:])
        elif s.startswith('SELECT id, COALESCE(quantity, 0) as qty FROM inventory WHERE product_id = %s AND location_id = %s'):
            row = self.inventory.get((params[0], params[1]))
            self._last = {'id': row['id'], 'qty': row['quantity']} if row else None
        elif s.startswith('UPDATE inventory SET quantity = quantity - %s'):
            delta, inv_id = float(params[0]), params[1]
            for k, v in self.inventory.items():
                if v['id'] == inv_id:
                    v['quantity'] -= delta
                    break
        elif s.startswith('INSERT INTO inventory (product_id, location_id, sublocation, quantity) VALUES (%s, %s, \'\', -%s)'):
            pid, loc_id, delta = params[0], params[1], float(params[2])
            self.next_inv_id += 1
            self.inventory[(pid, loc_id)] = {'id': self.next_inv_id, 'quantity': -delta, 'reserved_quantity': 0.0}
        elif s.startswith('INSERT INTO inventory (product_id, location_id, sublocation, quantity) VALUES (%s, %s, \'\', %s) ON CONFLICT'):
            pid, loc_id, delta = params[0], params[1], float(params[2])
            if (pid, loc_id) in self.inventory:
                self.inventory[(pid, loc_id)]['quantity'] += delta
            else:
                self.next_inv_id += 1
                self.inventory[(pid, loc_id)] = {'id': self.next_inv_id, 'quantity': delta, 'reserved_quantity': 0.0}
        elif s.startswith('INSERT INTO inventory_logs'):
            self.logs.append(params)

    def fetchone(self):
        return self._last

    def fetchall(self):
        return self._many


class SalesOrderReservationAndTransferTest(unittest.TestCase):
    def test_open_so_excludes_own_kit_reservation(self):
        """Reproduces SO-023311: 400 pcs of N3500G-CN in Open bill must include its own 400 reserved."""
        components_map = {
            999: [
                {
                    'component_id': 101,
                    'sku': 'N3500G-Nolid',
                    'name': 'Body',
                    'uom': 'pcs.',
                    'quantity': 1.0,
                    'stock_on_hand': 900.0,
                    'stock_reserved': 700.0,
                    'stock_available': 200.0,
                    'is_bom': True,
                },
                {
                    'component_id': 102,
                    'sku': 'Lid330-CN',
                    'name': 'Lid',
                    'uom': 'pcs.',
                    'quantity': 1.0,
                    'stock_on_hand': 500.0,
                    'stock_reserved': 400.0,
                    'stock_available': 100.0,
                    'is_bom': True,
                },
            ]
        }

        open_order = {'id': 23311, 'status': 'OPEN', 'payment_status': 'UNPAID'}
        self.assertTrue(_order_holds_stock_reservation(open_order))

        lines = [{'product_id': 999, 'quantity': 400.0, 'stock_on_hand': 0.0}]
        holds_res, saved_reserves = _apply_order_backorder_flags(lines, components_map, order=open_order)

        self.assertTrue(holds_res)
        self.assertEqual(saved_reserves, {'999': 400.0, '101': 400.0, '102': 400.0})
        self.assertFalse(lines[0]['is_backordered'])
        self.assertEqual(lines[0]['max_kits_buildable'], 500)
        self.assertEqual(lines[0]['components'][0]['stock_reserved'], 300.0)
        self.assertEqual(lines[0]['components'][0]['stock_available'], 600.0)
        self.assertEqual(lines[0]['components'][1]['stock_reserved'], 0.0)
        self.assertEqual(lines[0]['components'][1]['stock_available'], 500.0)

        # Shared components_map must NOT be mutated
        self.assertEqual(components_map[999][0]['stock_reserved'], 700.0)
        self.assertEqual(components_map[999][1]['stock_reserved'], 400.0)

        # When order qty exceeds adjusted buildable (600 > 500), backorder flag must trigger
        over_lines = [{'product_id': 999, 'quantity': 600.0, 'stock_on_hand': 0.0}]
        _apply_order_backorder_flags(over_lines, components_map, order=open_order)
        # Note: with 600 saved reserved on Lid330-CN (only 400 in DB), reserved clamps to 0 -> avail=500 < 600
        self.assertTrue(over_lines[0]['is_backordered'])
        self.assertEqual(over_lines[0]['max_kits_buildable'], 500)

        # Paid / New order does NOT hold reservations, so raw 100 buildable < 400 still flags backorder
        paid_order = {'id': 23311, 'status': 'PAID', 'payment_status': 'PAID'}
        paid_lines = [{'product_id': 999, 'quantity': 400.0, 'stock_on_hand': 0.0}]
        holds_paid, paid_reserves = _apply_order_backorder_flags(paid_lines, components_map, order=paid_order)
        self.assertFalse(holds_paid)
        self.assertEqual(paid_reserves, {})
        self.assertTrue(paid_lines[0]['is_backordered'])
        self.assertEqual(paid_lines[0]['max_kits_buildable'], 100)

    def test_web_transfer_complete_allowed_with_negative_source_stock(self):
        """Reproduces TRF-00003: insufficient/negative source stock warns but completes transfer cleanly."""
        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(inventory_bp)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'admin'

        fake_cur = FakeTransferCursor({
            (10, 1): {'id': 1, 'quantity': -215500.0, 'reserved_quantity': 1200.0},
            (10, 2): {'id': 2, 'quantity': 50.0, 'reserved_quantity': 0.0},
            # Product 11 has NO inventory row at source location 1 yet
        })

        @contextmanager
        def mock_cursor(commit=False):
            yield fake_cur

        payload = {
            'transfer_number': 'TRF-00003',
            'from_location_id': 1,
            'to_location_id': 2,
            'transfer_date': '2026-11-28',
            'notes': 'Allow negative source completion',
            'status': 'COMPLETED',
            'lines': [
                {'product_id': 10, 'quantity': 600, 'uom': 'pcs.', 'uom_factor': 1.0, 'source_on_hand': -215500, 'source_available': -216700},
                {'product_id': 11, 'quantity': 25, 'uom': 'pcs.', 'uom_factor': 1.0, 'source_on_hand': 0, 'source_available': 0},
            ],
        }

        with patch('routes.inventory.get_db_cursor', mock_cursor):
            res = client.post('/inventory/transfers/save', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['status'], 'COMPLETED')
        self.assertEqual(len(body['warnings']), 2)
        self.assertEqual(fake_cur.inventory[(10, 1)]['quantity'], -216100.0)
        self.assertEqual(fake_cur.inventory[(10, 2)]['quantity'], 650.0)
        self.assertEqual(fake_cur.inventory[(11, 1)]['quantity'], -25.0)
        self.assertEqual(fake_cur.inventory[(11, 2)]['quantity'], 25.0)
        self.assertEqual(len(fake_cur.logs), 2)

    def test_mobile_transfer_complete_allowed_with_negative_source_stock(self):
        """Verifies mobile /api/mobile/transfers/save also allows completion when source stock is negative."""
        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(mobile_api_bp)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'

        fake_cur = FakeTransferCursor({
            (10, 1): {'id': 1, 'quantity': -100.0, 'reserved_quantity': 20.0},
        })

        @contextmanager
        def mock_cursor(commit=False):
            yield fake_cur

        payload = {
            'transfer_number': 'TRF-MOB-1',
            'from_location_id': 1,
            'to_location_id': 2,
            'transfer_date': '2026-11-28',
            'notes': 'Mobile negative source',
            'status': 'COMPLETED',
            'lines': [{'product_id': 10, 'quantity': 50, 'uom': 'pcs.', 'uom_factor': 1.0}],
        }

        with patch('routes.mobile_api.get_db_cursor', mock_cursor):
            res = client.post('/api/mobile/transfers/save', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['status'], 'COMPLETED')
        self.assertEqual(len(body['warnings']), 1)
        self.assertEqual(fake_cur.inventory[(10, 1)]['quantity'], -150.0)
        self.assertEqual(fake_cur.inventory[(10, 2)]['quantity'], 50.0)

    def test_js_effective_reserved_calculation_for_open_order(self):
        """Runs the exact JS helpers from detail.html via Node against SO-023311 & multi-line cases."""
        import shutil
        import subprocess
        node_bin = shutil.which('node')
        if not node_bin:
            self.skipTest('node not available')

        detail_path = os.path.join(ROOT_DIR, 'templates', 'sales', 'detail.html')
        with open(detail_path, 'r', encoding='utf-8') as f:
            html = f.read()

        start_idx = html.index('function getSavedOrderReservesMap()')
        end_idx = html.index('function refreshAllRowBackorderBadges()')
        # Grab through end of refreshAllRowBackorderBadges()
        close_idx = html.index('}', html.index('{', end_idx)) + 1
        js_code = html[start_idx:close_idx]

        harness = f"""
        const vm = require('vm');
        let metaAttrs = {{
            'data-holds-res': '1',
            'data-saved-order-reserves': JSON.stringify({{"999": 400, "101": 400, "102": 400}})
        }};
        let row1 = {{
            querySelector: (sel) => sel === '.line-qty' ? {{ value: '400' }} : sel === '.line-uom' ? {{ value: 'pcs.' }} : sel === 'input[name*="[product_id]"]' ? {{ value: '999' }} : null,
            getAttribute: (a) => a === 'data-product-id' ? '999' : null,
        }};
        let row2 = null;
        const document = {{
            getElementById: (id) => id === 'soPartialMeta' ? {{ getAttribute: (k) => metaAttrs[k] }} : null,
            querySelectorAll: (sel) => row2 ? [row1, row2] : [row1],
        }};
        const window = {{
            productsCatalog: {{
                999: {{
                    base_uom: 'pcs.', sales_uom: '', sales_ratio: 1, purchasing_uom: '', purchasing_ratio: 1,
                    components: [
                        {{ component_id: 101, quantity: 1, stock_on_hand: 900, stock_reserved: 700, is_bom: true }},
                        {{ component_id: 102, quantity: 1, stock_on_hand: 500, stock_reserved: 400, is_bom: true }}
                    ]
                }}
            }}
        }};
        vm.runInNewContext({json.dumps(js_code)} + `;
            const assert = require('assert');
            // Single row 400: other orders hold 300 on comp 101 and 0 on comp 102
            assert.strictEqual(getEffectiveReservedForRow(101, 700, row1), 300);
            assert.strictEqual(getEffectiveReservedForRow(102, 400, row1), 0);
            // Adding a second unsaved row of 250 on the same order keeps row1 demand (400) reserved for row2 check
            setRow2({{
                querySelector: (sel) => sel === '.line-qty' ? {{ value: '250' }} : sel === '.line-uom' ? {{ value: 'pcs.' }} : sel === 'input[name*="[product_id]"]' ? {{ value: '999' }} : null,
                getAttribute: (a) => a === 'data-product-id' ? '999' : null,
            }});
            const row2 = getRow2();
            assert.strictEqual(getEffectiveReservedForRow(101, 700, row2), 700);
            assert.strictEqual(getEffectiveReservedForRow(102, 400, row2), 400);
            // And row1 now sees row2's 250 unsaved demand
            assert.strictEqual(getEffectiveReservedForRow(101, 700, row1), 550);
            assert.strictEqual(getEffectiveReservedForRow(102, 400, row1), 250);
            console.log('JS_HARNESS_OK');
        `, {{ document, window, require, console, row1, setRow2: (r) => {{ row2 = r; }}, getRow2: () => row2 }});
        """
        proc = subprocess.run([node_bin], input=harness, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Node harness failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
        self.assertIn('JS_HARNESS_OK', proc.stdout)

        # Ensure helper functions are declared at top-level (not nested inside selectUnitForLine/if blocks)
        scope_check = """
        const fs = require('fs');
        const html = fs.readFileSync(process.argv[1], 'utf8');
        const scriptBlock = html.slice(html.indexOf('function openQtyDropdown('), html.indexOf('function initBackorderNotices()'));
        let depth = 0;
        const lines = scriptBlock.split(/\\r?\\n/);
        const found = {};
        const targets = [
            'function openQtyDropdown(',
            'function selectUnitForLine(',
            'function getSavedOrderReservesMap(',
            'function getRowStdQty(',
            'function getEffectiveReservedForRow(',
            'function refreshRowBackorderBadge(',
            'function refreshAllRowBackorderBadges(',
            'function onQtyNumberChange(',
            'function showBackorderNotice('
        ];
        for (const line of lines) {
            const trimmed = line.trim();
            for (const t of targets) {
                if (trimmed.startsWith(t)) found[t] = depth;
            }
            const clean = line.replace(/'(?:\\\\.|[^'\\\\])*'|"(?:\\\\.|[^"\\\\])*"|`(?:\\\\.|[^`\\\\])*`/g, '').replace(/\\/\\/.*$/, '');
            for (const ch of clean) {
                if (ch === '{') depth++;
                else if (ch === '}') depth--;
            }
        }
        for (const t of targets) {
            if (found[t] !== 0) {
                console.error('Bad top-level depth for', t, 'got:', found[t]);
                process.exit(1);
            }
        }
        console.log('TOP_LEVEL_SCOPE_OK');
        """
        scope_proc = subprocess.run([node_bin, '-e', scope_check, detail_path], capture_output=True, text=True)
        self.assertEqual(scope_proc.returncode, 0, f"Top-level scope check failed:\nSTDOUT:{scope_proc.stdout}\nSTDERR:{scope_proc.stderr}")
        self.assertIn('TOP_LEVEL_SCOPE_OK', scope_proc.stdout)

    def test_canvas_saved_order_reserves_attribute_is_properly_escaped(self):
        """Ensures data-saved-order-reserves uses |tojson|forceescape so double quotes do not break HTML."""
        import html as html_mod
        import re
        from flask import render_template_string

        canvas_path = os.path.join(ROOT_DIR, 'templates', 'sales', '_detail_canvas.html')
        with open(canvas_path, 'r', encoding='utf-8') as f:
            canvas_tpl = f.read()

        self.assertNotIn('|tojson|e', canvas_tpl)
        self.assertIn('data-saved-order-reserves="{{ (saved_order_reserves or {})|tojson|forceescape }}"', canvas_tpl)

        app = Flask(__name__)
        with app.app_context():
            rendered = render_template_string(
                '<div id="soPartialMeta" data-holds-res="1" data-saved-order-reserves="{{ (saved_order_reserves or {})|tojson|forceescape }}"></div>',
                saved_order_reserves={'301': 400.0, '492': 400.0, '577': 400.0},
            )
        m = re.search(r'data-saved-order-reserves="([^"]+)"', rendered)
        self.assertIsNotNone(m, f"Attribute broken in rendered HTML: {rendered}")
        parsed = json.loads(html_mod.unescape(m.group(1)))
        self.assertEqual(parsed, {'301': 400.0, '492': 400.0, '577': 400.0})


if __name__ == '__main__':
    unittest.main()
