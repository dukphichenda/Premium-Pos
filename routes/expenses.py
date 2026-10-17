import json
from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, session
from database import query_one, query_all, execute, execute_returning_id
from services.expense_exporter import generate_monthly_excel, generate_monthly_pdf

expenses_bp = Blueprint('expenses', __name__)

DEFAULT_ACCOUNTS_LIST = [
    {'name': 'ABA', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Cash USD', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Cash KHR', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'ACELEDA', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'WING', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Office', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Teamwork', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Tola', 'amount': 0.0, 'expr': '0.00'},
    {'name': 'Borrow', 'amount': 0.0, 'expr': '0.00'}
]

def _normalize_accounts(accounts_data):
    if isinstance(accounts_data, str):
        try:
            accounts_data = json.loads(accounts_data)
        except Exception:
            accounts_data = None

    if isinstance(accounts_data, list):
        normalized = []
        for item in accounts_data:
            if isinstance(item, dict):
                name = str(item.get('name', '')).strip()
                amt = float(item.get('amount', 0) or 0)
                expr = str(item.get('expr', '')).strip()
                if not expr:
                    expr = f"{amt:.2f}"
                if name:
                    normalized.append({
                        'name': name,
                        'amount': amt,
                        'expr': expr
                    })
        if normalized:
            return normalized

    elif isinstance(accounts_data, dict):
        normalized = []
        for k, v in accounts_data.items():
            amt = float(v or 0)
            normalized.append({
                'name': str(k).strip(),
                'amount': amt,
                'expr': f"{amt:.2f}"
            })
        if normalized:
            return normalized

    return [acc.copy() for acc in DEFAULT_ACCOUNTS_LIST]

def _get_current_month_key():
    return datetime.now().strftime('%Y-%m')

def _get_previous_month_key(month_key):
    try:
        parts = month_key.split('-')
        year = int(parts[0])
        month = int(parts[1])
        if month == 1:
            return f"{year - 1:04d}-12"
        else:
            return f"{year:04d}-{month - 1:02d}"
    except Exception:
        return None

def _format_month_display(ym):
    try:
        parts = ym.split('-')
        year = parts[0]
        month_num = int(parts[1])
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        m_name = month_names[month_num - 1]
        yy = year[-2:]
        return f"{m_name} '{yy}"
    except Exception:
        return ym

def _get_available_months():
    rows = query_all("""
        SELECT DISTINCT month_key FROM expenses WHERE month_key IS NOT NULL
        UNION
        SELECT DISTINCT month_key FROM monthly_cash_summaries WHERE month_key IS NOT NULL
        UNION
        SELECT DISTINCT month_key FROM media_receipts WHERE month_key IS NOT NULL
        UNION
        SELECT DISTINCT TO_CHAR(order_date, 'YYYY-MM') as month_key 
        FROM sales_orders 
        WHERE order_date IS NOT NULL AND order_date >= '2025-01-01'
        ORDER BY month_key DESC
    """)
    months = [r['month_key'] for r in rows if r['month_key']]
    current_ym = _get_current_month_key()
    if current_ym not in months:
        months.insert(0, current_ym)
    return sorted(list(set(months)), reverse=True)

def _get_inflow_sales_data(month_key, branch_id='main'):
    """
    Returns inFlow sales metrics for a given month scoped to a store/branch:
    - 'main' or None: strictly Main Store HQ sales (branch_id IS NULL)
    - digit or int: strictly that branch (branch_id = %s)
    - 'all': all stores combined
    """
    if str(branch_id).lower() == 'all':
        branch_clause = ""
        params = (month_key,)
    elif branch_id and str(branch_id).isdigit():
        branch_clause = "AND branch_id = %s"
        params = (month_key, int(branch_id))
    else:
        # Default is Main Store HQ only (branch_id IS NULL)
        branch_clause = "AND branch_id IS NULL"
        params = (month_key,)

    so_stats = query_one(f"""
        SELECT 
            COUNT(*) as invoice_count,
            COUNT(CASE WHEN status = 'PAID' OR payment_status = 'PAID' THEN 1 END) as paid_invoice_count,
            COALESCE(SUM(total_amount), 0) as total_invoiced,
            COALESCE(SUM(CASE WHEN status = 'PAID' OR payment_status = 'PAID' THEN total_amount ELSE 0 END), 0) as total_paid
        FROM sales_orders
        WHERE TO_CHAR(order_date, 'YYYY-MM') = %s
          AND status != 'CANCELLED'
          {branch_clause}
    """, params)

    invoiced = float(so_stats['total_invoiced'] if so_stats else 0.0)
    paid = float(so_stats['total_paid'] if so_stats else 0.0)

    return {
        'invoice_count': int(so_stats['invoice_count'] if so_stats else 0),
        'paid_invoice_count': int(so_stats['paid_invoice_count'] if so_stats else 0),
        'total_invoiced': invoiced,
        'total_paid': paid
    }

def _calculate_month_money_in_hand(month_key, visited=None, branch_id='main'):
    """
    Calculate Money in Hand for a month:
    - For HQ: (Opening Balance + Clear STM + Media Total + Customer Receipts) - Total Expenses
    - For Branch: (Opening Balance + Customer Receipts) - Total Expenses (Clear STM & Media are 0)
    """
    if not month_key:
        return 0.0
    if visited is None:
        visited = set()
    if month_key in visited or len(visited) > 12:
        return 0.0
    visited.add(month_key)

    is_branch = (branch_id and str(branch_id).lower() not in ('main', 'all'))
    branch_id_val = int(branch_id) if is_branch and str(branch_id).isdigit() else None

    if branch_id_val is not None:
        summary = query_one("SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s", (month_key, branch_id_val))
    elif str(branch_id).lower() == 'all':
        summary = None
    else:
        summary = query_one("SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))

    # 1. Opening balance
    if summary and summary.get('manual_opening_balance') is not None:
        opening = float(summary['manual_opening_balance'])
    elif summary and summary.get('opening_balance') is not None and float(summary['opening_balance']) > 0:
        opening = float(summary['opening_balance'])
    else:
        prev_m = _get_previous_month_key(month_key)
        if prev_m:
            opening = _calculate_month_money_in_hand(prev_m, visited, branch_id=branch_id)
        else:
            opening = 0.0

    # 2. Clear STM and Media Total (Branch has NO STM and NO Media; HQ / Main has STM and Media)
    if is_branch:
        stm = 0.0
        media_total = 0.0
    else:
        stm = float(summary['clear_stm'] or 0) if summary else 0.0
        media_rec = query_one("SELECT COALESCE(SUM(amount), 0) as tot FROM media_receipts WHERE month_key = %s", (month_key,))
        media_sheet_total = float(media_rec['tot'] or 0) if media_rec else 0.0

        if summary and summary.get('manual_media_income') is not None:
            media_total = float(summary['manual_media_income'])
        elif media_sheet_total > 0:
            media_total = media_sheet_total
        elif summary and summary.get('media_expense') and float(summary['media_expense']) > 0:
            media_total = float(summary['media_expense'])
        else:
            media_total = 0.0

    # 3. Sales Received
    if summary and summary.get('custom_sales_income') is not None:
        sales = float(summary['custom_sales_income'] or 0)
    else:
        sales = _get_inflow_sales_data(month_key, branch_id=branch_id)['total_paid']

    # 4. Total Expenses
    if branch_id_val is not None:
        exp_res = query_one("SELECT COALESCE(SUM(total_price), 0) as tot FROM expenses WHERE month_key = %s AND branch_id = %s", (month_key, branch_id_val))
    elif str(branch_id).lower() == 'all':
        exp_res = query_one("SELECT COALESCE(SUM(total_price), 0) as tot FROM expenses WHERE month_key = %s", (month_key,))
    else:
        exp_res = query_one("SELECT COALESCE(SUM(total_price), 0) as tot FROM expenses WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))
    total_exp = float(exp_res['tot'] or 0) if exp_res else 0.0

    total_inflow = opening + stm + media_total + sales
    money_in_hand = total_inflow - total_exp
    return money_in_hand

def _get_or_create_monthly_summary(month_key, branch_id='main'):
    is_branch = (branch_id and str(branch_id).lower() not in ('main', 'all'))
    branch_id_val = int(branch_id) if is_branch and str(branch_id).isdigit() else None

    if branch_id_val is not None:
        summary = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s",
            (month_key, branch_id_val)
        )
    else:
        summary = query_one(
            "SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)",
            (month_key,)
        )

    if not summary:
        prev_m = _get_previous_month_key(month_key)
        scope_arg = str(branch_id_val) if branch_id_val is not None else 'main'
        carried_opening = _calculate_month_money_in_hand(prev_m, branch_id=scope_arg) if prev_m else 0.0

        if branch_id_val is not None:
            execute("""
                INSERT INTO monthly_cash_summaries (month_key, branch_id, opening_balance, manual_opening_balance, media_expense, manual_media_income, clear_stm, accounts_json)
                VALUES (%s, %s, %s, NULL, 0.0, NULL, 0.0, %s)
            """, (month_key, branch_id_val, carried_opening, json.dumps(DEFAULT_ACCOUNTS_LIST)))
            summary = query_one("SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s", (month_key, branch_id_val))
        else:
            execute("""
                INSERT INTO monthly_cash_summaries (month_key, branch_id, opening_balance, manual_opening_balance, media_expense, manual_media_income, clear_stm, accounts_json)
                VALUES (%s, NULL, %s, NULL, 0.0, NULL, 0.0, %s)
            """, (month_key, carried_opening, json.dumps(DEFAULT_ACCOUNTS_LIST)))
            summary = query_one("SELECT * FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))

    return summary

def _get_monthly_report_data(month_key, branch_id='main'):
    """Calculates and aggregates complete financial data for a given month and branch/store scope."""
    is_branch = (branch_id and str(branch_id).lower() not in ('main', 'all'))
    branch_id_val = int(branch_id) if is_branch and str(branch_id).isdigit() else None

    summary = _get_or_create_monthly_summary(month_key, branch_id=branch_id)
    inflow_data = _get_inflow_sales_data(month_key, branch_id=branch_id)

    # 1. Daily expenses
    if branch_id_val is not None:
        expenses = query_all("""
            SELECT * FROM expenses
            WHERE month_key = %s AND branch_id = %s
            ORDER BY expense_date ASC, id ASC
        """, (month_key, branch_id_val))
    elif str(branch_id).lower() == 'all':
        expenses = query_all("""
            SELECT * FROM expenses
            WHERE month_key = %s
            ORDER BY expense_date ASC, id ASC
        """, (month_key,))
    else:
        # Default Main Store (branch_id IS NULL or 0)
        expenses = query_all("""
            SELECT * FROM expenses
            WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)
            ORDER BY expense_date ASC, id ASC
        """, (month_key,))
    total_expenses = sum(float(e['total_price'] or 0) for e in expenses)

    # 2. Media receipts & Clear STM logic
    if is_branch:
        # Branches do not have Clear STM or Media money
        media_receipts = []
        media_sheet_total = 0.0
        media_total = 0.0
        is_manual_media = False
        clear_stm = 0.0
    else:
        # HQ / Main Store
        media_receipts = query_all("""
            SELECT * FROM media_receipts
            WHERE month_key = %s
            ORDER BY receipt_date ASC, id ASC
        """, (month_key,))
        media_sheet_total = sum(float(r['amount'] or 0) for r in media_receipts)

        is_manual_media = (summary.get('manual_media_income') is not None)
        if is_manual_media:
            media_total = float(summary['manual_media_income'])
        else:
            media_total = media_sheet_total
            if summary and summary.get('id'):
                execute("UPDATE monthly_cash_summaries SET media_expense = %s WHERE id = %s", (media_total, summary['id']))
                summary['media_expense'] = media_total

        clear_stm = float(summary.get('clear_stm') or 0)

    # 3. Dynamic Opening Balance logic
    prev_m = _get_previous_month_key(month_key)
    prev_money_in_hand = _calculate_month_money_in_hand(prev_m, branch_id=branch_id) if prev_m else 0.0

    is_manual_opening = (summary.get('manual_opening_balance') is not None)
    if is_manual_opening:
        opening_balance = float(summary['manual_opening_balance'])
    else:
        opening_balance = prev_money_in_hand
        if summary and summary.get('id'):
            execute("UPDATE monthly_cash_summaries SET opening_balance = %s WHERE id = %s", (opening_balance, summary['id']))
            summary['opening_balance'] = opening_balance

    # 4. Sales Receipts
    is_custom_sales = (summary.get('custom_sales_income') is not None)
    if is_custom_sales:
        sales_received = float(summary['custom_sales_income'] or 0)
    else:
        sales_received = inflow_data['total_paid']

    # 5. Inflow & Balances
    total_money_in = opening_balance + clear_stm + media_total + sales_received
    money_in_hand = total_money_in - total_expenses
    if is_branch:
        # Branch net operating income is strictly Sales minus Expenses
        net_operating_income = sales_received - total_expenses
    else:
        net_operating_income = (sales_received + clear_stm + media_total) - total_expenses

    # 6. Accounts Reconciliation
    accounts = _normalize_accounts(summary.get('accounts_json'))
    total_counted_cash = sum(float(a['amount'] or 0) for a in accounts)
    cash_variance = total_counted_cash - money_in_hand

    return {
        'month_key': month_key,
        'month_display': _format_month_display(month_key),
        'branch_id': branch_id,
        'is_branch': is_branch,
        'summary': summary,
        'inflow_data': inflow_data,
        'expenses': expenses,
        'total_expenses': total_expenses,
        'opening_balance': opening_balance,
        'is_manual_opening': is_manual_opening,
        'prev_money_in_hand': prev_money_in_hand,
        'prev_month_display': _format_month_display(prev_m) if prev_m else '',
        'clear_stm': clear_stm,
        'media_receipts': media_receipts,
        'media_sheet_total': media_sheet_total,
        'media_total': media_total,
        'is_manual_media': is_manual_media,
        'sales_received': sales_received,
        'is_custom_sales': is_custom_sales,
        'total_money_in': total_money_in,
        'money_in_hand': money_in_hand,
        'net_operating_income': net_operating_income,
        'accounts': accounts,
        'total_counted_cash': total_counted_cash,
        'cash_variance': cash_variance
    }

@expenses_bp.route('/expenses')
@expenses_bp.route('/expenses/monthly')
def monthly_expenses():
    user_role = session.get('role', 'branch_admin')
    user_bid = session.get('branch_id')
    is_main_admin = (user_role == 'main_admin')

    if not is_main_admin and user_bid:
        branch_scope = str(user_bid)
        branches = query_all("SELECT id, code, name, color, settings_json FROM branches WHERE id = %s", (user_bid,))
    else:
        branch_scope = request.args.get('branch', 'main').strip().lower()
        branches = query_all("SELECT id, code, name, color, settings_json FROM branches WHERE is_active = TRUE ORDER BY id ASC")

    for b in branches:
        raw_s = b.get('settings_json')
        s_dict = json.loads(raw_s) if isinstance(raw_s, str) else (raw_s or {})
        b['logo_url'] = s_dict.get('logo_url') or ''

    # Resolve store names
    if branch_scope == 'main':
        current_store_name = 'Main Store (HQ)'
        current_store_code = 'HQ'
    elif branch_scope == 'all':
        current_store_name = 'All Combined'
        current_store_code = 'ALL'
    else:
        matching = next((b for b in branches if str(b['id']) == branch_scope), None)
        current_store_name = f"{matching['code']} - {matching['name']}" if matching else f"Branch {branch_scope}"
        current_store_code = matching['code'] if matching else 'Branch'

    month_key = request.args.get('month', '').strip()
    if not month_key:
        month_key = _get_current_month_key()

    all_months = _get_available_months()
    if month_key not in all_months:
        all_months.insert(0, month_key)

    month_tabs = [{'key': m, 'label': _format_month_display(m)} for m in all_months]
    report_data = _get_monthly_report_data(month_key, branch_id=branch_scope)

    # Categories list
    categories = query_all("SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
    cat_names = [c['category'] for c in categories]
    for dc in ['Salary', 'Supplier', 'Food', 'Rent/Office', 'Supplies', 'Delivery', 'Packaging', 'General']:
        if dc not in cat_names:
            cat_names.append(dc)

    # Payers list
    payers = query_all("SELECT DISTINCT paid_by FROM expenses WHERE paid_by IS NOT NULL AND paid_by != '' ORDER BY paid_by ASC")
    payer_names = [p['paid_by'] for p in payers]
    for dp in ['Chenda', 'Veasna', 'Office']:
        if dp not in payer_names:
            payer_names.append(dp)

    return render_template('expenses/monthly.html',
                           current_month=month_key,
                           month_tabs=month_tabs,
                           month_display=report_data['month_display'],
                           branch_scope=branch_scope,
                           is_branch=report_data['is_branch'],
                           branches=branches,
                           current_store_name=current_store_name,
                           current_store_code=current_store_code,
                           is_main_admin=is_main_admin,
                           expenses=report_data['expenses'],
                           summary=report_data['summary'],
                           inflow_data=report_data['inflow_data'],
                           total_expenses=report_data['total_expenses'],
                           opening_balance=report_data['opening_balance'],
                           is_manual_opening=report_data['is_manual_opening'],
                           prev_money_in_hand=report_data['prev_money_in_hand'],
                           prev_month_display=report_data['prev_month_display'],
                           clear_stm=report_data['clear_stm'],
                           media_receipts=report_data['media_receipts'],
                           media_sheet_total=report_data['media_sheet_total'],
                           media_total=report_data['media_total'],
                           is_manual_media=report_data['is_manual_media'],
                           sales_received=report_data['sales_received'],
                           is_custom_sales=report_data['is_custom_sales'],
                           total_money_in=report_data['total_money_in'],
                           money_in_hand=report_data['money_in_hand'],
                           net_operating_income=report_data['net_operating_income'],
                           accounts=report_data['accounts'],
                           total_counted_cash=report_data['total_counted_cash'],
                           cash_variance=report_data['cash_variance'],
                           categories=cat_names,
                           payers=payer_names,
                           today_date=date.today().strftime('%Y-%m-%d'))

# --- Monthly Sheet Deletion ---

@expenses_bp.route('/expenses/month/delete', methods=['POST'])
@expenses_bp.route('/expenses/delete-month', methods=['POST'])
def delete_month():
    try:
        data = request.form if request.form else (request.get_json() or {})
        month_key = data.get('month_key', '').strip()
        if not month_key:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Month key is required'}), 400
            flash('Month key is required.', 'error')
            return redirect(url_for('expenses.monthly_expenses'))

        bid_raw = data.get('branch_scope') or data.get('branch_id') or request.args.get('branch')
        if bid_raw and str(bid_raw).isdigit():
            branch_id = int(bid_raw)
            execute("DELETE FROM expenses WHERE month_key = %s AND branch_id = %s", (month_key, branch_id))
            execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s", (month_key, branch_id))
            branch_param = str(branch_id)
        elif str(bid_raw).lower() == 'all':
            execute("DELETE FROM expenses WHERE month_key = %s", (month_key,))
            execute("DELETE FROM media_receipts WHERE month_key = %s", (month_key,))
            execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s", (month_key,))
            branch_param = 'all'
        else:
            execute("DELETE FROM expenses WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))
            execute("DELETE FROM media_receipts WHERE month_key = %s", (month_key,))
            execute("DELETE FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))
            branch_param = 'main'

        month_display = _format_month_display(month_key)

        if request.is_json:
            return jsonify({'success': True, 'message': f"Monthly sheet '{month_display}' was deleted successfully."})

        flash(f"Monthly sheet '{month_display}' entries were deleted successfully.", 'success')

        remaining_months = _get_available_months()
        if remaining_months:
            curr = _get_current_month_key()
            target = curr if curr in remaining_months else remaining_months[0]
            return redirect(url_for('expenses.monthly_expenses', month=target, branch=branch_param))
        else:
            return redirect(url_for('expenses.monthly_expenses', branch=branch_param))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error deleting month: {e}", 'error')
        return redirect(url_for('expenses.monthly_expenses'))

# --- Export to Excel & PDF & Print View ---

@expenses_bp.route('/expenses/export/excel')
def export_monthly_excel():
    try:
        month_key = request.args.get('month', '').strip() or _get_current_month_key()
        branch_scope = request.args.get('branch', 'main').strip().lower()
        report_data = _get_monthly_report_data(month_key, branch_id=branch_scope)
        excel_buf = generate_monthly_excel(report_data)
        filename = f"inFlow_Monthly_Report_{month_key}_{branch_scope}.xlsx"
        return send_file(
            excel_buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        flash(f"Error generating Excel report: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/export/pdf')
def export_monthly_pdf():
    try:
        month_key = request.args.get('month', '').strip() or _get_current_month_key()
        branch_scope = request.args.get('branch', 'main').strip().lower()
        report_data = _get_monthly_report_data(month_key, branch_id=branch_scope)
        pdf_buf = generate_monthly_pdf(report_data)
        filename = f"inFlow_Monthly_Report_{month_key}_{branch_scope}.pdf"
        return send_file(
            pdf_buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )
    except Exception as e:
        flash(f"Error generating PDF report: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/print')
def print_monthly_report():
    month_key = request.args.get('month', '').strip() or _get_current_month_key()
    branch_scope = request.args.get('branch', 'main').strip().lower()
    report_data = _get_monthly_report_data(month_key, branch_id=branch_scope)
    return render_template(
        'expenses/print.html',
        current_month=month_key,
        branch_scope=branch_scope,
        is_branch=report_data['is_branch'],
        month_display=report_data['month_display'],
        expenses=report_data['expenses'],
        total_expenses=report_data['total_expenses'],
        opening_balance=report_data['opening_balance'],
        clear_stm=report_data['clear_stm'],
        media_receipts=report_data['media_receipts'],
        media_total=report_data['media_total'],
        sales_received=report_data['sales_received'],
        total_money_in=report_data['total_money_in'],
        money_in_hand=report_data['money_in_hand'],
        net_operating_income=report_data['net_operating_income'],
        accounts=report_data['accounts'],
        total_counted_cash=report_data['total_counted_cash'],
        cash_variance=report_data['cash_variance'],
        today_date=date.today().strftime('%d-%b-%Y')
    )

# --- Expense Row Endpoints ---

@expenses_bp.route('/expenses/add', methods=['POST'])
def add_expense():
    try:
        data = request.form if request.form else (request.get_json() or {})
        
        item = data.get('item', '').strip()
        if not item:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Item description is required'}), 400
            flash('Item description is required.', 'error')
            return redirect(request.referrer or url_for('expenses.monthly_expenses'))

        exp_date_str = data.get('expense_date', '').strip()
        if exp_date_str:
            try:
                exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
            except Exception:
                exp_date = date.today()
        else:
            exp_date = date.today()

        unit_price = float(data.get('unit_price', 0) or 0)
        quantity = float(data.get('quantity', 1) or 1)
        total_price = float(data.get('total_price', 0) or (unit_price * quantity))

        paid_by = data.get('paid_by', '').strip()
        category = data.get('category', 'General').strip()
        notes = data.get('notes', '').strip()
        month_key = data.get('month_key', '').strip() or exp_date.strftime('%Y-%m')

        bid_raw = data.get('branch_id')
        if bid_raw is None or bid_raw == '':
            bid_raw = request.args.get('branch')
        if bid_raw is None or bid_raw == '':
            bid_raw = session.get('branch_id')

        if bid_raw and str(bid_raw).isdigit():
            branch_id = int(bid_raw)
        else:
            branch_id = None

        new_id = execute_returning_id("""
            INSERT INTO expenses (expense_date, item, category, unit_price, quantity, total_price, paid_by, notes, month_key, branch_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (exp_date, item, category, unit_price, quantity, total_price, paid_by, notes, month_key, branch_id))

        _get_or_create_monthly_summary(month_key, branch_id=str(branch_id) if branch_id else 'main')

        if request.is_json:
            return jsonify({
                'success': True,
                'id': new_id,
                'message': f"Recorded expense '{item}' successfully!"
            })

        flash(f"Recorded expense '{item}' (${total_price:,.2f}) successfully!", 'success')
        branch_param = str(branch_id) if branch_id else 'main'
        return redirect(url_for('expenses.monthly_expenses', month=month_key, branch=branch_param))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error adding expense: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error adding expense: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/<int:id>/update', methods=['POST'])
def update_expense(id):
    try:
        data = request.form if request.form else (request.get_json() or {})
        
        item = data.get('item', '').strip()
        unit_price = float(data.get('unit_price', 0) or 0)
        quantity = float(data.get('quantity', 1) or 1)
        total_price = float(data.get('total_price', 0) or (unit_price * quantity))
        paid_by = data.get('paid_by', '').strip()
        category = data.get('category', '').strip()
        notes = data.get('notes', '').strip()

        exp_date_str = data.get('expense_date', '').strip()
        if exp_date_str:
            try:
                exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
                month_key = exp_date.strftime('%Y-%m')
                execute("""
                    UPDATE expenses 
                    SET item = %s, unit_price = %s, quantity = %s, total_price = %s, 
                        paid_by = %s, category = %s, notes = %s, expense_date = %s, month_key = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (item, unit_price, quantity, total_price, paid_by, category, notes, exp_date, month_key, id))
            except Exception:
                execute("""
                    UPDATE expenses 
                    SET item = %s, unit_price = %s, quantity = %s, total_price = %s, 
                        paid_by = %s, category = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (item, unit_price, quantity, total_price, paid_by, category, notes, id))
        else:
            execute("""
                UPDATE expenses 
                SET item = %s, unit_price = %s, quantity = %s, total_price = %s, 
                    paid_by = %s, category = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (item, unit_price, quantity, total_price, paid_by, category, notes, id))

        if request.is_json:
            return jsonify({'success': True, 'message': 'Expense updated successfully'})

        flash('Expense updated successfully!', 'success')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error updating expense: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/<int:id>/delete', methods=['POST'])
def delete_expense(id):
    try:
        execute("DELETE FROM expenses WHERE id = %s", (id,))
        if request.is_json:
            return jsonify({'success': True, 'message': 'Expense deleted'})
        flash('Expense deleted successfully.', 'success')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error deleting expense: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

# --- Media Receipts Endpoints ---

@expenses_bp.route('/expenses/media/add', methods=['POST'])
def add_media_receipt():
    try:
        data = request.form if request.form else (request.get_json() or {})
        
        customer_name = data.get('customer_name', '').strip()
        if not customer_name:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Customer name is required'}), 400
            flash('Customer name is required.', 'error')
            return redirect(request.referrer or url_for('expenses.monthly_expenses'))

        rec_date_str = data.get('receipt_date', '').strip()
        if rec_date_str:
            try:
                rec_date = datetime.strptime(rec_date_str, '%Y-%m-%d').date()
            except Exception:
                rec_date = date.today()
        else:
            rec_date = date.today()

        amount = float(data.get('amount', 0) or 0)
        notes = data.get('notes', '').strip()
        month_key = data.get('month_key', '').strip() or rec_date.strftime('%Y-%m')

        new_id = execute_returning_id("""
            INSERT INTO media_receipts (receipt_date, customer_name, amount, notes, month_key)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (rec_date, customer_name, amount, notes, month_key))

        # Check if manual override is active; if not, auto-sync media_expense
        summary = query_one("SELECT manual_media_income FROM monthly_cash_summaries WHERE month_key = %s", (month_key,))
        if not summary or summary.get('manual_media_income') is None:
            med_tot = query_one("SELECT COALESCE(SUM(amount), 0) as tot FROM media_receipts WHERE month_key = %s", (month_key,))
            tot_val = float(med_tot['tot'] if med_tot else 0)
            execute("UPDATE monthly_cash_summaries SET media_expense = %s WHERE month_key = %s", (tot_val, month_key))

        if request.is_json:
            return jsonify({'success': True, 'id': new_id, 'message': 'Media receipt added successfully'})

        flash(f"Recorded Media receipt from '{customer_name}' (${amount:,.2f}) successfully!", 'success')
        return redirect(url_for('expenses.monthly_expenses', month=month_key))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error adding media receipt: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/media/<int:id>/update', methods=['POST'])
def update_media_receipt(id):
    try:
        data = request.form if request.form else (request.get_json() or {})
        customer_name = data.get('customer_name', '').strip()
        amount = float(data.get('amount', 0) or 0)
        notes = data.get('notes', '').strip()

        rec_date_str = data.get('receipt_date', '').strip()
        if rec_date_str:
            try:
                rec_date = datetime.strptime(rec_date_str, '%Y-%m-%d').date()
                month_key = rec_date.strftime('%Y-%m')
                execute("""
                    UPDATE media_receipts
                    SET customer_name = %s, amount = %s, notes = %s, receipt_date = %s, month_key = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (customer_name, amount, notes, rec_date, month_key, id))
            except Exception:
                execute("""
                    UPDATE media_receipts
                    SET customer_name = %s, amount = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (customer_name, amount, notes, id))
        else:
            execute("""
                UPDATE media_receipts
                SET customer_name = %s, amount = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (customer_name, amount, notes, id))

        if request.is_json:
            return jsonify({'success': True, 'message': 'Media receipt updated'})
        flash('Media receipt updated successfully.', 'success')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error updating media receipt: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

@expenses_bp.route('/expenses/media/<int:id>/delete', methods=['POST'])
def delete_media_receipt(id):
    try:
        row = query_one("SELECT month_key FROM media_receipts WHERE id = %s", (id,))
        month_key = row['month_key'] if row else None

        execute("DELETE FROM media_receipts WHERE id = %s", (id,))

        if month_key:
            summary = query_one("SELECT manual_media_income FROM monthly_cash_summaries WHERE month_key = %s", (month_key,))
            if not summary or summary.get('manual_media_income') is None:
                med_tot = query_one("SELECT COALESCE(SUM(amount), 0) as tot FROM media_receipts WHERE month_key = %s", (month_key,))
                tot_val = float(med_tot['tot'] if med_tot else 0)
                execute("UPDATE monthly_cash_summaries SET media_expense = %s WHERE month_key = %s", (tot_val, month_key))

        if request.is_json:
            return jsonify({'success': True, 'message': 'Media receipt deleted'})
        flash('Media receipt deleted successfully.', 'success')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error deleting media receipt: {e}", 'error')
        return redirect(request.referrer or url_for('expenses.monthly_expenses'))

# --- Monthly Summary & Balances Update ---

@expenses_bp.route('/expenses/summary/update', methods=['POST'])
def update_monthly_summary():
    try:
        data = request.get_json() if request.is_json else request.form
        month_key = data.get('month_key', '').strip()
        if not month_key:
            return jsonify({'success': False, 'error': 'Month key required'}), 400

        bid_raw = data.get('branch_id')
        if bid_raw is None or bid_raw == '':
            bid_raw = request.args.get('branch')
        if bid_raw and str(bid_raw).isdigit():
            branch_id = int(bid_raw)
            is_branch = True
        else:
            branch_id = None
            is_branch = False

        # 1. Opening Balance: Manual vs Auto
        mob_raw = data.get('manual_opening_balance')
        if mob_raw is None or str(mob_raw).strip() == '':
            mob_raw = data.get('opening_balance')
        scope_arg = str(branch_id) if branch_id else 'main'
        if mob_raw is not None and str(mob_raw).strip() != '':
            manual_opening = float(mob_raw)
            opening_balance = manual_opening
        else:
            manual_opening = None
            prev_m = _get_previous_month_key(month_key)
            opening_balance = _calculate_month_money_in_hand(prev_m, branch_id=scope_arg) if prev_m else 0.0

        if is_branch:
            clear_stm = 0.0
            media_total = 0.0
            manual_media = None
        else:
            clear_stm = float(data.get('clear_stm', 0) or 0)
            mmi_raw = data.get('manual_media_income')
            if mmi_raw is None or str(mmi_raw).strip() == '':
                mmi_raw = data.get('media')
            if mmi_raw is None or str(mmi_raw).strip() == '':
                mmi_raw = data.get('media_expense')
            if mmi_raw is not None and str(mmi_raw).strip() != '':
                manual_media = float(mmi_raw)
                media_total = manual_media
            else:
                manual_media = None
                med_tot = query_one("SELECT COALESCE(SUM(amount), 0) as tot FROM media_receipts WHERE month_key = %s", (month_key,))
                media_total = float(med_tot['tot'] if med_tot else 0)
        
        custom_sales = data.get('custom_sales_income')
        if custom_sales is None or str(custom_sales).strip() == '':
            custom_sales = data.get('inflow_sales')
        if custom_sales is not None and str(custom_sales).strip() != '':
            custom_sales = float(custom_sales)
        else:
            custom_sales = None

        accounts_data = data.get('accounts_json')
        if accounts_data is None:
            accounts_data = data.get('accounts')
        accounts_list = _normalize_accounts(accounts_data)

        if branch_id is not None:
            existing = query_one("SELECT id FROM monthly_cash_summaries WHERE month_key = %s AND branch_id = %s", (month_key, branch_id))
        else:
            existing = query_one("SELECT id FROM monthly_cash_summaries WHERE month_key = %s AND (branch_id IS NULL OR branch_id = 0)", (month_key,))

        if existing:
            execute("""
                UPDATE monthly_cash_summaries
                SET opening_balance = %s,
                    manual_opening_balance = %s,
                    clear_stm = %s,
                    media_expense = %s,
                    manual_media_income = %s,
                    custom_sales_income = %s,
                    accounts_json = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (opening_balance, manual_opening, clear_stm, media_total, manual_media, custom_sales, json.dumps(accounts_list), existing['id']))
        else:
            execute("""
                INSERT INTO monthly_cash_summaries (month_key, branch_id, opening_balance, manual_opening_balance, clear_stm, media_expense, manual_media_income, custom_sales_income, accounts_json, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (month_key, branch_id, opening_balance, manual_opening, clear_stm, media_total, manual_media, custom_sales, json.dumps(accounts_list)))

        return jsonify({
            'success': True,
            'message': 'Monthly financial summary updated successfully!',
            'opening_balance': opening_balance,
            'is_manual_opening': (manual_opening is not None),
            'media_total': media_total,
            'is_manual_media': (manual_media is not None),
            'branch_id': branch_id
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@expenses_bp.route('/expenses/summary-dashboard')
def summary_dashboard():
    all_months = _get_available_months()
    month_data = []

    for m in all_months:
        report = _get_monthly_report_data(m)
        exp_count = len(report['expenses'])

        month_data.append({
            'month_key': m,
            'month_display': report['month_display'],
            'opening_balance': report['opening_balance'],
            'clear_stm': report['clear_stm'],
            'media_total': report['media_total'],
            'sales_received': report['sales_received'],
            'inflow_invoiced': report['inflow_data']['total_invoiced'],
            'total_expenses': report['total_expenses'],
            'expense_count': exp_count,
            'total_money_in': report['total_money_in'],
            'money_in_hand': report['money_in_hand'],
            'net_profit': report['net_operating_income']
        })

    return render_template('expenses/dashboard.html', month_data=month_data)
