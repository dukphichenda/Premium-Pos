import os
import time
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from werkzeug.utils import secure_filename
from database import query_one, query_all, execute
from services.backup_service import (
    get_backup_settings, save_backup_settings, list_backups,
    create_backup, restore_backup, test_gdrive_config,
    save_backup_to_gdrive, get_backup_dir, format_file_size
)

settings_bp = Blueprint('settings', __name__)

def get_invoice_settings():
    inv = query_one("SELECT * FROM invoice_settings LIMIT 1")
    if not inv:
        execute("""
            INSERT INTO invoice_settings (
                font_family, primary_color, secondary_color,
                shop_name_kh, shop_name_en, shop_address_kh, shop_address_en,
                phone, email, website, vat_tin,
                invoice_title_kh, invoice_title_en,
                enable_khr_total, khr_exchange_rate, qr_code_url,
                bank_name, account_name, account_number,
                payment_terms, footer_notes_kh, footer_notes_en,
                show_signature, show_sku, show_tax,
                qr_size, qr_position, bank_info_size, bank_info_position,
                qr_offset_x, qr_offset_y, bank_offset_x, bank_offset_y,
                seller_signature_url, seller_name, unit_price_decimals
            ) VALUES (
                'Kantumruy Pro', '#0284C7', '#0F172A',
                'ក្រុមហ៊ុន អ៊ិនហ្វ្លូ ត្រេឌីង (ខេមបូឌា)', 'inFlow Premium Trading Co., Ltd.',
                'ផ្ទះលេខ ១២៣, មហាវិថីព្រះមុនីវង្ស, សង្កាត់បឹងកេងកង១, ខណ្ឌចំការមន, រាជធានីភ្នំពេញ',
                '#123, Preah Monivong Blvd, Sangkat Boeung Keng Kang 1, Phnom Penh, Cambodia',
                '+855 23 888 999 / +855 12 345 678', 'billing@inflowpremium.com.kh', 'www.inflowpremium.com.kh', 'K001-902103456',
                'វិក្កយបត្រ', 'INVOICE',
                TRUE, 4100.00, '/static/uploads/invoice/sample_khqr.png',
                'ABA Bank (KHQR / Bakong)', 'INFLOW TRADING CO LTD', '001 234 567 (USD) | 001 234 568 (KHR)',
                'ទូទាត់ភ្លាមៗពេលទទួលទំនិញ / Due on Receipt',
                'ទំនិញដែលបានទិញរួចមិនអាចប្តូរវិញបានទេ! សូមអរគុណចំពោះការគាំទ្ររបស់លោកអ្នក!',
                'Goods sold are not returnable. Thank you for your business!',
                TRUE, TRUE, TRUE,
                180, 'left', '8.5', 'below_qr',
                0, 0, 0, 0,
                NULL, NULL, 3
            );
        """)
        inv = query_one("SELECT * FROM invoice_settings LIMIT 1")
    return inv

@settings_bp.route('/settings')
def general_settings():
    company = query_one("SELECT * FROM companies LIMIT 1")
    if not company:
        execute("""
            INSERT INTO companies (
                name, email, phone, country, currency_code, currency_symbol,
                decimal_places_price, decimal_places_cost, decimal_places_qty,
                decimal_places_markup, decimal_places_total, decimal_places_measurement
            ) VALUES (
                'inFlow Premium Business', 'info@inflowpremium.local', '+855 23 888 999', 'Cambodia', 'USD', '$',
                2, 3, 0, 2, 2, 2
            );
        """)
        company = query_one("SELECT * FROM companies LIMIT 1")

    inv_settings = get_invoice_settings()

    pricing_schemes = query_one("SELECT COUNT(*) as cnt FROM pricing_schemes")['cnt']
    locations_count = query_one("SELECT COUNT(*) as cnt FROM locations WHERE is_active = TRUE")['cnt']
    products_count = query_one("SELECT COUNT(*) as cnt FROM products WHERE is_active = TRUE")['cnt']
    customers_count = query_one("SELECT COUNT(*) as cnt FROM customers WHERE is_active = TRUE")['cnt']
    sales_orders_count = query_one("SELECT COUNT(*) as cnt FROM sales_orders")['cnt']

    # Fetch users for User Management tab
    users = query_all("""
        SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.branch_id,
               u.is_active, u.last_login, u.created_at, u.permissions_json,
               b.name as branch_name, b.code as branch_code, b.color as branch_color
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.id
        ORDER BY u.id ASC
    """)
    all_branches_list = query_all("SELECT id, code, name FROM branches WHERE is_active = TRUE ORDER BY id ASC")

    # Fetch pricing schemes for Pricing & Currency tab
    all_pricing_schemes = query_all("""
        SELECT ps.id, ps.name, COALESCE(ps.currency, 'US Dollar ($)') as currency, ps.is_active, ps.is_default,
               COALESCE(pp_count.cnt, 0) as product_count
        FROM pricing_schemes ps
        LEFT JOIN (
            SELECT pricing_scheme_id, COUNT(*) as cnt
            FROM product_prices
            GROUP BY pricing_scheme_id
        ) pp_count ON ps.id = pp_count.pricing_scheme_id
        ORDER BY ps.is_default DESC, ps.is_active DESC, ps.id ASC
    """)
    default_pricing_scheme = next((s for s in all_pricing_schemes if s.get('is_default')), all_pricing_schemes[0] if all_pricing_schemes else None)
    active_schemes_count = sum(1 for s in all_pricing_schemes if s.get('is_active'))

    # Fetch database backups and backup settings for Backup & Restore tab
    backups = list_backups()
    backup_settings = get_backup_settings()
    backups_count = len(backups)
    backups_total_size = sum(b.get('size_bytes', 0) for b in backups)
    backups_formatted_total_size = format_file_size(backups_total_size)
    latest_backup = backups[0] if backups else None

    active_tab = request.args.get('tab', 'tabCompany')

    return render_template('settings/general.html',
                           company=company,
                           inv_settings=inv_settings,
                           pricing_schemes=pricing_schemes,
                           all_pricing_schemes=all_pricing_schemes,
                           default_pricing_scheme=default_pricing_scheme,
                           active_schemes_count=active_schemes_count,
                           locations_count=locations_count,
                           products_count=products_count,
                           customers_count=customers_count,
                           sales_orders_count=sales_orders_count,
                           users=users,
                           all_branches_list=all_branches_list,
                           backups=backups,
                           backup_settings=backup_settings,
                           backups_count=backups_count,
                           backups_formatted_total_size=backups_formatted_total_size,
                           latest_backup=latest_backup,
                           active_tab=active_tab)

