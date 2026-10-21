import subprocess
import time
import json
import urllib.request
import os
import websocket

print("=== STARTING SO SIDEBAR SEARCH & POPUP BEHAVIOR TEST ===")

# Start Headless Chrome
user_data = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'chrome_test_popup_' + str(int(time.time())))
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
proc = subprocess.Popen([
    chrome_path, '--headless=new', '--remote-debugging-port=9235', '--remote-allow-origins=*',
    f'--user-data-dir={user_data}', '--no-first-run', '--no-default-browser-check'
])
time.sleep(2)
msg_id = 0

try:
    req = urllib.request.Request("http://localhost:9235/json/new?http://localhost:5050/login", method="PUT")
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

    # 1. Login as chenda
    print("1. Logging in as chenda...")
    eval_js("""
        document.querySelector('input[name="username"]').value = 'chenda';
        document.querySelector('input[name="password"]').value = '123456';
        document.querySelector('form').submit();
    """)
    time.sleep(3)

    # 2. Open sales order workspace
    print("2. Opening /sales/new...")
    eval_js("window.location.href = '/sales/new';")
    time.sleep(4)

    # 3. Check initial sidebar search input and suggestion popup
    check_initial = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const inp = doc.getElementById('soSidebarSearchInput');
            const popup = doc.getElementById('soSidebarCustSuggestPopup');
            return {
                searchValue: inp ? inp.value : null,
                popupDisplay: popup ? window.getComputedStyle(popup).display : null,
                popupStyleAttr: popup ? popup.style.display : null
            };
        })()
    """)
    print("Initial State on /sales/new:", check_initial)
    assert check_initial['searchValue'] != 'chenda', f"Sidebar search box was filled with login name: {check_initial['searchValue']}"
    assert check_initial['popupDisplay'] == 'none', f"Customer suggestion popup popped out on initial load! display={check_initial['popupDisplay']}"

    # 4. Select an order from the sidebar (e.g. click first order card)
    print("4. Selecting an order from the sidebar...")
    click_res = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const firstCard = doc.querySelector('.so-sidebar-card');
            if (firstCard) {
                firstCard.click();
                return { clicked: true, orderId: firstCard.getAttribute('data-order-id') };
            }
            return { clicked: false };
        })()
    """)
    print("Clicked Order Card:", click_res)
    time.sleep(3)

    # 5. Check that selecting an order does NOT pop out customer suggestions!
    check_after_select = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const inp = doc.getElementById('soSidebarSearchInput');
            const popup = doc.getElementById('soSidebarCustSuggestPopup');
            return {
                searchValue: inp ? inp.value : null,
                popupDisplay: popup ? window.getComputedStyle(popup).display : null
            };
        })()
    """)
    print("State After Selecting Order:", check_after_select)
    assert check_after_select['searchValue'] != 'chenda', f"Sidebar search box was filled with login name after selecting order: {check_after_select['searchValue']}"
    assert check_after_select['popupDisplay'] == 'none', f"Customer suggestion popup popped out after selecting order! display={check_after_select['popupDisplay']}"

    # 6. Simulate user actively typing in the search box: popup SHOULD open!
    print("6. Simulating active user typing 'tola' in search input...")
    type_res = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const win = ifr ? ifr.contentWindow : window;
            const inp = doc.getElementById('soSidebarSearchInput');
            if (inp) {
                inp.value = 'tola';
                if (typeof win.handleSoLiveSearch === 'function') {
                    win.handleSoLiveSearch('tola', true); // isUserTyping = true
                }
            }
            const popup = doc.getElementById('soSidebarCustSuggestPopup');
            const tbody = doc.getElementById('soSidebarCustSuggestTbody');
            return {
                popupDisplay: popup ? window.getComputedStyle(popup).display : null,
                suggestRowsCount: tbody ? tbody.querySelectorAll('tr').length : 0
            };
        })()
    """)
    print("State After Active User Typing:", type_res)
    assert type_res['popupDisplay'] == 'block', f"Customer suggestions did NOT pop out when actively searching! display={type_res['popupDisplay']}"
    assert type_res['suggestRowsCount'] > 0, "No suggestions shown when actively typing tola!"

    # 7. Select another order: popup MUST close immediately!
    print("7. Selecting another order while popup was open...")
    select_again_res = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const cards = doc.querySelectorAll('.so-sidebar-card');
            if (cards.length > 1) {
                cards[1].click();
            } else if (cards.length > 0) {
                cards[0].click();
            }
            const popup = doc.getElementById('soSidebarCustSuggestPopup');
            return {
                popupDisplay: popup ? window.getComputedStyle(popup).display : null
            };
        })()
    """)
    print("State Immediately Upon Selecting Order:", select_again_res)
    assert select_again_res['popupDisplay'] == 'none', f"Popup remained open after clicking order! display={select_again_res['popupDisplay']}"

    time.sleep(2)
    final_check = eval_js("""
        (() => {
            const ifr = window.inflowMdi ? window.inflowMdi.getActiveIframe() : null;
            const doc = ifr ? (ifr.contentDocument || ifr.contentWindow.document) : document;
            const popup = doc.getElementById('soSidebarCustSuggestPopup');
            return {
                popupDisplay: popup ? window.getComputedStyle(popup).display : null
            };
        })()
    """)
    print("Final State After Order Navigation Completes:", final_check)
    assert final_check['popupDisplay'] == 'none', f"Popup popped out after fast order navigation completed! display={final_check['popupDisplay']}"

    print("\n[SUCCESS] ALL SO SIDEBAR SEARCH & POPUP CHECKS PASSED 100%!")

finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    proc.wait()
