import subprocess
import time
import json
import urllib.request
import os
import websocket
import psycopg2

print("=== STARTING BRANCH MODE CUSTOMER STRICT INDEPENDENCE TEST ===")

# Database cleanup and check
conn = psycopg2.connect('postgresql://odoo:odoo@localhost:5432/inflow_premium')
cur = conn.cursor()
cur.execute("DELETE FROM customers WHERE name LIKE 'Tola STM Test %' OR name = 'Branch1 Dedicated Customer' OR name LIKE 'Automated Branch1 Cust%'")
conn.commit()

# Start Headless Chrome
user_data = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'chrome_test_strict_' + str(int(time.time())))
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
proc = subprocess.Popen([
    chrome_path, '--headless=new', '--remote-debugging-port=9232', '--remote-allow-origins=*',
    f'--user-data-dir={user_data}', '--no-first-run', '--no-default-browser-check'
])
time.sleep(2)
msg_id = 0

try:
    req = urllib.request.Request("http://localhost:9232/json/new?http://localhost:5050/login", method="PUT")
    tabs = json.loads(urllib.request.urlopen(req).read().decode())
    ws = websocket.create_connection(tabs['webSocketDebuggerUrl'])

    def send_cmd(method, params=None):
        global msg_id
        msg_id += 1
        ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
        while True:
            resp = json.loads(ws.recv())
            if resp.get('id') == msg_id:
                return resp

    def eval_js(expression):
        resp = send_cmd("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True
        })
        res_body = resp.get('result', {})
        if 'exceptionDetails' in res_body:
            print("JS EXCEPTION:", res_body['exceptionDetails'])
        return res_body.get('result', {}).get('value')

    send_cmd("Page.enable")
    send_cmd("Runtime.enable")
    time.sleep(1)

    # 1. Login as admin
    print("1. Logging in as admin...")
    eval_js("""
        document.querySelector('input[name="username"]').value = 'admin';
        document.querySelector('input[name="password"]').value = '123456';
        document.querySelector('form').submit();
    """)
    time.sleep(3)

    # 2. Enter Branch Mode for Branch 1 (STM)
    print("2. Entering Branch Mode STM via /branches/switch/1...")
    eval_js("window.location.href = '/branches/switch/1';")
    time.sleep(3)

    # 3. Create new order in Branch STM
    print("3. Navigating to /sales/new in Branch STM...")
    eval_js("window.location.href = '/sales/new';")
    time.sleep(4)

    # 4. Search 'tola' in customer combobox on Branch STM order
    print("4. Searching 'tola' on Branch STM order...")
    branch_search_res = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const win = ifr ? ifr.contentWindow : window;

            const custInp = doc.getElementById('customerSearchInput');
            if (custInp) custInp.value = 'tola';
            if (typeof win.filterCustomerDropdown === 'function') {
                win.filterCustomerDropdown('tola');
            }
            const allRows = Array.from(doc.querySelectorAll('#customerDropdownBody tr.main-cust-row'));
            const visibleRows = allRows.filter(r => r.style.display !== 'none');
            const hqRows = visibleRows.filter(r => (r.getAttribute('data-branch-id') || '') === '');
            const hidden = doc.getElementById('orderBranchIdInput');
            const meta = doc.getElementById('soPartialMeta');
            const sel = doc.getElementById('soBranchSelect');
            return {
                rawHiddenVal: hidden ? hidden.value : 'NO_HIDDEN',
                rawMetaVal: meta ? meta.getAttribute('data-branch-id') : 'NO_META',
                rawSelVal: sel ? sel.value : 'NO_SEL',
                activeBranchId: typeof win.getActiveOrderBranchId === 'function' ? win.getActiveOrderBranchId() : null,
                totalCustomerRows: allRows.length,
                visibleCustomerCount: visibleRows.length,
                visibleCustomers: visibleRows.map(r => r.getAttribute('data-cname')),
                hqCustomersLeakedCount: hqRows.length
            };
        })()
    """)
    print("Branch STM Search Result:", json.dumps(branch_search_res, indent=2))
    assert branch_search_res['activeBranchId'] == '1', f"Expected activeBranchId '1', got {branch_search_res['activeBranchId']}"
    assert branch_search_res['hqCustomersLeakedCount'] == 0, f"HQ customers leaked into Branch STM: {branch_search_res['hqCustomersLeakedCount']}"
    assert branch_search_res['visibleCustomerCount'] == 0, f"Expected 0 tola customers on fresh branch, got {branch_search_res['visibleCustomerCount']}"

    # 5. Quick-add a new customer while in Branch STM
    unique_cust_name = "Tola STM Test " + str(int(time.time()))
    print(f"5. Quick-adding branch customer '{unique_cust_name}'...")
    add_res = eval_js(f"""
        (() => {{
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const win = ifr ? ifr.contentWindow : window;

            win.openQuickAddCustomerModal('{unique_cust_name}');
            const nameIn = doc.getElementById('quickAddCustNameInput');
            const phoneIn = doc.getElementById('quickAddCustPhoneInput');
            if (nameIn) nameIn.value = '{unique_cust_name}';
            if (phoneIn) phoneIn.value = '012999888';
            win.submitQuickAddCustomerAjax();
            return {{
                submittingForBranch: win.getActiveOrderBranchId(),
                name: '{unique_cust_name}'
            }};
        }})()
    """)
    print("Quick Add Submitted:", add_res)
    time.sleep(3)

    # 6. Verify in DB that the new customer has branch_id = 1
    cur.execute("SELECT id, name, branch_id FROM customers WHERE name = %s", (unique_cust_name,))
    db_cust = cur.fetchone()
    print("Customer in DB:", db_cust)
    assert db_cust is not None, "Customer was not saved in DB!"
    assert db_cust[2] == 1, f"Customer branch_id was {db_cust[2]}, expected 1!"

    # 7. Search 'tola' again in Branch STM: ONLY this customer should appear
    print("7. Searching 'tola' again in Branch STM...")
    branch_search_res2 = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const win = ifr ? ifr.contentWindow : window;

            const custInp = doc.getElementById('customerSearchInput');
            if (custInp) custInp.value = 'tola';
            if (typeof win.filterCustomerDropdown === 'function') {
                win.filterCustomerDropdown('tola');
            }
            const allRows = Array.from(doc.querySelectorAll('#customerDropdownBody tr.main-cust-row'));
            const visibleRows = allRows.filter(r => r.style.display !== 'none');
            return {
                visibleCustomerCount: visibleRows.length,
                visibleCustomers: visibleRows.map(r => ({
                    name: r.getAttribute('data-cname'),
                    branchId: r.getAttribute('data-branch-id')
                }))
            };
        })()
    """)
    print("Branch STM Search Result 2:", json.dumps(branch_search_res2, indent=2))
    assert branch_search_res2['visibleCustomerCount'] == 1, f"Expected exactly 1 branch customer, got {branch_search_res2['visibleCustomerCount']}"
    assert branch_search_res2['visibleCustomers'][0]['name'] == unique_cust_name, "Wrong customer displayed!"
    assert branch_search_res2['visibleCustomers'][0]['branchId'] == '1', "Customer branchId in DOM is not 1!"

    # 8. Return to Main Store (HQ)
    print("8. Returning to Main Store (HQ) via /branches/switch/0...")
    eval_js("window.location.href = '/branches/switch/0';")
    time.sleep(3)

    # 9. Open /sales/new in Main Store (HQ)
    print("9. Navigating to /sales/new in Main Store (HQ)...")
    eval_js("window.location.href = '/sales/new';")
    time.sleep(4)

    # 10. Search 'tola' in customer combobox on Main Store (HQ) order
    print("10. Searching 'tola' on Main Store (HQ) order...")
    hq_search_res = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const win = ifr ? ifr.contentWindow : window;

            const custInp = doc.getElementById('customerSearchInput');
            if (custInp) custInp.value = 'tola';
            if (typeof win.filterCustomerDropdown === 'function') {
                win.filterCustomerDropdown('tola');
            }
            const allRows = Array.from(doc.querySelectorAll('#customerDropdownBody tr.main-cust-row'));
            const visibleRows = allRows.filter(r => r.style.display !== 'none');
            const branchRows = visibleRows.filter(r => (r.getAttribute('data-branch-id') || '') !== '');
            return {
                activeBranchId: typeof win.getActiveOrderBranchId === 'function' ? win.getActiveOrderBranchId() : null,
                totalCustomerRows: allRows.length,
                visibleCustomerCount: visibleRows.length,
                visibleCustomers: visibleRows.map(r => r.getAttribute('data-cname')),
                branchCustomersLeakedCount: branchRows.length
            };
        })()
    """)
    print("HQ Search Result:", json.dumps(hq_search_res, indent=2))
    assert hq_search_res['activeBranchId'] == '', f"Expected activeBranchId '', got {hq_search_res['activeBranchId']}"
    assert hq_search_res['branchCustomersLeakedCount'] == 0, f"Branch customers leaked into HQ: {hq_search_res['branchCustomersLeakedCount']}"
    assert unique_cust_name not in hq_search_res['visibleCustomers'], f"Branch customer {unique_cust_name} found in HQ!"
    assert hq_search_res['visibleCustomerCount'] >= 6, f"Expected at least 6 HQ tola customers, got {hq_search_res['visibleCustomerCount']}"

    # 11. Clean up test customer
    cur.execute("DELETE FROM customers WHERE name = %s", (unique_cust_name,))
    conn.commit()
    print("11. Cleaned up test customer.")

    print("\n[SUCCESS] STRICT HQ VS BRANCH CUSTOMER INDEPENDENCE VERIFIED 100%!")

finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    proc.wait()
    conn.close()