@settings_bp.route('/settings/currency/update', methods=['POST'])
def update_currency_settings():
    try:
        currency_code = (request.form.get('currency_code') or 'USD').strip()
        currency_symbol = (request.form.get('currency_symbol') or '$').strip()
        khr_exchange_rate = float(request.form.get('khr_exchange_rate') or 4080.0)
        enable_khr_total = bool(request.form.get('enable_khr_total'))

        # Decimal places
        decimal_places_price = int(request.form.get('decimal_places_price', 2) or 2)
        decimal_places_cost = int(request.form.get('decimal_places_cost', 3) or 3)
        decimal_places_markup = int(request.form.get('decimal_places_markup', 2) or 2)

        # Update companies table
        execute("""
            UPDATE companies SET
                currency_code = %s,
                currency_symbol = %s,
                decimal_places_price = %s,
                decimal_places_cost = %s,
                decimal_places_markup = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM companies LIMIT 1);
        """, (currency_code, currency_symbol, decimal_places_price, decimal_places_cost, decimal_places_markup))

        # Update invoice_settings table
        execute("""
            UPDATE invoice_settings SET
                enable_khr_total = %s,
                khr_exchange_rate = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM invoice_settings LIMIT 1);
        """, (enable_khr_total, khr_exchange_rate))

        flash("Pricing & currency preferences updated successfully!", "success")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))
    except Exception as e:
        flash(f"Error updating currency settings: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))

@settings_bp.route('/settings/pricing-schemes/create', methods=['POST'])
def create_pricing_scheme():
    try:
        name = (request.form.get('name') or '').strip()
        currency = (request.form.get('currency') or 'US Dollar ($)').strip()
        is_default = bool(request.form.get('is_default'))

        if not name:
            flash("Pricing scheme name cannot be empty.", "error")
            return redirect(url_for('settings.general_settings', tab='tabPricing'))

        if is_default:
            execute("UPDATE pricing_schemes SET is_default = FALSE")

        execute("""
            INSERT INTO pricing_schemes (name, currency, is_active, is_default)
            VALUES (%s, %s, TRUE, %s)
        """, (name, currency, is_default))

        flash(f"Pricing scheme '{name}' created successfully!", "success")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))
    except Exception as e:
        flash(f"Error creating pricing scheme: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))

@settings_bp.route('/settings/pricing-schemes/<int:id>/set-default', methods=['POST'])
def set_default_pricing_scheme(id):
    try:
        execute("UPDATE pricing_schemes SET is_default = FALSE")
        execute("UPDATE pricing_schemes SET is_default = TRUE, is_active = TRUE WHERE id = %s", (id,))
        if request.is_json:
            return jsonify({'success': True, 'message': 'Default pricing scheme updated.'})
        flash("Default pricing scheme updated successfully!", "success")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error updating default scheme: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))

@settings_bp.route('/settings/pricing-schemes/<int:id>/toggle-active', methods=['POST'])
def toggle_pricing_scheme_active(id):
    try:
        scheme = query_one("SELECT is_default, is_active FROM pricing_schemes WHERE id = %s", (id,))
        if not scheme:
            return jsonify({'success': False, 'message': 'Scheme not found.'}), 404
        if scheme['is_default'] and scheme['is_active']:
            return jsonify({'success': False, 'message': 'Cannot deactivate the default pricing scheme.'}), 400

        execute("UPDATE pricing_schemes SET is_active = NOT is_active WHERE id = %s", (id,))
        return jsonify({'success': True, 'is_active': not scheme['is_active']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@settings_bp.route('/settings/pricing-schemes/<int:id>/update', methods=['POST'])
def update_pricing_scheme(id):
    try:
        if request.is_json:
            data = request.get_json() or {}
            name = (data.get('name') or '').strip()
            currency = (data.get('currency') or 'US Dollar ($)').strip()
        else:
            name = (request.form.get('name') or '').strip()
            currency = (request.form.get('currency') or 'US Dollar ($)').strip()

        if not name:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Name cannot be empty.'}), 400
            flash("Pricing scheme name cannot be empty.", "error")
            return redirect(url_for('settings.general_settings', tab='tabPricing'))

        execute("""
            UPDATE pricing_schemes SET name = %s, currency = %s WHERE id = %s
        """, (name, currency, id))

        if request.is_json:
            return jsonify({'success': True, 'message': 'Scheme updated.'})
        flash("Pricing scheme updated successfully!", "success")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error updating scheme: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))

