import subprocess
import time
import json
import urllib.request
import os
import websocket
import psycopg2

print("=== STARTING HQ VS BRANCH CUSTOMER INDEPENDENCE & DATEPICKER TEST ===")

# Database setup: ensure we have at least one customer assigned to Branch 1 for testing
conn = psycopg2.connect('postgresql://odoo:odoo@localhost:5432/inflow_premium')
cur = conn.cursor()

# Get Branch 1 ID
cur.execute("SELECT id, name, code FROM branches ORDER BY id ASC LIMIT 1")
branch_row = cur.fetchone()
branch_1_id = branch_row[0] if branch_row else 1
print(f"Testing with Branch: ID={branch_1_id}, Name={branch_row[1] if branch_row else 'STM'}")

# Ensure we have a branch-specific customer for Branch 1
cur.execute("SELECT id, name FROM customers WHERE branch_id = %s LIMIT 1", (branch_1_id,))
branch_cust = cur.fetchone()
if not branch_cust:
    cur.execute("""
        INSERT INTO customers (name, contact_name, phone, branch_id, is_active)
        VALUES ('Branch1 Dedicated Customer', 'Tola Branch1 Contact', '099111222', %s, TRUE)
        RETURNING id, name
    """, (branch_1_id,))
    branch_cust = cur.fetchone()
    conn.commit()
    print("Created Branch 1 customer:", branch_cust)
else:
    print("Found existing Branch 1 customer:", branch_cust)

# Get an existing saved order
cur.execute("SELECT id, order_number, branch_id, order_date FROM sales_orders ORDER BY id DESC LIMIT 1")
test_order = cur.fetchone()
order_id = test_order[0]
print(f"Target Saved Order: ID={order_id}, Num={test_order[1]}, Date={test_order[3]}")
conn.close()

# Start Headless Chrome
user_data = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'chrome_test_prof_' + str(int(time.time())))
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
proc = subprocess.Popen([
    chrome_path, '--headless=new', '--remote-debugging-port=9229', '--remote-allow-origins=*',
    f'--user-data-dir={user_data}', '--no-first-run', '--no-default-browser-check'
])
time.sleep(2)
msg_id = 0