@settings_bp.route('/settings/pricing-schemes/<int:id>/delete', methods=['POST'])
def delete_pricing_scheme_setting(id):
    try:
        scheme = query_one("SELECT is_default FROM pricing_schemes WHERE id = %s", (id,))
        if not scheme:
            return jsonify({'success': False, 'message': 'Scheme not found.'}), 404
        if scheme['is_default']:
            return jsonify({'success': False, 'message': 'Cannot delete the default pricing scheme. Please set another scheme as default first.'}), 400

        execute("DELETE FROM product_prices WHERE pricing_scheme_id = %s", (id,))
        execute("UPDATE customers SET default_pricing_scheme_id = NULL WHERE default_pricing_scheme_id = %s", (id,))
        execute("UPDATE sales_order_lines SET pricing_scheme_id = NULL WHERE pricing_scheme_id = %s", (id,))
        execute("DELETE FROM pricing_schemes WHERE id = %s", (id,))
        msg = "Pricing scheme permanently deleted."

        if request.is_json:
            return jsonify({'success': True, 'message': msg})
        flash(msg, "success")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error deleting scheme: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabPricing'))

@settings_bp.route('/settings/update', methods=['POST'])
def update_settings():
    try:
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        address1 = request.form.get('address1', '').strip()
        city = request.form.get('city', '').strip()
        country = request.form.get('country', '').strip()
        tax_number = request.form.get('tax_number', '').strip()
        currency_code = request.form.get('currency_code', 'USD').strip()
        currency_symbol = request.form.get('currency_symbol', '$').strip()

        # Decimal settings
        decimal_places_price = int(request.form.get('decimal_places_price', 2) or 2)
        decimal_places_cost = int(request.form.get('decimal_places_cost', 3) or 3)
        decimal_places_qty = int(request.form.get('decimal_places_qty', 0) or 0)
        decimal_places_markup = int(request.form.get('decimal_places_markup', 2) or 2)
        decimal_places_total = int(request.form.get('decimal_places_total', 2) or 2)
        decimal_places_measurement = int(request.form.get('decimal_places_measurement', 2) or 2)

        execute("""
            UPDATE companies SET
                name = %s,
                phone = %s,
                email = %s,
                website = %s,
                address1 = %s,
                city = %s,
                country = %s,
                tax_number = %s,
                currency_code = %s,
                currency_symbol = %s,
                decimal_places_price = %s,
                decimal_places_cost = %s,
                decimal_places_qty = %s,
                decimal_places_markup = %s,
                decimal_places_total = %s,
                decimal_places_measurement = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM companies LIMIT 1);
        """, (
            name, phone, email, website, address1, city, country, tax_number,
            currency_code, currency_symbol,
            decimal_places_price, decimal_places_cost, decimal_places_qty,
            decimal_places_markup, decimal_places_total, decimal_places_measurement
        ))

        active_tab = request.form.get('active_tab', 'tabCompany')
        flash("Settings updated successfully!", "success")
        return redirect(url_for('settings.general_settings', tab=active_tab))

    except Exception as e:
        flash(f"Error updating settings: {e}", "error")
        return redirect(url_for('settings.general_settings'))

@settings_bp.route('/settings/app-logo', methods=['POST'])
def update_app_logo():
    try:
        action = request.form.get('action', 'upload')
        if action == 'reset':
            execute("UPDATE companies SET app_logo_url = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM companies LIMIT 1)")
            flash("✅ Restored default inFlow logo successfully! / បានប្តូរត្រឡប់ទៅ Logo ដើមជោគជ័យ!", "success")
            return redirect(url_for('settings.general_settings', tab='tabCompany'))

        if 'app_logo_file' not in request.files:
            flash("No file selected.", "warning")
            return redirect(url_for('settings.general_settings', tab='tabCompany'))

        file = request.files['app_logo_file']
        if not file or not file.filename:
            flash("Please choose an image file to upload.", "warning")
            return redirect(url_for('settings.general_settings', tab='tabCompany'))

        allowed_exts = {'png', 'jpg', 'jpeg', 'svg', 'webp', 'ico', 'gif'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed_exts:
            flash("Invalid image format. Allowed: PNG, JPG, SVG, WebP, ICO.", "error")
            return redirect(url_for('settings.general_settings', tab='tabCompany'))

        upload_dir = os.path.join('static', 'uploads', 'branding')
        os.makedirs(upload_dir, exist_ok=True)
        fname = f"app_logo_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(upload_dir, fname)
        file.save(filepath)

        app_logo_url = f"/static/uploads/branding/{fname}"
        execute("UPDATE companies SET app_logo_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM companies LIMIT 1)", (app_logo_url,))
        flash("✅ Application Logo updated successfully! / រូបសញ្ញាប្រព័ន្ធត្រូវបានផ្លាស់ប្តូរជោគជ័យ!", "success")
        return redirect(url_for('settings.general_settings', tab='tabCompany'))

    except Exception as e:
        flash(f"Error updating app logo: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabCompany'))

@settings_bp.route('/settings/items/<int:id>/decimals', methods=['POST'])
def update_item_decimals(id):
    try:
        data = request.get_json(silent=True) or request.form
        p_dec = data.get('price_decimals')
        c_dec = data.get('cost_decimals')
        q_dec = data.get('qty_decimals')

        price_decimals = int(p_dec) if p_dec is not None and str(p_dec).strip() != '' and str(p_dec).strip() != '-1' else None
        cost_decimals = int(c_dec) if c_dec is not None and str(c_dec).strip() != '' and str(c_dec).strip() != '-1' else None
        qty_decimals = int(q_dec) if q_dec is not None and str(q_dec).strip() != '' and str(q_dec).strip() != '-1' else None

        execute("""
            UPDATE products SET
                price_decimals = %s,
                cost_decimals = %s,
                qty_decimals = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (price_decimals, cost_decimals, qty_decimals, id))

        if request.is_json:
            return jsonify({'success': True, 'message': 'Item decimal precision updated successfully.'})
        flash('Item decimal precision updated successfully.', 'success')
        return redirect(url_for('settings.general_settings', tab='tabDecimals'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabDecimals'))

@settings_bp.route('/api/settings/items/decimals/batch', methods=['POST'])
def batch_update_items_decimals():
    try:
        data = request.get_json(force=True) or {}
        items = data.get('items', [])
        for item in items:
            p_id = int(item['id'])
            p_dec = item.get('price_decimals')
            c_dec = item.get('cost_decimals')
            q_dec = item.get('qty_decimals')

            price_decimals = int(p_dec) if p_dec is not None and str(p_dec).strip() != '' and str(p_dec).strip() != '-1' else None
            cost_decimals = int(c_dec) if c_dec is not None and str(c_dec).strip() != '' and str(c_dec).strip() != '-1' else None
            qty_decimals = int(q_dec) if q_dec is not None and str(q_dec).strip() != '' and str(q_dec).strip() != '-1' else None

            execute("""
                UPDATE products SET
                    price_decimals = %s,
                    cost_decimals = %s,
                    qty_decimals = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (price_decimals, cost_decimals, qty_decimals, p_id))

        return jsonify({'success': True, 'message': f'{len(items)} items updated successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@settings_bp.route('/api/settings/items/search', methods=['GET'])
def search_items_for_decimals():
    q = request.args.get('q', '').strip()
    where = "p.is_active = TRUE"
    params = []
    if q:
        where += " AND (p.name ILIKE %s OR p.sku ILIKE %s OR c.name ILIKE %s)"
        param = f"%{q}%"
        params = [param, param, param]

    items = query_all(f"""
        SELECT 
            p.id, p.sku, p.name, 
            COALESCE(c.name, 'Uncategorized') as category_name,
            p.standard_cost, p.default_price, p.uom,
            p.price_decimals, p.cost_decimals, p.qty_decimals
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE {where}
        ORDER BY p.id ASC
        LIMIT 100
    """, tuple(params))
    return jsonify({'success': True, 'items': [dict(r) for r in items]})

ALLOWED_IMG_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG_EXTENSIONS

@settings_bp.route('/settings/invoice/update', methods=['POST'])
def update_invoice_settings():
    try:
        inv = get_invoice_settings()
        
        font_family = request.form.get('font_family', 'Kantumruy Pro').strip()
        primary_color = request.form.get('primary_color', '#0284C7').strip()
        secondary_color = request.form.get('secondary_color', '#0F172A').strip()
        
        shop_name_kh = request.form.get('shop_name_kh', '').strip()
        shop_name_en = request.form.get('shop_name_en', '').strip()
        shop_address_kh = request.form.get('shop_address_kh', '').strip()
        shop_address_en = request.form.get('shop_address_en', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        vat_tin = request.form.get('vat_tin', '').strip()
        
        invoice_title_kh = request.form.get('invoice_title_kh', 'វិក្កយបត្រ').strip()
        invoice_title_en = request.form.get('invoice_title_en', 'INVOICE').strip()
        
        enable_khr_total = (request.form.get('enable_khr_total') == '1' or request.form.get('enable_khr_total') == 'on')
        khr_exchange_rate = float(request.form.get('khr_exchange_rate', 4100.00) or 4100.00)
        
        bank_name = request.form.get('bank_name', '').strip()
        account_name = request.form.get('account_name', '').strip()
        account_number = request.form.get('account_number', '').strip()
        payment_terms = request.form.get('payment_terms', 'ទូទាត់ភ្លាមៗ / Due on receipt').strip()
        
        footer_notes_kh = request.form.get('footer_notes_kh', '').strip()
        footer_notes_en = request.form.get('footer_notes_en', '').strip()
        
        show_signature = (request.form.get('show_signature') == '1' or request.form.get('show_signature') == 'on')
        show_sku = (request.form.get('show_sku') == '1' or request.form.get('show_sku') == 'on')
        show_tax = (request.form.get('show_tax') == '1' or request.form.get('show_tax') == 'on')
        unit_price_decimals = int(request.form.get('unit_price_decimals', 3) or 3)

        qr_size = int(request.form.get('qr_size', 180) or 180)
        qr_position = request.form.get('qr_position', 'left').strip()
        bank_info_size = request.form.get('bank_info_size', '8.5').strip()
        bank_info_position = request.form.get('bank_info_position', 'below_qr').strip()
        qr_offset_x = int(request.form.get('qr_offset_x', 0) or 0)
        qr_offset_y = int(request.form.get('qr_offset_y', 0) or 0)
        bank_offset_x = int(request.form.get('bank_offset_x', 0) or 0)
        bank_offset_y = int(request.form.get('bank_offset_y', 0) or 0)
        
        logo_url = inv.get('logo_url')
        qr_code_url = inv.get('qr_code_url')
        
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'invoice')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Handle logo upload
        if request.form.get('remove_logo') == '1':
            logo_url = None
        elif 'logo_file' in request.files:
            file = request.files['logo_file']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fname = f"logo_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                logo_url = f"/static/uploads/invoice/{fname}"
                
        # Handle QR code upload
        if request.form.get('remove_qr') == '1':
            qr_code_url = None
        elif 'qr_code_file' in request.files:
            file = request.files['qr_code_file']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fname = f"qr_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                qr_code_url = f"/static/uploads/invoice/{fname}"

        seller_name = request.form.get('seller_name', inv.get('seller_name') or '').strip()
        seller_signature_url = inv.get('seller_signature_url')
        if request.form.get('remove_seller_signature') == '1':
            seller_signature_url = None
        elif 'seller_signature_file' in request.files:
            file = request.files['seller_signature_file']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fname = f"seller_sig_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(upload_dir, fname)
                try:
                    file.save(save_path)
                    try:
                        os.chmod(save_path, 0o666)
                    except Exception:
                        pass
                    seller_signature_url = f"/static/uploads/invoice/{fname}"
                except Exception as save_err:
                    import base64
                    file.seek(0)
                    file_bytes = file.read()
                    mime_type = f"image/{'svg+xml' if ext == 'svg' else ('jpeg' if ext == 'jpg' else ext)}"
                    b64_str = base64.b64encode(file_bytes).decode('utf-8')
                    seller_signature_url = f"data:{mime_type};base64,{b64_str}"

        execute("""
            UPDATE invoice_settings SET
                font_family = %s,
                primary_color = %s,
                secondary_color = %s,
                logo_url = %s,
                shop_name_kh = %s,
                shop_name_en = %s,
                shop_address_kh = %s,
                shop_address_en = %s,
                phone = %s,
                email = %s,
                website = %s,
                vat_tin = %s,
                invoice_title_kh = %s,
                invoice_title_en = %s,
                enable_khr_total = %s,
                khr_exchange_rate = %s,
                qr_code_url = %s,
                bank_name = %s,
                account_name = %s,
                account_number = %s,
                payment_terms = %s,
                footer_notes_kh = %s,
                footer_notes_en = %s,
                show_signature = %s,
                show_sku = %s,
                show_tax = %s,
                qr_size = %s,
                qr_position = %s,
                bank_info_size = %s,
                bank_info_position = %s,
                qr_offset_x = %s,
                qr_offset_y = %s,
                bank_offset_x = %s,
                bank_offset_y = %s,
                seller_signature_url = %s,
                seller_name = %s,
                unit_price_decimals = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            font_family, primary_color, secondary_color, logo_url,
            shop_name_kh, shop_name_en, shop_address_kh, shop_address_en,
            phone, email, website, vat_tin,
            invoice_title_kh, invoice_title_en,
            enable_khr_total, khr_exchange_rate, qr_code_url,
            bank_name, account_name, account_number, payment_terms,
            footer_notes_kh, footer_notes_en,
            show_signature, show_sku, show_tax,
            qr_size, qr_position, bank_info_size, bank_info_position,
            qr_offset_x, qr_offset_y, bank_offset_x, bank_offset_y,
            seller_signature_url, seller_name,
            unit_price_decimals,
            inv['id']
        ))

        # Also update companies table so company info stays in sync
        execute("""
            UPDATE companies SET
                name = COALESCE(NULLIF(%s, ''), name),
                phone = COALESCE(NULLIF(%s, ''), phone),
                email = COALESCE(NULLIF(%s, ''), email),
                website = COALESCE(NULLIF(%s, ''), website),
                address1 = COALESCE(NULLIF(%s, ''), address1),
                tax_number = COALESCE(NULLIF(%s, ''), tax_number),
                logo_url = COALESCE(%s, logo_url),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM companies LIMIT 1);
        """, (
            shop_name_en, phone, email, website, shop_address_en, vat_tin, logo_url
        ))

        flash("Invoice customization saved successfully!", "success")
        return redirect(url_for('settings.general_settings', tab='tabInvoice'))
    except Exception as e:
        flash(f"Error saving invoice settings: {e}", "error")
        return redirect(url_for('settings.general_settings', tab='tabInvoice'))

@settings_bp.route('/api/settings/invoice/layout', methods=['POST'])
def update_invoice_layout_api():
    try:
        data = request.get_json() or {}
        inv = get_invoice_settings()
        
        qr_size = int(data.get('qr_size', 180) or 180)
        qr_position = str(data.get('qr_position', 'left') or 'left').strip()
        bank_info_size = str(data.get('bank_info_size', '8.5') or '8.5').strip()
        bank_info_position = str(data.get('bank_info_position', 'below_qr') or 'below_qr').strip()
        qr_offset_x = int(data.get('qr_offset_x', 0) or 0)
        qr_offset_y = int(data.get('qr_offset_y', 0) or 0)
        bank_offset_x = int(data.get('bank_offset_x', 0) or 0)
        bank_offset_y = int(data.get('bank_offset_y', 0) or 0)
        
        execute("""
            UPDATE invoice_settings SET
                qr_size = %s,
                qr_position = %s,
                bank_info_size = %s,
                bank_info_position = %s,
                qr_offset_x = %s,
                qr_offset_y = %s,
                bank_offset_x = %s,
                bank_offset_y = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            qr_size, qr_position, bank_info_size, bank_info_position,
            qr_offset_x, qr_offset_y, bank_offset_x, bank_offset_y,
            inv['id']
        ))
        return jsonify({'success': True, 'message': 'Invoice layout updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/settings/invoice/preview')
def preview_invoice():
    use_sample = (request.args.get('sample') == '1')
    order = None
    if not use_sample:
        order = query_one("""
            SELECT 
                so.*,
                c.name as customer_name,
                c.contact_name as customer_contact,
                c.phone as customer_phone,
                c.email as customer_email,
                c.address1 as customer_address,
                c.city as customer_city,
                l.name as location_name
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            LEFT JOIN locations l ON so.location_id = l.id
            ORDER BY so.id DESC
            LIMIT 1
        """)
    
    if order:
        lines = query_all("""
            SELECT 
                sol.*,
                COALESCE(p.name, 'Item') as product_name,
                p.sku as product_sku,
                p.barcode as product_barcode,
                COALESCE(sol.uom, p.uom, 'ea') as product_uom,
                COALESCE(NULLIF(sol.description, ''), NULLIF(p.description, ''), '') as line_description
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            WHERE sol.sales_order_id = %s
            ORDER BY sol.line_num ASC
        """, (order['id'],))
    else:
        import datetime
        order = {
            'order_number': 'INV-2026-0089',
            'order_date': datetime.date.today(),
            'due_date': datetime.date.today() + datetime.timedelta(days=7),
            'customer_name': 'ក្រុមហ៊ុន សុខា ត្រេឌីង ខូអិលធីឌី (Sokha Trading Co., Ltd.)',
            'customer_contact': 'លោក សុខា / Mr. Sokha',
            'customer_phone': '+855 12 888 777',
            'customer_email': 'procurement@sokhatrading.com.kh',
            'customer_address': '#88, ផ្លូវ 1986, សង្កាត់ភ្នំពេញថ្មី, ខណ្ឌសែនសុខ, ភ្នំពេញ',
            'customer_tax_number': 'K002-987654321',
            'salesperson': 'Mr. Dara (Sales)',
            'location_name': 'ឃ្លាំងកណ្តាល (Main Central Warehouse)',
            'status': 'Invoiced',
            'payment_terms': 'Due on Receipt',
            'subtotal': 1350.00,
            'discount_amount': 50.00,
            'tax_amount': 130.00,
            'shipping_fee': 10.00,
            'total_amount': 1440.00,
            'paid_amount': 1000.00,
            'balance_due': 440.00,
            'notes': 'ដឹកជញ្ជូនរហ័សដល់ទីតាំងអតិថិជន។ សូមអរគុណ!'
        }
        lines = [
            {
                'line_num': 1,
                'product_name': 'កំប៉ុងដែកអ៊ីណុក Premium Chef Wok 32cm (Stainless Steel)',
                'product_sku': 'WOK-SS-32',
                'quantity': 20,
                'quantity_display': 20,
                'uom': 'pcs',
                'unit_price': 35.00,
                'discount_percent': 0,
                'subtotal': 700.00
            },
            {
                'line_num': 2,
                'product_name': 'ឈុតកាំបិតចង្ក្រានបាយបច្ចេកវិទ្យាអាល្លឺម៉ង់ (Kitchen Chef Knife Set)',
                'product_sku': 'KNIFE-SET-08',
                'quantity': 10,
                'quantity_display': 10,
                'uom': 'set',
                'unit_price': 45.00,
                'discount_percent': 5,
                'subtotal': 427.50
            },
            {
                'line_num': 3,
                'product_name': 'ឆ្នាំងអ៊ុតចំហាយទឹកកម្លាំងខ្ពស់ (Electric Steam Cooker 5L)',
                'product_sku': 'STEAM-CK-05',
                'quantity': 5,
                'quantity_display': 5,
                'uom': 'unit',
                'unit_price': 44.50,
                'discount_percent': 0,
                'subtotal': 222.50
            }
        ]

    company = query_one("SELECT * FROM companies LIMIT 1")
    inv_settings = get_invoice_settings()
    
    rate = float(inv_settings.get('khr_exchange_rate') or 4100.0)
    total_usd = float(order.get('total_amount') or 0.0)
    paid_usd = float(order.get('paid_amount') or 0.0)
    balance_usd = float(order.get('balance_due') or 0.0)
    
    total_khr = int(round(total_usd * rate, -2))
    paid_khr = int(round(paid_usd * rate, -2))
    balance_khr = int(round(balance_usd * rate, -2))

    return render_template('sales/invoice_print.html',
                           order=order,
                           lines=lines,
                           company=company,
                           inv_settings=inv_settings,
                           doc_type='invoice',
                           khr_rate=rate,
                           total_khr=total_khr,
                           paid_khr=paid_khr,
                           balance_khr=balance_khr)

@settings_bp.route('/api/set-language/<lang>', methods=['GET', 'POST'])
def set_app_language(lang):
    if lang not in ['en', 'km']:
        lang = 'en'
    session['app_lang'] = lang
    resp = jsonify({'success': True, 'lang': lang})
    resp.set_cookie('inflow_lang', lang, max_age=31536000, path='/')
    return resp

# =========================================================================
# Database Backup, Restore & Google Drive Management Endpoints
# =========================================================================

@settings_bp.route('/settings/backup/create', methods=['POST'])
def create_backup_action():
    try:
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
        data = request.get_json(silent=True) if request.is_json else request.form
        
        save_gdrive_val = data.get('save_to_gdrive') if data else None
        save_to_gdrive = None
        if save_gdrive_val is not None:
            save_to_gdrive = str(save_gdrive_val).lower() in ('1', 'true', 'on', 'yes')
            
        note = (data.get('note') or '').strip() if data else ''
        
        res = create_backup(backup_type='manual', note=note, save_to_gdrive=save_to_gdrive)
        
        if res.get('success'):
            msg = f"✅ Database backup created: {res['filename']} ({res['formatted_size']})"
            if res.get('gdrive_saved'):
                gdrive_res = res.get('gdrive_result', {})
                if gdrive_res.get('success'):
                    msg += " & automatically saved to Google Drive!"
                else:
                    msg += f" (Google Drive note: {gdrive_res.get('error', 'Sync pending')})"
            if is_ajax:
                return jsonify({'success': True, 'message': msg, 'backup': res})
            flash(msg, 'success')
        else:
            err_msg = res.get('error', 'Failed to generate database backup.')
            if is_ajax:
                return jsonify({'success': False, 'message': err_msg}), 400
            flash(f"❌ Backup failed: {err_msg}", 'error')
            
        return redirect(url_for('settings.general_settings', tab='tabBackup'))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error creating backup: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/restore', methods=['POST'])
def restore_backup_action():
    try:
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
        b_dir = get_backup_dir()
        
        source = request.form.get('source', 'existing')
        safety_val = request.form.get('create_safety_backup', 'true')
        create_safety = str(safety_val).lower() in ('1', 'true', 'on', 'yes')
        
        target_filepath = None
        
        if source == 'upload':
            if 'backup_file' not in request.files:
                err_msg = "Please select a .sql database backup file to upload."
                if is_ajax: return jsonify({'success': False, 'message': err_msg}), 400
                flash(err_msg, 'error')
                return redirect(url_for('settings.general_settings', tab='tabBackup'))
                
            file = request.files['backup_file']
            if not file or not file.filename:
                err_msg = "No file selected."
                if is_ajax: return jsonify({'success': False, 'message': err_msg}), 400
                flash(err_msg, 'error')
                return redirect(url_for('settings.general_settings', tab='tabBackup'))
                
            fname_clean = secure_filename(file.filename)
            ext = fname_clean.rsplit('.', 1)[-1].lower() if '.' in fname_clean else ''
            if ext not in ('sql', 'sgl'):
                err_msg = "Invalid file type. Only PostgreSQL .sql backup files are accepted."
                if is_ajax: return jsonify({'success': False, 'message': err_msg}), 400
                flash(err_msg, 'error')
                return redirect(url_for('settings.general_settings', tab='tabBackup'))
                
            now_str = datetime.now().strftime('%Y-%m-%d_%H%M%S')
            saved_name = f"uploaded_restore_{now_str}_{fname_clean}"
            if not saved_name.endswith('.sql'):
                saved_name = saved_name.rsplit('.', 1)[0] + '.sql'
            target_filepath = os.path.join(b_dir, saved_name)
            file.save(target_filepath)
        else:
            filename = secure_filename(request.form.get('filename', '').strip())
            if not filename:
                err_msg = "Please select a backup file to restore."
                if is_ajax: return jsonify({'success': False, 'message': err_msg}), 400
                flash(err_msg, 'error')
                return redirect(url_for('settings.general_settings', tab='tabBackup'))
                
            target_filepath = os.path.join(b_dir, filename)
            if not os.path.exists(target_filepath):
                err_msg = f"Backup file {filename} does not exist on disk."
                if is_ajax: return jsonify({'success': False, 'message': err_msg}), 404
                flash(err_msg, 'error')
                return redirect(url_for('settings.general_settings', tab='tabBackup'))
                
        res = restore_backup(target_filepath, create_safety_backup=create_safety)
        
        if res.get('success'):
            msg = "🎉 Database restored successfully!"
            if res.get('safety_backup'):
                msg += f" (Safety snapshot created: {res['safety_backup']})"
            if is_ajax:
                return jsonify({'success': True, 'message': msg, 'result': res})
            flash(msg, 'success')
        else:
            err = res.get('error', 'Restoration failed.')
            if is_ajax:
                return jsonify({'success': False, 'message': err}), 500
            flash(f"❌ Restore failed: {err}", 'error')
            
        return redirect(url_for('settings.general_settings', tab='tabBackup'))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error restoring backup: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/download/<path:filename>', methods=['GET'])
def download_backup_action(filename):
    try:
        fname = secure_filename(filename)
        b_dir = get_backup_dir()
        fpath = os.path.abspath(os.path.join(b_dir, fname))
        
        # Security check: must reside inside backup directory
        if not fpath.startswith(os.path.abspath(b_dir)) or not os.path.exists(fpath):
            flash(f"Backup file '{fname}' not found.", 'error')
            return redirect(url_for('settings.general_settings', tab='tabBackup'))
            
        return send_file(
            fpath,
            as_attachment=True,
            download_name=fname,
            mimetype='application/sql'
        )
    except Exception as e:
        flash(f"Error downloading backup: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/delete/<path:filename>', methods=['POST'])
def delete_backup_action(filename):
    try:
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
        fname = secure_filename(filename)
        b_dir = get_backup_dir()
        fpath = os.path.abspath(os.path.join(b_dir, fname))
        
        if not fpath.startswith(os.path.abspath(b_dir)) or not os.path.exists(fpath):
            msg = f"File '{fname}' not found."
            if is_ajax: return jsonify({'success': False, 'message': msg}), 404
            flash(msg, 'warning')
            return redirect(url_for('settings.general_settings', tab='tabBackup'))
            
        os.remove(fpath)
        try:
            execute("DELETE FROM backup_logs WHERE filename = %s", (fname,))
        except Exception:
            pass
            
        msg = f"🗑️ Backup '{fname}' deleted successfully."
        if is_ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error deleting backup: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/sync-gdrive/<path:filename>', methods=['POST'])
def sync_gdrive_action(filename):
    try:
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
        fname = secure_filename(filename)
        b_dir = get_backup_dir()
        fpath = os.path.abspath(os.path.join(b_dir, fname))
        
        if not fpath.startswith(os.path.abspath(b_dir)) or not os.path.exists(fpath):
            msg = f"Backup file '{fname}' not found."
            if is_ajax: return jsonify({'success': False, 'message': msg}), 404
            flash(msg, 'error')
            return redirect(url_for('settings.general_settings', tab='tabBackup'))
            
        res = save_backup_to_gdrive(fpath, fname)
        if res.get('success'):
            msg = f"☁️ Backup '{fname}' saved to Google Drive successfully! {res.get('message', '')}"
            if is_ajax: return jsonify({'success': True, 'message': msg, 'result': res})
            flash(msg, 'success')
        else:
            err = res.get('error', 'Google Drive sync failed.')
            if is_ajax: return jsonify({'success': False, 'message': err}), 500
            flash(f"❌ Google Drive sync failed: {err}", 'error')
            
        return redirect(url_for('settings.general_settings', tab='tabBackup'))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error saving to Google Drive: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/config', methods=['POST'])
def save_backup_config_action():
    try:
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'
        data = request.get_json(silent=True) if request.is_json else request.form
        
        auto_backup_enabled = str(data.get('auto_backup_enabled', '')).lower() in ('1', 'true', 'on', 'yes')
        auto_save_gdrive = str(data.get('auto_save_gdrive', '')).lower() in ('1', 'true', 'on', 'yes')
        auto_backup_frequency = data.get('auto_backup_frequency', 'daily')
        auto_backup_time = data.get('auto_backup_time', '23:00')
        gdrive_mode = data.get('gdrive_mode', 'local_sync')
        gdrive_local_path = data.get('gdrive_local_path', r'G:\My Drive\inFlow_Backups')
        gdrive_folder_id = data.get('gdrive_folder_id', '')
        retention_count = int(data.get('retention_count', 15) or 15)
        
        # Check if service account JSON file was uploaded
        gdrive_service_account_json = data.get('gdrive_service_account_json', '')
        if 'sa_file' in request.files:
            sa_f = request.files['sa_file']
            if sa_f and sa_f.filename:
                gdrive_service_account_json = sa_f.read().decode('utf-8', errors='ignore')
                
        save_backup_settings({
            'auto_backup_enabled': auto_backup_enabled,
            'auto_backup_frequency': auto_backup_frequency,
            'auto_backup_time': auto_backup_time,
            'auto_save_gdrive': auto_save_gdrive,
            'gdrive_mode': gdrive_mode,
            'gdrive_local_path': gdrive_local_path,
            'gdrive_folder_id': gdrive_folder_id,
            'gdrive_service_account_json': gdrive_service_account_json,
            'retention_count': retention_count
        })
        
        msg = "✅ Backup & Google Drive settings saved successfully!"
        if is_ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))
    except Exception as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Error saving backup settings: {e}", 'error')
        return redirect(url_for('settings.general_settings', tab='tabBackup'))

@settings_bp.route('/settings/backup/test-gdrive', methods=['POST'])
def test_gdrive_config_action():
    try:
        data = request.get_json(silent=True) or request.form
        mode = data.get('gdrive_mode')
        local_path = data.get('gdrive_local_path')
        sa_json = data.get('gdrive_service_account_json')
        folder_id = data.get('gdrive_folder_id')
        
        res = test_gdrive_config(mode=mode, local_path=local_path, sa_json=sa_json, folder_id=folder_id)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