try:
    req = urllib.request.Request("http://localhost:9229/json/new?http://localhost:5050/login", method="PUT")
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

    # Login
    eval_js("""
        document.querySelector('input[name="username"]').value = 'admin';
        document.querySelector('input[name="password"]').value = '123456';
        document.querySelector('form').submit();
    """)
    time.sleep(3)

    # Open target order tab
    print(f"Opening /sales/{order_id} via inflowMdi...")
    eval_js(f"window.inflowMdi.openTab('/sales/{order_id}', 'Sales Order {order_id}', 'sales');")
    time.sleep(3)

    # Wait for iframe to be fully loaded and initialized
    for i in range(20):
        ready = eval_js("""
            (() => {
                const ifr = window.inflowMdi.getActiveIframe();
                if (!ifr) return false;
                const doc = ifr.contentDocument || ifr.contentWindow.document;
                const win = ifr.contentWindow;
                const inp = doc.getElementById('orderDateInput');
                return !!(doc && win && win.GoogleSheetDatePicker && inp && inp.__gsDatepickerAttached);
            })()
        """)
        if ready:
            print("Active order iframe fully loaded and datepicker initialized!")
            break
        time.sleep(0.5)

    # TEST 1: Datepicker popup and date selection on saved order
    print("\n--- TEST 1: DATEPICKER ON SAVED ORDER ---")
    dp_val = eval_js("""
        (() => {
            const ifr = window.inflowMdi.getActiveIframe();
            const doc = ifr.contentDocument || ifr.contentWindow.document;
            const dateInput = doc.getElementById('orderDateInput');
            const origVal = dateInput.value;

            // 1. Click input
            dateInput.click();
            const pop = doc.getElementById('gsDatepickerPopup');
            const popOpenedOnInputClick = !!(pop && pop.style.display !== 'none');

            // 2. Select a day button (e.g. 15)
            const dayBtns = Array.from(pop.querySelectorAll('.gs-dp-day-btn:not(.gs-dp-day-muted)'));
            const btn15 = dayBtns.find(b => b.textContent.trim() === '15') || dayBtns[0];
            btn15.click();
            const newVal = dateInput.value;
            const popClosedAfterSelect = (pop.style.display === 'none');

            // 3. Click icon to reopen
            const icon = doc.querySelector('.gs-datepicker-icon');
            icon.click();
            const popOpenedOnIconClick = (pop.style.display !== 'none');

            // Close it
            dateInput.click(); // or close

            return {
                origVal,
                newVal,
                popOpenedOnInputClick,
                popClosedAfterSelect,
                popOpenedOnIconClick
            };
        })()
    """)
    print("Datepicker Test Result:", json.dumps(dp_val, indent=2))
    assert dp_val and dp_val.get('popOpenedOnInputClick'), "Datepicker popup did not open on input click!"
    assert dp_val.get('popClosedAfterSelect'), "Popup did not close after selecting date!"
    assert dp_val.get('popOpenedOnIconClick'), "Datepicker popup did not open on icon click!"
    assert dp_val.get('newVal') != '', "Date value was empty!"

    # TEST 2: Customer dropdown HQ isolation & search
    print("\n--- TEST 2: CUSTOMER DROPDOWN HQ ISOLATION ---")
    hq_val = eval_js("""
        (() => {
            const ifr = window.inflowMdi.getActiveIframe();
            const doc = ifr.contentDocument || ifr.contentWindow.document;
            const win = ifr.contentWindow;

            // Ensure store is set to Main Store (HQ)
            const branchSel = doc.getElementById('soBranchSelect');
            if (branchSel) {
                branchSel.value = '';
                win.handleSoBranchChange('');
            }

            // Focus customer combobox and type 'tola'
            const custInput = doc.getElementById('customerSearchInput');
            custInput.value = 'tola';
            win.filterCustomerDropdown('tola');

            // Check visible rows
            const allRows = Array.from(doc.querySelectorAll('#customerDropdownBody tr.main-cust-row'));
            const visibleRows = allRows.filter(r => r.style.display !== 'none');

            // Check branch_id of all visible rows
            const invalidRows = visibleRows.filter(r => (r.getAttribute('data-branch-id') || '') !== '');

            return {
                activeBranch: win.getActiveOrderBranchId(),
                totalCustRows: allRows.length,
                visibleRowsCount: visibleRows.length,
                visibleCustomerNames: visibleRows.map(r => r.getAttribute('data-cname')),
                invalidRowsForHQCount: invalidRows.length
            };
        })()
    """)
    print("HQ Isolation Result:", json.dumps(hq_val, indent=2))
    assert hq_val and hq_val.get('invalidRowsForHQCount') == 0, f"Found {hq_val.get('invalidRowsForHQCount')} branch customers mixed into HQ!"
    assert hq_val.get('visibleRowsCount') > 0, "Expected at least 1 HQ 'tola' customer!"

    # TEST 3: Switching Store to Branch 1 & Branch Customer Isolation
    print(f"\n--- TEST 3: SWITCHING STORE TO BRANCH {branch_1_id} ---")
    br_val = eval_js(f"""
        (() => {{
            const ifr = window.inflowMdi.getActiveIframe();
            const doc = ifr.contentDocument || ifr.contentWindow.document;
            const win = ifr.contentWindow;

            // Switch store to Branch {branch_1_id}
            const branchSel = doc.getElementById('soBranchSelect');
            branchSel.value = '{branch_1_id}';
            win.handleSoBranchChange('{branch_1_id}');

            // Filter with empty string (open dropdown)
            const custInput = doc.getElementById('customerSearchInput');
            custInput.value = '';
            win.filterCustomerDropdown('');

            const allRows = Array.from(doc.querySelectorAll('#customerDropdownBody tr.main-cust-row'));
            const visibleRows = allRows.filter(r => r.style.display !== 'none');
            const invalidRows = visibleRows.filter(r => r.getAttribute('data-branch-id') !== '{branch_1_id}');

            // Check typing 'tola' on Branch 1 (HQ 'tola' customers must NOT appear!)
            win.filterCustomerDropdown('tola');
            const visibleTolaRows = allRows.filter(r => r.style.display !== 'none');
            const hqTolaAppeared = visibleTolaRows.filter(r => (r.getAttribute('data-branch-id') || '') === '');

            return {{
                activeBranch: win.getActiveOrderBranchId(),
                totalCustRows: allRows.length,
                visibleBranchCustCount: visibleRows.length,
                visibleBranchCustNames: visibleRows.map(r => r.getAttribute('data-cname')),
                invalidRowsForBranchCount: invalidRows.length,
                visibleTolaOnBranchCount: visibleTolaRows.length,
                hqTolaAppearedOnBranchCount: hqTolaAppeared.length
            }};
        }})()
    """)
    print(f"Branch {branch_1_id} Isolation Result:", json.dumps(br_val, indent=2))
    assert br_val and br_val.get('invalidRowsForBranchCount') == 0, "Found non-Branch customers visible on Branch order!"
    assert br_val.get('hqTolaAppearedOnBranchCount') == 0, "HQ 'tola' customers leaked into Branch 1 order!"

    # TEST 4: Quick Add Customer on Active Branch
    print(f"\n--- TEST 4: QUICK ADD CUSTOMER ON BRANCH {branch_1_id} ---")
    test_cust_name = 'Automated Branch1 Cust ' + str(int(time.time()))
    quick_val = eval_js(f"""
        (() => {{
            const ifr = window.inflowMdi.getActiveIframe();
            const doc = ifr.contentDocument || ifr.contentWindow.document;
            const win = ifr.contentWindow;

            // Ensure active branch is Branch {branch_1_id}
            const branchSel = doc.getElementById('soBranchSelect');
            branchSel.value = '{branch_1_id}';
            win.handleSoBranchChange('{branch_1_id}');

            win.openQuickAddCustomerModal('{test_cust_name}');
            const notice = doc.getElementById('quickAddBranchNotice');
            const noticeText = notice ? notice.innerText : '';

            // Fill form
            doc.getElementById('quickAddCustNameInput').value = '{test_cust_name}';
            doc.getElementById('quickAddCustPhoneInput').value = '012999888';

            // Submit
            win.submitQuickAddCustomerAjax();

            return {{
                activeBranchBeforeSubmit: win.getActiveOrderBranchId(),
                noticeText: noticeText,
                createdCustName: '{test_cust_name}'
            }};
        }})()
    """)
    print("Quick Add Modal Open Result:", json.dumps(quick_val, indent=2))
    time.sleep(3) # Wait for AJAX

    # Verify new customer in DOM and in Database
    quick_verify = eval_js("""
        (() => {
            const ifr = window.inflowMdi.getActiveIframe();
            const doc = ifr.contentDocument || ifr.contentWindow.document;
            const custInput = doc.getElementById('customerSearchInput');
            const custIdInput = doc.getElementById('customerIdHidden');

            const newRow = doc.querySelector('#customerDropdownBody tr.main-cust-row');
            return {
                selectedCustName: custInput.value,
                selectedCustId: custIdInput.value,
                newRowBranchId: newRow ? newRow.getAttribute('data-branch-id') : null,
                newRowName: newRow ? newRow.getAttribute('data-cname') : null
            };
        })()
    """)
    print("Quick Add DOM Verification:", json.dumps(quick_verify, indent=2))
    new_cid = int(quick_verify.get('selectedCustId'))
    assert quick_verify.get('newRowBranchId') == str(branch_1_id), f"Expected new customer data-branch-id={branch_1_id}, got {quick_verify.get('newRowBranchId')}"

    # Check database branch_id
    db_conn = psycopg2.connect('postgresql://odoo:odoo@localhost:5432/inflow_premium')
    db_cur = db_conn.cursor()
    db_cur.execute("SELECT id, name, branch_id FROM customers WHERE id = %s", (new_cid,))
    db_row = db_cur.fetchone()
    db_conn.close()
    print("Database customer record:", db_row)
    assert db_row[2] == branch_1_id, f"Customer was NOT saved with branch_id={branch_1_id}! Saved with {db_row[2]}"

    print("\n[SUCCESS] ALL TESTS PASSED SUCCESSFULLY!")

finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    proc.wait()
