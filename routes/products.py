import os
import re
import time
import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from database import query_one, query_all, execute, execute_returning_id, get_db_cursor, get_next_sequence_val

products_bp = Blueprint('products', __name__)

def safe_eval_math(expr):
    """Safely evaluate arithmetic expressions like Google Sheets (e.g. 10+2.5, =0.10+0.02, 12/100, 36/300)"""
    if expr is None:
        return 0.0
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr).strip()
    if s.startswith('='):
        s = s[1:].strip()
    s = s.replace('$', '').replace(',', '').strip()
    if not s:
        return 0.0
    if re.match(r'^[\d\s\+\-\*\/\%\(\)\.]+$', s):
        try:
            val = eval(s, {"__builtins__": None}, {})
            return float(val)
        except Exception:
            pass
    try:
        return float(s)
    except Exception:
        return 0.0

def _split_khmer_english(name, sku=''):
    name = (name or '').strip()
    sku = (sku or '').strip()
    if not name:
        return {'khmer': 'ប្រអប់បាយជ័រ', 'english': sku or 'Product'}
    if ' / ' in name:
        parts = name.split(' / ', 1)
        return {'khmer': parts[0].strip(), 'english': parts[1].strip()}
    elif '/' in name:
        parts = name.split('/', 1)
        return {'khmer': parts[0].strip(), 'english': parts[1].strip()}
    return {'khmer': name, 'english': sku if sku and sku != name else ''}

CATEGORY_COLOR_MAP = {
    'rice box': '#00A3E0',         # Cyan (Screenshot Match)
    'rec. box': '#4F46E5',         # Indigo
    'food box': '#DC2626',         # Crimson Red
    'paper fodo box': '#B45309',   # Warm Amber / Kraft Brown
    'plastic': '#1E3A8A',          # Deep Navy
    'bowl': '#0284C7',             # Pacific Sky Blue
    'paper bowl': '#0891B2',       # Ocean Teal
    'cup': '#2563EB',              # Royal Blue
    'small cup': '#059669',        # Emerald Green
    'paper cup': '#EA580C',        # Vibrant Orange
    'bottle': '#0D9488',           # Teal
    'cake box': '#E11D48',         # Rose
    'paper cake box': '#DB2777',   # Pink
    'paper bag': '#CA8A04',        # Kraft Ochre
    'folk/spoon': '#7C3AED',       # Purple
    'delivery': '#D97706',         # Amber
    'printing': '#C026D3',         # Fuchsia
    'eco': '#16A34A',              # Green
    'bagasse': '#65A30D',          # Olive Lime
    'aluminium box': '#475569',    # Slate Silver
    'pans': '#6D28D9'              # Deep Violet
}

from routes.auth import user_can_edit_prices, user_can_view_costs, user_can_adjust_stock

def _build_price_card_data(product, price_tiers, can_view_costs=None):
    if can_view_costs is None:
        can_view_costs = user_can_view_costs()
    names = _split_khmer_english(product.get('name'), product.get('sku'))
    
    # Dimensions (default 21cm x 21cm x 4cm matching reference)
    l_val = product.get('length')
    w_val = product.get('width')
    h_val = product.get('height')
    length = float(l_val) if l_val is not None and float(l_val) > 0 else 21
    width = float(w_val) if w_val is not None and float(w_val) > 0 else 21
    height = float(h_val) if h_val is not None and float(h_val) > 0 else 4
    dim_str = f"{length:g}cm x {width:g}cm x {height:g}cm"
    
    # Packaging specs
    packs_per_case = float(product.get('packs_per_case') or 0)
    pcs_per_pack = float(product.get('pcs_per_pack') or 0)
    sales_uom_ratio_std = float(product.get('sales_uom_ratio_std') or 0)
    
    # Total pcs per case / carton
    if sales_uom_ratio_std > 1:
        pcs_per_case = sales_uom_ratio_std
        if pcs_per_pack <= 0:
            pcs_per_pack = 50.0
        # Automatically calculate number pack per case = number pcs per case / pcs per pack
        packs_per_case = round(pcs_per_case / pcs_per_pack, 2)
    elif packs_per_case > 0 and pcs_per_pack > 0:
        pcs_per_case = packs_per_case * pcs_per_pack
    else:
        pcs_per_case = 400.0
        packs_per_case = 8.0
        pcs_per_pack = 50.0

    card_unit = product.get('price_card_unit') or 'ប្រអប់'
    auto_detail_lines = [
        f"ទំហំ: {dim_str}",
        f"1 កេស មាន {packs_per_case:g} ដុំ",
        f"1 ដុំ មាន {pcs_per_pack:g} {card_unit}",
        f"{pcs_per_case:g} {card_unit}/1កេស",
        f"({pcs_per_case:g} PCS/ Carton)"
    ]
    auto_detail_text = "\n".join(auto_detail_lines)
    is_custom_detail = bool(product.get('price_card_is_custom_detail'))
    custom_detail = product.get('price_card_custom_detail') or ''
    
    # Default tier amounts:
    # Tier 1 = 100 pcs
    # Tier 2 = 1 case in pcs (e.g. 400 pcs)
    # Tier 3 = 2 cases in pcs (e.g. 800 pcs)
    case_pcs_int = int(round(pcs_per_case)) if pcs_per_case > 0 else 400
    default_tier_1 = 100
    default_tier_2 = case_pcs_int
    default_tier_3 = case_pcs_int * 2
    
    saved_q1 = product.get('tier_qty_1')
    saved_q2 = product.get('tier_qty_2')
    saved_q3 = product.get('tier_qty_3')
    
    tier_qty_1 = int(saved_q1) if (saved_q1 is not None and int(saved_q1) > 0) else default_tier_1
    tier_qty_2 = int(saved_q2) if (saved_q2 is not None and int(saved_q2) > 0) else default_tier_2
    tier_qty_3 = int(saved_q3) if (saved_q3 is not None and int(saved_q3) > 0) else default_tier_3
    
    # Extract Retail 1, Retail 2, Retail 3 prices
    r1_price = None
    r2_price = None
    r3_price = None
    for pt in price_tiers:
        s_name = (pt.get('scheme_name') or '').lower()
        sid = pt.get('pricing_scheme_id')
        p = float(pt.get('unit_price') or 0)
        if 'retail 1' in s_name or sid == 100:
            r1_price = p
        elif 'retail 2' in s_name or sid == 101:
            r2_price = p
        elif 'retail 3' in s_name or sid == 102:
            r3_price = p
            
    # Calculate Unit Price ($/pcs): Retail price divided by number of pcs per case
    if r1_price is not None and r1_price > 0:
        if r1_price > 2 and pcs_per_case > 1:
            u_price_1 = r1_price / pcs_per_case
        else:
            u_price_1 = r1_price
    else:
        u_price_1 = 0.150
        
    if r2_price is not None and r2_price > 0:
        if r2_price > 2 and pcs_per_case > 1:
            u_price_2 = r2_price / pcs_per_case
        else:
            u_price_2 = r2_price
    else:
        u_price_2 = 0.140
        
    if r3_price is not None and r3_price > 0:
        if r3_price > 2 and pcs_per_case > 1:
            u_price_3 = r3_price / pcs_per_case
        else:
            u_price_3 = r3_price
    else:
        u_price_3 = 0.135
        
    # Total price calculation (or manual override)
    if product.get('tier_price_1') is not None and float(product.get('tier_price_1')) > 0:
        tot_price_1 = float(product.get('tier_price_1'))
        u_price_1 = tot_price_1 / tier_qty_1 if tier_qty_1 > 0 else u_price_1
    else:
        tot_price_1 = round(tier_qty_1 * u_price_1, 2)
        
    if product.get('tier_price_2') is not None and float(product.get('tier_price_2')) > 0:
        tot_price_2 = float(product.get('tier_price_2'))
        u_price_2 = tot_price_2 / tier_qty_2 if tier_qty_2 > 0 else u_price_2
    else:
        tot_price_2 = round(tier_qty_2 * u_price_2, 2)
        
    if product.get('tier_price_3') is not None and float(product.get('tier_price_3')) > 0:
        tot_price_3 = float(product.get('tier_price_3'))
        u_price_3 = tot_price_3 / tier_qty_3 if tier_qty_3 > 0 else u_price_3
    else:
        tot_price_3 = round(tier_qty_3 * u_price_3, 2)
        
    if can_view_costs:
        # Internal Costing and Profit Analysis (Screenshot 2)
        raw_cost = float(product.get('standard_cost') or product.get('average_cost') or 0.0)
        unit_cost = raw_cost if raw_cost > 0 else 0.12
        
        tot_cost_1 = unit_cost * tier_qty_1
        profit_dlr_1 = tot_price_1 - tot_cost_1
        profit_pct_1 = (profit_dlr_1 / tot_cost_1 * 100) if tot_cost_1 > 0 else 0.0
        
        tot_cost_2 = unit_cost * tier_qty_2
        profit_dlr_2 = tot_price_2 - tot_cost_2
        profit_pct_2 = (profit_dlr_2 / tot_cost_2 * 100) if tot_cost_2 > 0 else 0.0
        
        tot_cost_3 = unit_cost * tier_qty_3
        profit_dlr_3 = tot_price_3 - tot_cost_3
        profit_pct_3 = (profit_dlr_3 / tot_cost_3 * 100) if tot_cost_3 > 0 else 0.0
    else:
        unit_cost = 0.0
        tot_cost_1 = 0.0
        tot_cost_2 = 0.0
        tot_cost_3 = 0.0
        profit_dlr_1 = 0.0
        profit_dlr_2 = 0.0
        profit_dlr_3 = 0.0
        profit_pct_1 = 0
        profit_pct_2 = 0
        profit_pct_3 = 0

    # Determine category color
    cat_color = product.get('category_color')
    if not cat_color and product.get('category_id'):
        c_row = query_one("SELECT color FROM categories WHERE id = %s", (product['category_id'],))
        if c_row and c_row.get('color'):
            cat_color = c_row['color']
            
    if not cat_color:
        c_name = (product.get('category_name') or '').strip().lower()
        cat_color = CATEGORY_COLOR_MAP.get(c_name, '#00A3E0')

    # Assign color: Category color takes precedence unless user saved a non-default custom color
    saved_color = product.get('price_card_color')
    if not saved_color or saved_color in ('#00A3E0', '#0F172A', ''):
        final_color = cat_color
    else:
        final_color = saved_color
    
    return {
        'khmer_name': names['khmer'],
        'english_name': names['english'],
        'length': length,
        'width': width,
        'height': height,
        'dim_str': dim_str,
        'category_name': product.get('category_name') or 'ប្រអប់បាយ (Food Container)',
        'packs_per_case': packs_per_case,
        'pcs_per_pack': pcs_per_pack,
        'pcs_per_case': pcs_per_case,
        'tier_qty_1': tier_qty_1,
        'tier_qty_2': tier_qty_2,
        'tier_qty_3': tier_qty_3,
        'tot_price_1': tot_price_1,
        'tot_price_2': tot_price_2,
        'tot_price_3': tot_price_3,
        'u_price_1': u_price_1,
        'u_price_2': u_price_2,
        'u_price_3': u_price_3,
        'unit_cost': unit_cost,
        'tot_cost_1': tot_cost_1,
        'tot_cost_2': tot_cost_2,
        'tot_cost_3': tot_cost_3,
        'profit_dlr_1': profit_dlr_1,
        'profit_dlr_2': profit_dlr_2,
        'profit_dlr_3': profit_dlr_3,
        'profit_pct_1': int(profit_pct_1 + 0.5),
        'profit_pct_2': int(profit_pct_2 + 0.5),
        'profit_pct_3': int(profit_pct_3 + 0.5),
        'card_color': final_color,
        'card_font': product.get('price_card_font') or 'Kantumruy Pro',
        'card_unit': card_unit,
        'is_custom_detail': is_custom_detail,
        'custom_detail': custom_detail,
        'auto_detail_text': auto_detail_text,
        'notes': product.get('price_card_notes') or '',
        'price_table_style': product.get('price_table_style') or product.get('price_card_style') or 'classic',
        'can_view_costs': can_view_costs
    }

def recalc_product_bom_cost(product_id):
    """
    Recalculates the standard_cost of a combined product by summing the
    cost of all component items in product_boms:
    SUM(pb.quantity * COALESCE(p.standard_cost, pb.cost, 0))
    Updates products.standard_cost and products.combine_type in the DB.
    Returns the new standard_cost (float).
    """
    boms = query_all("""
        SELECT pb.id, pb.quantity, COALESCE(p.standard_cost, pb.cost, 0) as unit_cost
        FROM product_boms pb
        LEFT JOIN products p ON pb.component_product_id = p.id
        WHERE pb.product_id = %s
    """, (product_id,))
    
    if boms:
        total_cost = sum(float(b['quantity'] or 1.0) * float(b['unit_cost'] or 0.0) for b in boms)
        total_cost = round(total_cost, 4)
        execute("""
            UPDATE product_boms pb
            SET cost = COALESCE(p.standard_cost, 0)
            FROM products p
            WHERE pb.component_product_id = p.id AND pb.product_id = %s
        """, (product_id,))
        execute("""
            UPDATE products 
            SET standard_cost = %s, average_cost = %s, combine_type = 'multi', cost_formula = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (total_cost, total_cost, product_id))
        # Propagate change to any parent kits that might contain this combined product
        update_parent_boms_cost(product_id)
        return total_cost
    else:
        execute("UPDATE products SET combine_type = 'single', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (product_id,))
        p = query_one("SELECT standard_cost, average_cost FROM products WHERE id = %s", (product_id,))
        return float(p['standard_cost'] or p['average_cost'] or 0.0) if p else 0.0

def update_parent_boms_cost(component_product_id, visited=None):
    """
    Whenever a component product's cost changes, auto-recalculate
    all parent combined kit products that use this component!
    """
    if visited is None:
        visited = set()
    if component_product_id in visited:
        return
    visited.add(component_product_id)
    try:
        parents = query_all("""
            SELECT DISTINCT product_id 
            FROM product_boms 
            WHERE component_product_id = %s
        """, (component_product_id,))
        for r in parents:
            parent_id = r['product_id']
            # Directly recalculate the parent's BOM cost
            boms = query_all("""
                SELECT pb.id, pb.quantity, COALESCE(p.standard_cost, pb.cost, 0) as unit_cost
                FROM product_boms pb
                LEFT JOIN products p ON pb.component_product_id = p.id
                WHERE pb.product_id = %s
            """, (parent_id,))
            if boms:
                p_cost = round(sum(float(b['quantity'] or 1.0) * float(b['unit_cost'] or 0.0) for b in boms), 4)
                execute("""
                    UPDATE product_boms pb
                    SET cost = COALESCE(p.standard_cost, 0)
                    FROM products p
                    WHERE pb.component_product_id = p.id AND pb.product_id = %s
                """, (parent_id,))
                execute("""
                    UPDATE products 
                    SET standard_cost = %s, average_cost = %s, combine_type = 'multi', cost_formula = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (p_cost, p_cost, parent_id))
                update_parent_boms_cost(parent_id, visited)
    except Exception as e:
        logger.error(f"Error in update_parent_boms_cost for component {component_product_id}: {e}")

def _get_catalog_sidebar_products():
    return query_all("""
        SELECT 
            p.id, p.sku, p.name, p.image_url, p.is_active, p.category_id,
            p.combine_type,
            COALESCE(bom_tbl.bom_count, 0) as bom_count,
            COALESCE(c.name, '') as category_name,
            COALESCE(c.color, '#00A3E0') as category_color,
            COALESCE(SUM(i.quantity), 0) as total_qty,
            COALESCE(s.total_sold_qty, 0) as total_sold_qty,
            COALESCE(s.order_count, 0) as order_count,
            GREATEST(
                COALESCE(p.default_price, 0),
                COALESCE(p.tier_price_1, 0),
                COALESCE(pr.max_price, 0)
            ) as price
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i ON p.id = i.product_id
        LEFT JOIN (
            SELECT 
                sol.product_id, 
                SUM(sol.quantity) as total_sold_qty, 
                COUNT(DISTINCT sol.sales_order_id) as order_count
            FROM sales_order_lines sol
            GROUP BY sol.product_id
        ) s ON p.id = s.product_id
        LEFT JOIN (
            SELECT 
                product_id, 
                MAX(unit_price) as max_price
            FROM product_prices
            GROUP BY product_id
        ) pr ON p.id = pr.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) as bom_count
            FROM product_boms
            GROUP BY product_id
        ) bom_tbl ON p.id = bom_tbl.product_id
        GROUP BY p.id, p.combine_type, bom_tbl.bom_count, c.name, c.color, s.total_sold_qty, s.order_count, pr.max_price
        ORDER BY p.name ASC, p.id ASC
    """)

def _get_product_detail_bundle(product_id):
    # Global default price table style setting
    global_setting = query_one("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style'")
    global_price_table_style = (global_setting['setting_value'] if global_setting and global_setting.get('setting_value') else 'classic').lower()
    if global_price_table_style not in ('classic', 'modern'):
        global_price_table_style = 'classic'

    product = query_one("""
        SELECT 
            p.*, 
            c.name as category_name,
            COALESCE(c.color, '#00A3E0') as category_color,
            COALESCE(c.price_table_style, 'classic') as category_price_table_style,
            COALESCE(p.price_card_style, c.price_table_style, %s, 'classic') as price_table_style,
            l.name as default_location_name,
            COALESCE(inv.total_qty, 0) as total_qty,
            COALESCE(inv.reserved_qty, 0) as reserved_qty
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN locations l ON p.default_location_id = l.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty, SUM(reserved_quantity) as reserved_qty
            FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE p.id = %s
    """, (global_price_table_style, product_id))

    if not product:
        return None

    product['default_price'] = float(product.get('default_price') or 0.0)
    product['standard_cost'] = float(product.get('standard_cost') or 0.0)
    product['average_cost'] = float(product.get('average_cost') or 0.0)

    # Purchases UOM always equal to Sales UOM
    product['purchasing_uom'] = product.get('sales_uom') or 'cases'
    product['purchasing_uom_ratio'] = float(product.get('sales_uom_ratio') or 1.0)
    product['purchasing_uom_ratio_std'] = float(product.get('sales_uom_ratio_std') or 200.0)

    # Number pack per case should be automatically calculated: pcs per case / pcs per pack
    ratio_std = float(product.get('sales_uom_ratio_std') or 0.0)
    pcs_pack = float(product.get('pcs_per_pack') or 0.0)
    if ratio_std > 0 and pcs_pack > 0:
        product['packs_per_case'] = round(ratio_std / pcs_pack, 2)

    if product.get('cost_formula') in ('None', 'null', 'undefined', ''):
        product['cost_formula'] = None

    # Inventory distribution per location (exclude special system locations)
    location_stocks = query_all("""
        SELECT 
            l.id as location_id, l.name as location_name,
            COALESCE(i.sublocation, '') as sublocation,
            COALESCE(i.quantity, 0) as quantity,
            COALESCE(i.reserved_quantity, 0) as reserved_quantity
        FROM locations l
        LEFT JOIN inventory i ON l.id = i.location_id AND i.product_id = %s
        WHERE l.is_active = TRUE AND l.name NOT LIKE '<%%>'
        ORDER BY l.is_default DESC, l.name ASC
    """, (product_id,))

    # Price tiers (only schemes assigned to this product, enabling add/delete)
    price_tiers = query_all("""
        SELECT 
            ps.id as pricing_scheme_id, ps.name as scheme_name,
            pp.unit_price
        FROM product_prices pp
        JOIN pricing_schemes ps ON pp.pricing_scheme_id = ps.id
        WHERE pp.product_id = %s AND ps.is_active = TRUE
        ORDER BY ps.is_default DESC, ps.id ASC
    """, (product_id,))

    # Auto seed default scheme if no prices set yet and default_price > 0
    if not price_tiers and float(product.get('default_price') or 0.0) > 0:
        default_scheme = query_one("SELECT id, name FROM pricing_schemes WHERE is_default = TRUE AND is_active = TRUE LIMIT 1") or query_one("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id ASC LIMIT 1")
        if default_scheme:
            init_price = float(product.get('default_price') or 0.0)
            execute("""
                INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                VALUES (%s, %s, %s)
                ON CONFLICT (product_id, pricing_scheme_id) DO NOTHING
            """, (product_id, default_scheme['id'], init_price))
            price_tiers = query_all("""
                SELECT 
                    ps.id as pricing_scheme_id, ps.name as scheme_name,
                    pp.unit_price
                FROM product_prices pp
                JOIN pricing_schemes ps ON pp.pricing_scheme_id = ps.id
                WHERE pp.product_id = %s AND ps.is_active = TRUE
                ORDER BY ps.is_default DESC, ps.id ASC
            """, (product_id,))

    boms = query_all("""
        SELECT pb.id, pb.component_product_id, p.name as component_name, p.sku as component_sku,
               p.image_url as component_image_url,
               COALESCE(pb.description, p.description, '') as description,
               pb.quantity, 
               COALESCE(p.standard_cost, pb.cost, 0) as cost,
               ROUND(pb.quantity * COALESCE(p.standard_cost, pb.cost, 0), 4) as subtotal_cost,
               COALESCE((SELECT SUM(quantity) FROM inventory WHERE product_id = pb.component_product_id), 0) as component_stock
        FROM product_boms pb
        LEFT JOIN products p ON pb.component_product_id = p.id
        WHERE pb.product_id = %s
        ORDER BY pb.id ASC
    """, (product_id,))
    
    total_bom_cost = 0.0
    available_bundle_qty = 999999999
    is_bundle = len(boms) > 0 or product.get('combine_type') == 'multi'
    bottleneck_component = None

    if boms:
        for b in boms:
            b_cost = float(b.get('cost') or 0.0)
            b_qty = float(b.get('quantity') or 1.0)
            b_sub = round(b_cost * b_qty, 4)
            b['subtotal_cost'] = b_sub
            total_bom_cost += b_sub

            c_stock = float(b.get('component_stock') or 0.0)
            possible = int(c_stock // b_qty) if b_qty > 0 else 0
            b['max_kits_possible'] = max(0, possible)
            if possible < available_bundle_qty:
                available_bundle_qty = max(0, possible)
                bottleneck_component = b
        total_bom_cost = round(total_bom_cost, 4)
        if product.get('standard_cost') != total_bom_cost or product.get('average_cost') != total_bom_cost:
            execute("UPDATE products SET standard_cost = %s, average_cost = %s, combine_type = 'multi', cost_formula = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (total_bom_cost, total_bom_cost, product_id))
            product['standard_cost'] = total_bom_cost
            product['average_cost'] = total_bom_cost
        cost = total_bom_cost
    else:
        available_bundle_qty = 0
        if product.get('costing_method') == 'Average':
            cost = float(product['average_cost'] or product['standard_cost'] or 0)
        else:
            cost = float(product['standard_cost'] or product['average_cost'] or 0)

    # User requirement: mark up should calculate based on Sale UOM such as case or pcs and multiply costing with number of pcs in 1 case
    sales_uom = (product.get('sales_uom') or '').strip().lower()
    std_uom = (product.get('uom') or '').strip().lower()
    if sales_uom and std_uom and sales_uom == std_uom:
        multiplier = 1.0
    else:
        ratio_std = float(product.get('sales_uom_ratio_std') or 1.0)
        ratio_sales = float(product.get('sales_uom_ratio') or 1.0)
        multiplier = (ratio_std / ratio_sales) if ratio_sales > 0 else 1.0

    effective_cost = cost * multiplier

    for pt in price_tiers:
        price = float(pt['unit_price'] or 0)
        if effective_cost > 0:
            markup = ((price - effective_cost) / effective_cost) * 100
        else:
            markup = 0.0
        rounded = f"{markup:.2f}"
        pt['markup'] = rounded.rstrip('0').rstrip('.') if '.' in rounded else rounded
        if pt['markup'] == '' or pt['markup'] == '-0':
            pt['markup'] = '0'

    # Product version history
    versions = query_all("""
        SELECT * FROM product_versions
        WHERE product_id = %s
        ORDER BY version_number DESC, created_at DESC
    """, (product_id,))

    # Recent stock movement logs
    recent_movements = query_all("""
        SELECT 
            il.*,
            fl.name as from_location_name,
            tl.name as to_location_name
        FROM inventory_logs il
        LEFT JOIN locations fl ON il.from_location_id = fl.id
        LEFT JOIN locations tl ON il.to_location_id = tl.id
        WHERE il.product_id = %s
        ORDER BY il.created_at DESC
        LIMIT 25
    """, (product_id,))

    # Order history (SO & PO)
    recent_orders = query_all("""
        (
            SELECT 'SO' as order_type, so.id as order_id, so.order_number, so.order_date, c.name as party_name, 
                   COALESCE(sol.quantity_display, sol.quantity) as quantity, 
                   sol.uom, 
                   sol.unit_price, 
                   COALESCE(sol.subtotal, (COALESCE(sol.quantity_display, sol.quantity) * sol.unit_price)) as total_amount,
                   so.status
            FROM sales_order_lines sol
            JOIN sales_orders so ON sol.sales_order_id = so.id
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE sol.product_id = %s
        )
        UNION ALL
        (
            SELECT 'PO' as order_type, po.id as order_id, po.order_number as order_number, po.order_date, v.name as party_name, 
                   pol.quantity, 
                   pol.uom, 
                   pol.unit_cost as unit_price, 
                   COALESCE(pol.subtotal, (pol.quantity * pol.unit_cost)) as total_amount,
                   po.status
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            LEFT JOIN vendors v ON po.vendor_id = v.id
            WHERE pol.product_id = %s
        )
        ORDER BY order_date DESC LIMIT 25
    """, (product_id, product_id))

    # Dedicated Sales Order History
    sales_history = query_all("""
        SELECT 
            'SO' as order_type, 
            so.id as order_id, 
            so.order_number, 
            so.order_date, 
            c.name as customer_name, 
            COALESCE(sol.quantity_display, sol.quantity) as quantity, 
            sol.uom, 
            sol.unit_price, 
            COALESCE(sol.subtotal, (COALESCE(sol.quantity_display, sol.quantity) * sol.unit_price)) as total_amount,
            so.status
        FROM sales_order_lines sol
        JOIN sales_orders so ON sol.sales_order_id = so.id
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE sol.product_id = %s
        ORDER BY so.order_date DESC, so.id DESC LIMIT 30
    """, (product_id,))

    # Dedicated Purchase Order History
    purchase_history = query_all("""
        SELECT 
            'PO' as order_type, 
            po.id as order_id, 
            po.order_number, 
            po.order_date, 
            po.received_date,
            v.name as vendor_name, 
            pol.quantity, 
            COALESCE(pol.received_qty, 0) as received_qty,
            pol.uom,
            pol.unit_cost, 
            COALESCE(pol.subtotal, (pol.quantity * pol.unit_cost)) as total_amount,
            po.status
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON pol.purchase_order_id = po.id
        LEFT JOIN vendors v ON po.vendor_id = v.id
        WHERE pol.product_id = %s
        ORDER BY po.order_date DESC, po.id DESC LIMIT 30
    """, (product_id,))

    # Product vendors
    product_vendors = query_all("""
        SELECT 
            pv.id,
            v.id as vendor_id,
            v.name as vendor_name,
            v.contact_name,
            v.phone as vendor_phone,
            v.payment_terms,
            pv.vendor_item_code,
            COALESCE(NULLIF(pv.cost, 0), po.unit_cost, %s) as last_cost
        FROM product_vendors pv
        JOIN vendors v ON pv.vendor_id = v.id
        LEFT JOIN (
            SELECT pol.product_id, po.vendor_id, pol.unit_cost,
                   ROW_NUMBER() OVER(PARTITION BY po.vendor_id ORDER BY po.order_date DESC) as rn
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON pol.purchase_order_id = po.id
            WHERE pol.product_id = %s
        ) po ON v.id = po.vendor_id AND po.rn = 1
        WHERE pv.product_id = %s AND v.is_active = TRUE
        ORDER BY v.name ASC
    """, (cost, product_id, product_id))

    if not product_vendors:
        product_vendors = query_all("""
            SELECT v.id as vendor_id, v.name as vendor_name, v.contact_name, v.phone as vendor_phone, v.payment_terms, '' as vendor_item_code, po.unit_cost as last_cost
            FROM vendors v
            JOIN (
                SELECT pol.product_id, po.vendor_id, pol.unit_cost,
                       ROW_NUMBER() OVER(PARTITION BY po.vendor_id ORDER BY po.order_date DESC) as rn
                FROM purchase_order_lines pol
                JOIN purchase_orders po ON pol.purchase_order_id = po.id
                WHERE pol.product_id = %s
            ) po ON v.id = po.vendor_id AND po.rn = 1
            WHERE v.is_active = TRUE
            ORDER BY po.unit_cost IS NOT NULL DESC, v.name ASC LIMIT 25
        """, (product_id,))

    attachments = query_all("""
        SELECT * FROM product_attachments WHERE product_id = %s ORDER BY created_at DESC
    """, (product_id,))

    categories = query_all("SELECT id, name, COALESCE(color, '#00A3E0') as color FROM categories WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    all_vendors = query_all("SELECT id, name FROM vendors WHERE is_active = TRUE ORDER BY name ASC")


    all_products = query_all("SELECT id, name, sku, description, standard_cost, image_url FROM products WHERE is_active = TRUE AND id != %s ORDER BY name ASC", (product_id,))
    pricing_schemes = query_all("SELECT id, name, COALESCE(currency, 'US Dollar ($)') as currency, is_active FROM pricing_schemes WHERE is_active = TRUE ORDER BY id ASC")

    can_view_costs = user_can_view_costs()
    if not can_view_costs:
        product['standard_cost'] = 0.0
        product['average_cost'] = 0.0
        product['cost_formula'] = None
        product['factory_cost'] = None
        product['factory_cost_formula'] = None
        product['cost_rate'] = None
        product['shipping_cost'] = None
        product['costing_sheet_cost'] = None
        for pt in price_tiers:
            pt['markup'] = '-'
        for v in product_vendors:
            v['last_cost'] = 0.0
        for po in purchase_history:
            po['unit_cost'] = 0.0
            po['total_amount'] = 0.0
        for b in boms:
            b['cost'] = 0.0
            b['subtotal_cost'] = 0.0
        total_bom_cost = 0.0
        for p in all_products:
            p['standard_cost'] = 0.0
        for ver in versions:
            ver['standard_cost'] = 0.0
        for ro in recent_orders:
            if ro.get('order_type') == 'PO':
                ro['unit_price'] = 0.0

    combine_options = query_all("""
        SELECT pco.*, 
               p.name as component_name, p.sku as component_sku, p.uom as component_uom,
               p.default_price as component_default_price,
               COALESCE(inv.total_qty, 0) as component_stock
        FROM product_combine_options pco
        LEFT JOIN products p ON pco.component_product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE pco.product_id = %s
        ORDER BY pco.sort_order ASC, pco.id ASC
    """, (product_id,))

    price_card = _build_price_card_data(product, price_tiers, can_view_costs=can_view_costs)

    return {
        'product': product,
        'location_stocks': location_stocks,
        'price_tiers': price_tiers,
        'price_card': price_card,
        'recent_movements': recent_movements,
        'recent_orders': recent_orders,
        'sales_history': sales_history,
        'purchase_history': purchase_history,
        'product_vendors': product_vendors,
        'attachments': attachments,
        'versions': versions,
        'categories': categories,
        'locations': locations,
        'all_vendors': all_vendors,
        'boms': boms,
        'total_bom_cost': total_bom_cost,
        'available_bundle_qty': available_bundle_qty,
        'is_bundle': is_bundle,
        'bottleneck_component': bottleneck_component,
        'combine_options': combine_options,
        'all_products': all_products,
        'pricing_schemes': pricing_schemes,
        'can_view_costs': can_view_costs,
        'can_edit_prices': user_can_edit_prices(),
        'can_adjust_stock': user_can_adjust_stock(),
        'global_price_table_style': global_price_table_style,
        'effective_price_table_style': (product.get('price_table_style') or global_price_table_style or 'classic').lower()
    }

def _render_table_list_products():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    offset = (page - 1) * per_page
    
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category_id', '').strip()
    stock_status = request.args.get('stock_status', '').strip()

    where_clauses = ["p.is_active = TRUE"]
    params = []

    if search:
        where_clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])

    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(int(category_id))

    where_sql = " AND ".join(where_clauses)

    having_clause = ""
    if stock_status == 'out_of_stock':
        having_clause = "HAVING COALESCE(SUM(i.quantity), 0) <= 0"
    elif stock_status == 'low_stock':
        having_clause = "HAVING COALESCE(SUM(i.quantity), 0) > 0 AND COALESCE(SUM(i.quantity), 0) <= p.reorder_point"
    elif stock_status == 'in_stock':
        having_clause = "HAVING COALESCE(SUM(i.quantity), 0) > p.reorder_point"

    count_sql = f"""
        SELECT COUNT(*) as cnt FROM (
            SELECT p.id
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            WHERE {where_sql}
            GROUP BY p.id
            {having_clause}
        ) sub
    """
    total_count = query_one(count_sql, tuple(params))['cnt']
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    list_sql = f"""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.uom, p.master_pack_qty, p.inner_pack_qty,
            p.reorder_point, p.reorder_quantity, p.standard_cost, p.average_cost, p.default_price,
            c.name as category_name,
            COALESCE(SUM(i.quantity), 0) as total_qty,
            COALESCE(SUM(i.reserved_quantity), 0) as reserved_qty,
            COALESCE(SUM(i.quantity) - SUM(i.reserved_quantity), 0) as available_qty
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN inventory i ON p.id = i.product_id
        WHERE {where_sql}
        GROUP BY p.id, c.name
        {having_clause}
        ORDER BY p.id ASC
        LIMIT %s OFFSET %s
    """
    rows_params = params.copy()
    rows_params.extend([per_page, offset])
    products = query_all(list_sql, tuple(rows_params))

    categories = query_all("SELECT id, name, COALESCE(color, '#00A3E0') as color FROM categories WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")

    can_view_costs = user_can_view_costs()
    if not can_view_costs:
        for p in products:
            p['standard_cost'] = 0.0
            p['average_cost'] = 0.0

    return render_template('products/list.html',
                           products=products,
                           categories=categories,
                           locations=locations,
                           search=search,
                           category_id=category_id,
                           stock_status=stock_status,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           can_view_costs=can_view_costs)

@products_bp.route('/products')
def list_products():
    if request.args.get('view') == 'table':
        return _render_table_list_products()

    catalog_products = _get_catalog_sidebar_products()
    if not catalog_products:
        return redirect(url_for('products.new_product'))

    selected_id = request.args.get('id', type=int)
    if not selected_id:
        selected_id = catalog_products[0]['id']

    bundle = _get_product_detail_bundle(selected_id)
    if not bundle:
        selected_id = catalog_products[0]['id']
        bundle = _get_product_detail_bundle(selected_id)

    return render_template('products/catalog.html',
                           catalog_products=catalog_products,
                           **bundle)

@products_bp.route('/products/<int:id>')
def detail_product(id):
    if request.args.get('legacy') == '1':
        bundle = _get_product_detail_bundle(id)
        if not bundle:
            flash("Product not found.", "error")
            return redirect(url_for('products.list_products'))
        return render_template('products/detail.html',
                               active_tab=request.args.get('tab', 'tabProductInfo'),
                               is_new=False,
                               **bundle)

    catalog_products = _get_catalog_sidebar_products()
    bundle = _get_product_detail_bundle(id)
    if not bundle:
        flash("Product not found.", "error")
        return redirect(url_for('products.list_products'))

    return render_template('products/catalog.html',
                           catalog_products=catalog_products,
                           **bundle)

@products_bp.route('/products/<int:id>/update_ajax', methods=['POST'])
def update_product_ajax(id):
    try:
        data = request.get_json(force=True) or {}
        
        # Protect internal cost fields from branch updates if branch cannot view/edit costs
        if not user_can_view_costs():
            for cf in (
                'standard_cost', 'average_cost', 'cost_formula', 'cost_price',
                'factory_cost', 'factory_cost_formula', 'cost_rate', 'cost_rate_formula',
                'shipping_cost', 'shipping_cost_formula', 'costing_sheet_pcs', 'costing_sheet_pcs_formula',
                'costing_sheet_cost', 'costing_sheet_formula'
            ):
                data.pop(cf, None)

        # Protect selling prices from branch updates if user cannot edit selling prices
        if not user_can_edit_prices():
            for pf in ('default_price', 'tier_price_1', 'tier_price_2', 'tier_price_3'):
                data.pop(pf, None)
            data.pop('prices', None)
        
        # 1. Update product scalar fields
        allowed_fields = [
            'name', 'sku', 'barcode', 'description', 'category_id',
            'reorder_point', 'reorder_quantity', 'default_location_id',
            'default_sublocation', 'last_vendor_id',
            'uom', 'sales_uom', 'sales_uom_ratio', 'sales_uom_ratio_std',
            'purchasing_uom', 'purchasing_uom_ratio', 'purchasing_uom_ratio_std',
            'standard_cost', 'average_cost', 'cost_formula', 'default_price', 'remarks',
            'length', 'width', 'height', 'weight',
            'packs_per_case', 'pcs_per_pack',
            'tier_qty_1', 'tier_qty_2', 'tier_qty_3',
            'tier_price_1', 'tier_price_2', 'tier_price_3',
            'price_card_notes', 'price_card_color', 'price_card_font', 'price_card_unit',
            'price_card_custom_detail', 'price_card_is_custom_detail', 'price_card_style',
            'factory_cost', 'factory_cost_formula',
            'cost_rate', 'cost_rate_formula',
            'shipping_cost', 'shipping_cost_formula',
            'costing_sheet_pcs', 'costing_sheet_pcs_formula',
            'costing_sheet_cost', 'costing_sheet_formula',
            'combine_type',
            'price_decimals', 'cost_decimals', 'qty_decimals'
        ]
        
        # Handle 'cost_formula' and formula evaluation
        if 'cost_formula' in data:
            raw_f = data.get('cost_formula')
            if raw_f is None or str(raw_f).strip() in ('', 'None', 'null', 'undefined'):
                data['cost_formula'] = None
            else:
                f_str = str(raw_f).strip()
                data['cost_formula'] = f_str
                calc_val = safe_eval_math(f_str)
                data['standard_cost'] = calc_val
                data['average_cost'] = calc_val

        # Handle 'cost_price' alias for costing
        if 'cost_price' in data and 'standard_cost' not in data:
            data['standard_cost'] = data['cost_price']
            data['average_cost'] = data['cost_price']

        # Purchases UOM always equal to Sale UOM no need to fill
        if 'sales_uom' in data:
            data['purchasing_uom'] = data['sales_uom']
        if 'sales_uom_ratio' in data:
            data['purchasing_uom_ratio'] = data['sales_uom_ratio']
        if 'sales_uom_ratio_std' in data:
            data['purchasing_uom_ratio_std'] = data['sales_uom_ratio_std']

        # Number pack per case should automatically calculate: pcs per case / pcs per pack
        s_std = data.get('sales_uom_ratio_std')
        p_pack = data.get('pcs_per_pack')
        if s_std is not None or p_pack is not None:
            curr_prod = query_one("SELECT sales_uom_ratio_std, pcs_per_pack FROM products WHERE id = %s", (id,)) or {}
            calc_std = float(s_std if s_std is not None else (curr_prod.get('sales_uom_ratio_std') or 0))
            calc_pack = float(p_pack if p_pack is not None else (curr_prod.get('pcs_per_pack') or 0))
            if calc_std > 0 and calc_pack > 0:
                data['packs_per_case'] = round(calc_std / calc_pack, 2)

        updates = []
        params = []
        for field in allowed_fields:
            if field in data:
                val = data[field]
                if field in ('category_id', 'default_location_id', 'last_vendor_id'):
                    val = int(val) if val and str(val).strip() != '' else None
                elif field in ('price_decimals', 'cost_decimals', 'qty_decimals'):
                    val = int(val) if val is not None and str(val).strip() not in ('', 'None', 'null', '-1') else None
                elif field == 'price_card_is_custom_detail':
                    val = bool(val) if val is not None else False
                elif field == 'price_card_custom_detail':
                    val = str(val).strip() if val is not None else None
                elif field in ('tier_qty_1', 'tier_qty_2', 'tier_qty_3'):
                    val = int(safe_eval_math(val)) if val is not None and str(val).strip() not in ('', 'None', 'null') and int(safe_eval_math(val)) > 0 else None
                elif field in ('length', 'width', 'height', 'weight', 'reorder_point', 'reorder_quantity',
                              'sales_uom_ratio', 'sales_uom_ratio_std', 'purchasing_uom_ratio', 'purchasing_uom_ratio_std',
                              'standard_cost', 'average_cost', 'default_price',
                              'packs_per_case', 'pcs_per_pack',
                              'tier_price_1', 'tier_price_2', 'tier_price_3'):
                    val = safe_eval_math(val) if val is not None and str(val).strip() != '' else 0.0
                elif field in ('factory_cost', 'cost_rate', 'shipping_cost', 'costing_sheet_pcs', 'costing_sheet_cost'):
                    val = safe_eval_math(val) if val is not None and str(val).strip() not in ('', 'None', 'null', 'undefined') else None
                elif field in ('factory_cost_formula', 'cost_rate_formula', 'shipping_cost_formula', 'costing_sheet_pcs_formula', 'costing_sheet_formula'):
                    val = str(val).strip() if val is not None and str(val).strip() not in ('', 'None', 'null', 'undefined') else None
                elif isinstance(val, str):
                    val = val.strip()
                
                updates.append(f"{field} = %s")
                params.append(val)
        
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(id)
            sql = f"UPDATE products SET {', '.join(updates)} WHERE id = %s"
            execute(sql, tuple(params))
            
        # 2. Update pricing scheme prices if provided (only if user has permission)
        prices = data.get('prices')
        if user_can_edit_prices() and prices and isinstance(prices, dict):
            for scheme_id_str, price_val in prices.items():
                try:
                    s_id = int(scheme_id_str)
                    p_val = safe_eval_math(price_val)
                    existing = query_one("SELECT id FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (id, s_id))
                    if existing:
                        execute("UPDATE product_prices SET unit_price = %s WHERE id = %s", (p_val, existing['id']))
                    else:
                        execute("INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price) VALUES (%s, %s, %s)", (id, s_id, p_val))
                except Exception as ex:
                    print(f"Error updating scheme price {scheme_id_str}: {ex}")

        # Fetch updated bundle data for live card synchronization
        updated_prod = query_one("""
            SELECT p.*, c.name as category_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.id = %s
        """, (id,))
        updated_tiers = query_all("""
            SELECT ps.id as pricing_scheme_id, ps.name as scheme_name, pp.unit_price
            FROM product_prices pp
            JOIN pricing_schemes ps ON pp.pricing_scheme_id = ps.id
            WHERE pp.product_id = %s AND ps.is_active = TRUE
        """, (id,))
        updated_price_card = _build_price_card_data(updated_prod, updated_tiers) if updated_prod else None

        return jsonify({
            'success': True,
            'message': 'Product updated successfully.',
            'price_card': updated_price_card,
            'standard_cost': float(updated_prod['standard_cost'] or 0) if updated_prod else 0,
            'price_decimals': updated_prod['price_decimals'] if updated_prod else None,
            'cost_decimals': updated_prod['cost_decimals'] if updated_prod else None
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/add_price', methods=['POST'])
def api_add_product_price(id):
    if not user_can_edit_prices():
        return jsonify({'success': False, 'message': 'Permission denied: Editing selling prices is disabled.'}), 403
    try:
        data = request.get_json(force=True) or {}
        scheme_id = data.get('scheme_id')
        scheme_name = (data.get('scheme_name') or '').strip()
        price = float(data.get('price') or 0.0)

        if not scheme_id and scheme_name:
            # Check if scheme exists
            existing_scheme = query_one("SELECT id FROM pricing_schemes WHERE LOWER(name) = LOWER(%s)", (scheme_name,))
            if existing_scheme:
                scheme_id = existing_scheme['id']
                execute("UPDATE pricing_schemes SET is_active = TRUE WHERE id = %s", (scheme_id,))
            else:
                scheme_id = execute_returning_id("INSERT INTO pricing_schemes (name, is_active, is_default, currency) VALUES (%s, TRUE, FALSE, 'US Dollar ($)') RETURNING id", (scheme_name,))

        if not scheme_id:
            return jsonify({'success': False, 'message': 'Pricing scheme is required.'}), 400

        scheme = query_one("SELECT id, name FROM pricing_schemes WHERE id = %s", (scheme_id,))
        if not scheme:
            return jsonify({'success': False, 'message': 'Pricing scheme not found.'}), 404

        existing_price = query_one("SELECT id FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (id, scheme_id))
        if existing_price:
            execute("UPDATE product_prices SET unit_price = %s WHERE id = %s", (price, existing_price['id']))
        else:
            execute("INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price) VALUES (%s, %s, %s)", (id, scheme_id, price))

        # Calculate markup
        prod = query_one("SELECT standard_cost, average_cost, sales_uom, uom, sales_uom_ratio, sales_uom_ratio_std FROM products WHERE id = %s", (id,))
        cost = float(prod['standard_cost'] or prod['average_cost'] or 0.0) if prod else 0.0
        sales_ratio = float(prod.get('sales_uom_ratio') or 1.0) if prod else 1.0
        std_ratio = float(prod.get('sales_uom_ratio_std') or 1.0) if prod else 1.0
        mult = (std_ratio / sales_ratio) if sales_ratio > 0 else 1.0
        eff_cost = cost * mult
        if eff_cost > 0:
            markup = ((price - eff_cost) / eff_cost) * 100
            markup_str = f"{markup:.2f}".rstrip('0').rstrip('.')
        else:
            markup_str = "0"

        return jsonify({
            'success': True,
            'scheme_id': scheme['id'],
            'scheme_name': scheme['name'],
            'unit_price': price,
            'markup': markup_str
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/delete_price/<int:scheme_id>', methods=['POST', 'DELETE'])
def api_delete_product_price(id, scheme_id):
    if not user_can_edit_prices():
        return jsonify({'success': False, 'message': 'Permission denied: Editing selling prices is disabled.'}), 403
    try:
        execute("DELETE FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (id, scheme_id))
        return jsonify({'success': True, 'message': 'Price tier deleted.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/delete_cost', methods=['POST'])
def api_delete_product_cost(id):
    try:
        execute("UPDATE products SET standard_cost = 0, average_cost = 0, cost_formula = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
        return jsonify({'success': True, 'message': 'Product cost deleted/cleared.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/update_cost', methods=['POST'])
def api_update_product_cost(id):
    try:
        data = request.get_json(force=True) or {}
        raw = data.get('cost') or data.get('formula') or 0.0
        formula_str = str(raw).strip() if (isinstance(raw, str) and any(c in str(raw) for c in '+-*/=')) else None
        cost = safe_eval_math(raw)
        execute("""
            UPDATE products 
            SET standard_cost = %s, average_cost = %s, cost_formula = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """, (cost, cost, formula_str, id))
        update_parent_boms_cost(id)
        return jsonify({'success': True, 'cost': cost, 'formula': formula_str})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/adjust_stock', methods=['POST'])
def api_adjust_product_stock(id):
    if not user_can_adjust_stock():
        return jsonify({'success': False, 'message': 'Permission denied: Stock adjustments are disabled for this user/branch.'}), 403
    try:
        data = request.get_json(force=True) or {}
        location_id = int(data.get('location_id'))
        mode = data.get('mode', 'set')  # 'set' (counted quantity) or 'diff' (+/- quantity)
        raw_qty = float(data.get('quantity', 0))
        reason = (data.get('reason') or 'Recount / Inventory Count').strip()
        notes = (data.get('notes') or '').strip()

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT COALESCE(quantity, 0) as qty 
                FROM inventory 
                WHERE product_id = %s AND location_id = %s AND sublocation = ''
                FOR UPDATE
            """, (id, location_id))
            cur_inv = cur.fetchone()
            old_qty = float(cur_inv['qty']) if cur_inv else 0.0

            if mode == 'diff':
                new_qty = old_qty + raw_qty
                diff_qty = raw_qty
            else:
                new_qty = raw_qty
                diff_qty = new_qty - old_qty

            if new_qty < 0:
                return jsonify({'success': False, 'message': f'Stock quantity cannot be negative (current: {old_qty:g}, adjustment: {raw_qty:+g}).'}), 400

            if abs(diff_qty) < 1e-9:
                return jsonify({
                    'success': True,
                    'message': 'No quantity change detected.',
                    'old_qty': old_qty,
                    'new_qty': new_qty,
                    'diff_qty': 0,
                    'location_id': location_id
                })

            seq_val = get_next_sequence_val('adj_number_seq')
            adj_number = f"ADJ-{seq_val:05d}"

            cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s", (id,))
            prod = cur.fetchone()
            unit_cost = float(prod['average_cost'] or prod['standard_cost'] or 0) if prod else 0.0

            cur.execute("""
                INSERT INTO stock_adjustments (adjustment_number, location_id, reason, status, notes)
                VALUES (%s, %s, %s, 'COMPLETED', %s)
                RETURNING id;
            """, (adj_number, location_id, reason, notes))
            adj_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO stock_adjustment_lines (adjustment_id, product_id, old_qty, new_qty, diff_qty, unit_cost)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (adj_id, id, old_qty, new_qty, diff_qty, unit_cost))

            cur.execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES (%s, %s, '', %s)
                ON CONFLICT (product_id, location_id, sublocation)
                DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
            """, (id, location_id, new_qty))

            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    to_location_id, quantity, qty_before, qty_after, unit_cost, reason, notes
                ) VALUES (%s, 'ADJUSTMENT', 'ADJUST', %s, %s, %s, %s, %s, %s, %s, %s);
            """, (id, adj_number, location_id, diff_qty, old_qty, new_qty, unit_cost, reason, notes))

            cur.execute("SELECT COALESCE(SUM(quantity), 0) as total_qty FROM inventory WHERE product_id = %s", (id,))
            total_qty = float(cur.fetchone()['total_qty'] or 0)

            cur.execute("""
                SELECT 
                    l.id as location_id, l.name as location_name,
                    COALESCE(i.quantity, 0) as quantity
                FROM locations l
                LEFT JOIN inventory i ON l.id = i.location_id AND i.product_id = %s
                WHERE l.is_active = TRUE AND l.name NOT LIKE '<%%>'
                ORDER BY l.is_default DESC, l.name ASC
            """, (id,))
            loc_stocks = [
                {
                    'location_id': r['location_id'],
                    'location_name': r['location_name'],
                    'quantity': float(r['quantity'] or 0)
                } for r in cur.fetchall()
            ]

        return jsonify({
            'success': True,
            'message': f"Stock adjusted: {adj_number} (Now: {new_qty:g}, Diff: {diff_qty:+g})",
            'adjustment_number': adj_number,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'diff_qty': diff_qty,
            'location_id': location_id,
            'total_qty': total_qty,
            'location_stocks': loc_stocks
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/<int:id>/batch_adjust_stock', methods=['POST'])
def api_batch_adjust_product_stock(id):
    if not user_can_adjust_stock():
        return jsonify({'success': False, 'message': 'Permission denied.'}), 403
    try:
        data = request.get_json(force=True) or {}
        adjustments = data.get('adjustments', [])
        reason = (data.get('reason') or 'Multi-Location Audit / Recount').strip()
        notes = (data.get('notes') or '').strip()
        if not adjustments:
            return jsonify({'success': False, 'message': 'No adjustments provided.'}), 400

        applied_count = 0
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT average_cost, standard_cost FROM products WHERE id = %s", (id,))
            prod = cur.fetchone()
            unit_cost = float(prod['average_cost'] or prod['standard_cost'] or 0) if prod else 0.0

            for adj in adjustments:
                loc_id = int(adj.get('location_id'))
                new_qty = float(adj.get('new_qty', 0))
                if new_qty < 0:
                    continue
                cur.execute("""
                    SELECT COALESCE(quantity, 0) as qty 
                    FROM inventory 
                    WHERE product_id = %s AND location_id = %s AND sublocation = ''
                    FOR UPDATE
                """, (id, loc_id))
                cur_inv = cur.fetchone()
                old_qty = float(cur_inv['qty']) if cur_inv else 0.0
                diff_qty = new_qty - old_qty
                if abs(diff_qty) < 1e-9:
                    continue

                seq_val = get_next_sequence_val('adj_number_seq')
                adj_number = f"ADJ-{seq_val:05d}"

                cur.execute("""
                    INSERT INTO stock_adjustments (adjustment_number, location_id, reason, status, notes)
                    VALUES (%s, %s, %s, 'COMPLETED', %s)
                    RETURNING id;
                """, (adj_number, loc_id, reason, notes))
                adj_id = cur.fetchone()['id']

                cur.execute("""
                    INSERT INTO stock_adjustment_lines (adjustment_id, product_id, old_qty, new_qty, diff_qty, unit_cost)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (adj_id, id, old_qty, new_qty, diff_qty, unit_cost))

                cur.execute("""
                    INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                    VALUES (%s, %s, '', %s)
                    ON CONFLICT (product_id, location_id, sublocation)
                    DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = CURRENT_TIMESTAMP;
                """, (id, loc_id, new_qty))

                cur.execute("""
                    INSERT INTO inventory_logs (
                        product_id, movement_type, reference_type, reference_id,
                        to_location_id, quantity, qty_before, qty_after, unit_cost, reason, notes
                    ) VALUES (%s, 'ADJUSTMENT', 'ADJUST', %s, %s, %s, %s, %s, %s, %s, %s);
                """, (id, adj_number, loc_id, diff_qty, old_qty, new_qty, unit_cost, reason, notes))
                applied_count += 1

            cur.execute("SELECT COALESCE(SUM(quantity), 0) as total_qty FROM inventory WHERE product_id = %s", (id,))
            total_qty = float(cur.fetchone()['total_qty'] or 0)

            cur.execute("""
                SELECT 
                    l.id as location_id, l.name as location_name,
                    COALESCE(i.quantity, 0) as quantity
                FROM locations l
                LEFT JOIN inventory i ON l.id = i.location_id AND i.product_id = %s
                WHERE l.is_active = TRUE AND l.name NOT LIKE '<%%>'
                ORDER BY l.is_default DESC, l.name ASC
            """, (id,))
            loc_stocks = [
                {
                    'location_id': r['location_id'],
                    'location_name': r['location_name'],
                    'quantity': float(r['quantity'] or 0)
                } for r in cur.fetchall()
            ]

        return jsonify({
            'success': True,
            'message': f"Updated {applied_count} warehouse location(s) successfully!",
            'total_qty': total_qty,
            'location_stocks': loc_stocks
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/products/<int:id>/upload_picture', methods=['POST'])
def upload_product_picture(id):
    try:
        save_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'products')
        os.makedirs(save_dir, exist_ok=True)

        # 1. Support JSON base64 data URL
        if request.is_json:
            data = request.get_json(silent=True) or {}
            img_b64 = data.get('picture') or data.get('image') or data.get('image_base64') or ''
            if img_b64 and 'base64,' in img_b64:
                import base64
                header, encoded = img_b64.split('base64,', 1)
                mime = header.split(';')[0].replace('data:', '').strip()
                ext_map = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif', 'image/webp': '.webp'}
                ext = ext_map.get(mime, '.png')
                img_bytes = base64.b64decode(encoded)
                filename = f"prod_{id}_{int(time.time())}{ext}"
                with open(os.path.join(save_dir, filename), 'wb') as f:
                    f.write(img_bytes)
                image_url = f"/static/uploads/products/{filename}"
                execute("UPDATE products SET image_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (image_url, id))
                return jsonify({'success': True, 'image_url': image_url})

        # 2. Support standard multipart/form-data upload (including pasted blobs)
        if 'picture' not in request.files:
            return jsonify({'success': False, 'message': 'No picture uploaded'}), 400
        file = request.files['picture']
        if file.filename == '' and not getattr(file, 'mimetype', ''):
            return jsonify({'success': False, 'message': 'No selected file'}), 400
        
        ext = os.path.splitext(file.filename)[1].lower() if file.filename else ''
        if not ext or ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            mimetype = (getattr(file, 'mimetype', '') or '').lower()
            if 'png' in mimetype:
                ext = '.png'
            elif 'jpeg' in mimetype or 'jpg' in mimetype:
                ext = '.jpg'
            elif 'webp' in mimetype:
                ext = '.webp'
            elif 'gif' in mimetype:
                ext = '.gif'
            else:
                ext = '.png'
            
        filename = f"prod_{id}_{int(time.time())}{ext}"
        file.save(os.path.join(save_dir, filename))
        
        image_url = f"/static/uploads/products/{filename}"
        execute("UPDATE products SET image_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (image_url, id))
        
        return jsonify({'success': True, 'image_url': image_url})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/products/toggle_active/<int:id>', methods=['POST'])
def toggle_product_active_ajax(id):
    try:
        prod = query_one("SELECT is_active FROM products WHERE id = %s", (id,))
        if not prod:
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        new_val = not prod['is_active']
        execute("UPDATE products SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_val, id))
        return jsonify({'success': True, 'is_active': new_val})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/products/delete/<int:id>', methods=['POST', 'DELETE'])
@products_bp.route('/products/<int:id>/delete', methods=['POST', 'DELETE'])
def delete_catalog_product(id):
    try:
        prod = query_one("SELECT id, name, sku FROM products WHERE id = %s", (id,))
        if not prod:
            return jsonify({'success': False, 'message': 'Product not found'}), 404

        snapshot_desc = f"{prod['name']} ({prod['sku']})"

        # Safely detach foreign key references before deleting product
        # Preserve product description in historical sales and purchase orders
        execute("""
            UPDATE sales_order_lines 
            SET description = COALESCE(NULLIF(description, ''), %s), 
                product_id = NULL 
            WHERE product_id = %s
        """, (snapshot_desc, id))

        execute("""
            UPDATE purchase_order_lines 
            SET description = COALESCE(NULLIF(description, ''), %s), 
                product_id = NULL 
            WHERE product_id = %s
        """, (snapshot_desc, id))

        execute("DELETE FROM stock_transfer_lines WHERE product_id = %s", (id,))
        execute("DELETE FROM stock_adjustment_lines WHERE product_id = %s", (id,))
        execute("DELETE FROM product_boms WHERE product_id = %s OR component_product_id = %s", (id, id))

        # Now delete product (cascades inventory, inventory_logs, product_prices, product_attachments, product_versions, product_vendors)
        execute("DELETE FROM products WHERE id = %s", (id,))

        # Find the product directly ABOVE the deleted product (so selection stays at the product above it)
        next_id = None
        if request.is_json:
            req_data = request.get_json(silent=True) or {}
            preferred_next_id = req_data.get('preferred_next_id')
            if preferred_next_id:
                try:
                    check_p = query_one("SELECT id FROM products WHERE id = %s", (int(preferred_next_id),))
                    if check_p:
                        next_id = check_p['id']
                except Exception:
                    pass

        if not next_id:
            # Query for the product directly ABOVE this one in catalog order (name ASC, id ASC)
            above_prod = query_one("""
                SELECT id FROM products 
                WHERE (name < %s OR (name = %s AND id < %s))
                ORDER BY name DESC, id DESC 
                LIMIT 1
            """, (prod['name'], prod['name'], id))
            if above_prod:
                next_id = above_prod['id']
            else:
                # If deleted product was the first item, pick the product directly below it
                below_prod = query_one("""
                    SELECT id FROM products 
                    WHERE (name > %s OR (name = %s AND id > %s))
                    ORDER BY name ASC, id ASC 
                    LIMIT 1
                """, (prod['name'], prod['name'], id))
                if below_prod:
                    next_id = below_prod['id']
                else:
                    # Fallback to any remaining product
                    rem_prod = query_one("SELECT id FROM products ORDER BY name ASC, id ASC LIMIT 1")
                    next_id = rem_prod['id'] if rem_prod else None

        return jsonify({
            'success': True,
            'message': f"Product '{prod['name']}' deleted successfully.",
            'next_id': next_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/products/new')
def new_product():
    next_id = query_one("SELECT COALESCE(MAX(id), 0) + 1 as nid FROM products")['nid']
    new_sku = f"SKU-{next_id:04d}"
    
    product = {
        'id': None,
        'sku': new_sku,
        'name': '',
        'description': '',
        'barcode': '',
        'category_id': None,
        'category_name': '',
        'uom': 'pcs.',
        'master_pack_qty': 1.0,
        'inner_pack_qty': 1.0,
        'default_location_id': None,
        'reorder_point': 0.0,
        'reorder_quantity': 0.0,
        'standard_cost': 0.0,
        'average_cost': 0.0,
        'last_purchase_cost': 0.0,
        'default_price': 0.0,
        'item_type': 'Stockable',
        'tax_code': 'Taxable',
        'costing_method': 'Manual',
        'image_url': None,
        'is_active': True,
        'total_qty': 0,
        'reserved_qty': 0,
        'custom1': '',
        'custom2': '',
        'custom3': '',
        'custom4': '',
        'custom5': '',
        'default_sublocation': '',
        'last_vendor_id': None,
        'sales_uom': 'cases',
        'sales_uom_ratio': 1.0,
        'sales_uom_ratio_std': 200.0,
        'purchasing_uom': 'cases',
        'purchasing_uom_ratio': 1.0,
        'purchasing_uom_ratio_std': 1.0,
        'length': None,
        'width': None,
        'height': None,
        'weight': None,
        'packs_per_case': 10,
        'pcs_per_pack': 50,
        'price_decimals': None,
        'cost_decimals': None,
        'qty_decimals': None,
        'cost_formula': None,
        'price_card_color': '#00A3E0',
        'price_card_font': 'Kantumruy Pro',
        'price_card_notes': '',
        'factory_cost': None,
        'factory_cost_formula': '',
        'cost_rate': None,
        'cost_rate_formula': '',
        'shipping_cost': None,
        'shipping_cost_formula': '',
        'costing_sheet_pcs': None,
        'costing_sheet_pcs_formula': '',
        'costing_sheet_cost': None,
        'costing_sheet_formula': '',
        'combine_type': 'single',
        'remarks': ''
    }

    categories = query_all("SELECT id, name, COALESCE(color, '#00A3E0') as color FROM categories WHERE is_active = TRUE ORDER BY name")
    locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE AND name NOT LIKE '<%%>' ORDER BY is_default DESC, name ASC")
    all_vendors = query_all("SELECT id, name FROM vendors WHERE is_active = TRUE ORDER BY name ASC")
    all_products = query_all("SELECT id, name, sku, description, standard_cost FROM products WHERE is_active = TRUE ORDER BY name ASC")
    
    location_stocks = [
        {'location_id': loc['id'], 'location_name': loc['name'], 'quantity': 0.0, 'reserved_quantity': 0.0}
        for loc in locations
    ]

    pricing_schemes = query_all("SELECT id as pricing_scheme_id, name as scheme_name FROM pricing_schemes WHERE is_active = TRUE ORDER BY id")
    price_tiers = [
        {'pricing_scheme_id': ps['pricing_scheme_id'], 'scheme_name': ps['scheme_name'], 'unit_price': 0.0, 'markup': '0'}
        for ps in pricing_schemes
    ]

    return render_template('products/detail.html',
                           product=product,
                           location_stocks=location_stocks,
                           price_tiers=price_tiers,
                           recent_movements=[],
                           recent_orders=[],
                           product_vendors=[],
                           attachments=[],
                           versions=[],
                           categories=categories,
                           locations=locations,
                           all_vendors=all_vendors,
                           boms=[],
                           combine_options=[],
                           all_products=all_products,
                           active_tab=request.args.get('tab', 'tabProductInfo'),
                           is_new=True)

@products_bp.route('/products/create', methods=['POST'])
def create_product():
    try:
        sku = request.form.get('sku', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        barcode = request.form.get('barcode', '').strip() or None
        category_id = request.form.get('category_id') or None
        if category_id == '': category_id = None
        uom = request.form.get('uom', 'pcs.').strip()
        master_pack = float(request.form.get('master_pack_qty', 1.0) or 1.0)
        inner_pack = float(request.form.get('inner_pack_qty', 1.0) or 1.0)
        default_loc = request.form.get('default_location_id') or None
        if default_loc == '': default_loc = None
        default_subloc = request.form.get('default_sublocation', '').strip()
        last_vendor_id = request.form.get('last_vendor_id') or None
        if last_vendor_id == '': last_vendor_id = None
        sales_uom = request.form.get('sales_uom', 'cases').strip()
        sales_uom_ratio = float(request.form.get('sales_uom_ratio', 1) or 1)
        sales_uom_ratio_std = float(request.form.get('sales_uom_ratio_std', 200) or 200)
        # Purchases UOM always equal to Sale UOM no need to fill
        purchasing_uom = sales_uom
        purchasing_uom_ratio = sales_uom_ratio
        purchasing_uom_ratio_std = sales_uom_ratio_std

        pcs_per_pack = safe_eval_math(request.form.get('pcs_per_pack', 50))
        if sales_uom_ratio_std > 0 and pcs_per_pack > 0:
            packs_per_case = round(sales_uom_ratio_std / pcs_per_pack, 2)
        else:
            packs_per_case = safe_eval_math(request.form.get('packs_per_case', 10))

        length_val = float(request.form.get('length')) if request.form.get('length') else None
        width_val = float(request.form.get('width')) if request.form.get('width') else None
        height_val = float(request.form.get('height')) if request.form.get('height') else None
        weight_val = float(request.form.get('weight')) if request.form.get('weight') else None
        remarks = request.form.get('remarks', '').strip() or None

        reorder_pt = float(request.form.get('reorder_point', 0) or 0)
        reorder_qty = float(request.form.get('reorder_quantity', 0) or 0)
        cost_price = float(request.form.get('cost_price', 0) or 0)
        default_price = float(request.form.get('default_price', 0) or 0)
        initial_qty = float(request.form.get('initial_qty', 0) or 0)
        item_type = request.form.get('item_type', 'Stockable').strip()
        tax_code = request.form.get('tax_code', 'Taxable').strip()
        costing_method = request.form.get('costing_method', 'Manual').strip()
        custom1 = request.form.get('custom1', '').strip() or None
        custom2 = request.form.get('custom2', '').strip() or None
        custom3 = request.form.get('custom3', '').strip() or None
        custom4 = request.form.get('custom4', '').strip() or None
        custom5 = request.form.get('custom5', '').strip() or None

        price_dec_raw = request.form.get('price_decimals', '').strip()
        cost_dec_raw = request.form.get('cost_decimals', '').strip()
        qty_dec_raw = request.form.get('qty_decimals', '').strip()
        price_decimals = int(price_dec_raw) if price_dec_raw != '' and price_dec_raw != '-1' else None
        cost_decimals = int(cost_dec_raw) if cost_dec_raw != '' and cost_dec_raw != '-1' else None
        qty_decimals = int(qty_dec_raw) if qty_dec_raw != '' and qty_dec_raw != '-1' else None

        factory_cost = safe_eval_math(request.form.get('factory_cost')) if request.form.get('factory_cost') else None
        factory_cost_formula = request.form.get('factory_cost_formula', '').strip() or None
        cost_rate = safe_eval_math(request.form.get('cost_rate')) if request.form.get('cost_rate') else None
        cost_rate_formula = request.form.get('cost_rate_formula', '').strip() or None
        shipping_cost = safe_eval_math(request.form.get('shipping_cost')) if request.form.get('shipping_cost') else None
        shipping_cost_formula = request.form.get('shipping_cost_formula', '').strip() or None
        costing_sheet_pcs = safe_eval_math(request.form.get('costing_sheet_pcs')) if request.form.get('costing_sheet_pcs') else None
        costing_sheet_pcs_formula = request.form.get('costing_sheet_pcs_formula', '').strip() or None
        costing_sheet_cost = safe_eval_math(request.form.get('costing_sheet_cost')) if request.form.get('costing_sheet_cost') else None
        costing_sheet_formula = request.form.get('costing_sheet_formula', '').strip() or None
        cost_formula = request.form.get('cost_formula', '').strip() or None
        combine_type = request.form.get('combine_type', 'single').strip() or 'single'

        # Rule: If main cost is empty and costing sheet has calculated value, take value automatically!
        if (cost_price is None or cost_price == 0) and costing_sheet_cost and costing_sheet_cost > 0:
            cost_price = costing_sheet_cost
            if not cost_formula and costing_sheet_formula:
                cost_formula = costing_sheet_formula

        if not name:
            flash("Product name is required.", "error")
            return redirect(url_for('products.new_product'))

        if not sku:
            next_id = query_one("SELECT COALESCE(MAX(id), 0) + 1 as nid FROM products")['nid']
            sku = f"SKU-{next_id:04d}"

        new_id = execute_returning_id("""
            INSERT INTO products (
                sku, name, description, barcode, category_id, uom,
                master_pack_qty, inner_pack_qty, default_location_id,
                default_sublocation, last_vendor_id,
                sales_uom, sales_uom_ratio, sales_uom_ratio_std,
                purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
                length, width, height, weight, remarks,
                reorder_point, reorder_quantity, standard_cost, average_cost,
                last_purchase_cost, default_price, item_type, tax_code, costing_method,
                custom1, custom2, custom3, custom4, custom5,
                price_decimals, cost_decimals, qty_decimals,
                cost_formula, factory_cost, factory_cost_formula,
                cost_rate, cost_rate_formula,
                shipping_cost, shipping_cost_formula,
                costing_sheet_pcs, costing_sheet_pcs_formula,
                costing_sheet_cost, costing_sheet_formula,
                packs_per_case, pcs_per_pack,
                combine_type
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s
            ) RETURNING id;
        """, (
            sku, name, description, barcode, category_id, uom,
            master_pack, inner_pack, default_loc,
            default_subloc, last_vendor_id,
            sales_uom, sales_uom_ratio, sales_uom_ratio_std,
            purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
            length_val, width_val, height_val, weight_val, remarks,
            reorder_pt, reorder_qty, cost_price, cost_price,
            cost_price, default_price, item_type, tax_code, costing_method,
            custom1, custom2, custom3, custom4, custom5,
            price_decimals, cost_decimals, qty_decimals,
            cost_formula, factory_cost, factory_cost_formula,
            cost_rate, cost_rate_formula,
            shipping_cost, shipping_cost_formula,
            costing_sheet_pcs, costing_sheet_pcs_formula,
            costing_sheet_cost, costing_sheet_formula,
            packs_per_case, pcs_per_pack,
            combine_type
        ))

        # Handle Picture Upload
        if 'picture' in request.files:
            file = request.files['picture']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    filename = f"prod_{new_id}_{int(time.time())}.{ext}"
                    save_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'products')
                    os.makedirs(save_dir, exist_ok=True)
                    filepath = os.path.join(save_dir, filename)
                    file.save(filepath)
                    image_url = f"/static/uploads/products/{filename}"
                    execute("UPDATE products SET image_url = %s WHERE id = %s", (image_url, new_id))

        # Handle pricing schemes
        pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE")
        for ps in pricing_schemes:
            key = f"scheme_price_{ps['id']}"
            if key in request.form and request.form.get(key) != '':
                try:
                    scheme_val = float(request.form.get(key))
                    execute("""
                        INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (product_id, pricing_scheme_id) DO UPDATE SET unit_price = EXCLUDED.unit_price;
                    """, (new_id, ps['id'], scheme_val))
                    if 'retail 1' in ps['name'].lower() or ps['id'] == 100:
                        execute("UPDATE products SET default_price = %s WHERE id = %s", (scheme_val, new_id))
                        default_price = scheme_val
                except (ValueError, TypeError):
                    pass

        # Handle location inventory
        locations = query_all("SELECT id FROM locations WHERE is_active = TRUE")
        for loc in locations:
            stock_key = f"stock_qty_{loc['id']}"
            if stock_key in request.form and request.form.get(stock_key) != '':
                try:
                    raw_val = request.form.get(stock_key).replace(',', '')
                    val = float(raw_val)
                    if val != 0:
                        execute("""
                            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                            VALUES (%s, %s, '', %s);
                        """, (new_id, loc['id'], val))
                        execute("""
                            INSERT INTO inventory_logs (
                                product_id, movement_type, reference_type, reference_id,
                                to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                            ) VALUES (%s, 'INITIAL', 'MANUAL', %s, %s, %s, 0, %s, %s, 'Initial stock on product creation');
                        """, (new_id, str(new_id), loc['id'], val, val, cost_price))
                except (ValueError, TypeError):
                    pass

        # Handle Bill of Materials / Combined Kit components
        bom_comp_ids = request.form.getlist('bom_component_id[]')
        bom_quantities = request.form.getlist('bom_quantity[]')
        new_bom_comp = request.form.get('new_bom_component_id')
        new_bom_qty = request.form.get('new_bom_quantity', 1)

        if new_bom_comp and str(new_bom_comp).strip() and str(new_bom_comp).strip().isdigit():
            c_id_str = str(new_bom_comp).strip()
            if c_id_str not in [str(x).strip() for x in bom_comp_ids]:
                bom_comp_ids.append(c_id_str)
                bom_quantities.append(new_bom_qty or 1)
            
        if bom_comp_ids:
            for idx, c_id_raw in enumerate(bom_comp_ids):
                try:
                    c_id = int(c_id_raw)
                    b_qty = float(bom_quantities[idx] if idx < len(bom_quantities) else 1) or 1.0
                    comp_prod = query_one("SELECT description, standard_cost FROM products WHERE id = %s", (c_id,))
                    if comp_prod and c_id != new_id:
                        execute("""
                            INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
                            VALUES (%s, %s, %s, %s, %s);
                        """, (new_id, c_id, comp_prod.get('description') or '', b_qty, float(comp_prod.get('standard_cost') or 0)))
                except (ValueError, TypeError):
                    pass
            cost_price = recalc_product_bom_cost(new_id)

        # Legacy initial_qty fallback
        if initial_qty > 0 and default_loc:
            execute("""
                INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                VALUES (%s, %s, '', %s)
                ON CONFLICT (product_id, location_id, sublocation) 
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity;
            """, (new_id, default_loc, initial_qty))

            execute("""
                INSERT INTO inventory_logs (
                    product_id, movement_type, reference_type, reference_id,
                    to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                ) VALUES (%s, 'INITIAL', 'MANUAL', %s, %s, %s, 0, %s, %s, 'Initial Stock Creation');
            """, (new_id, str(new_id), default_loc, initial_qty, initial_qty, cost_price))

        # Record initial version in product_versions
        execute("""
            INSERT INTO product_versions (product_id, version_number, name, sku, standard_cost, default_price, change_summary)
            VALUES (%s, 1, %s, %s, %s, %s, 'Initial product creation');
        """, (new_id, name, sku, cost_price, default_price))

        flash(f"Product '{name}' ({sku}) created successfully!", "success")
        next_url = request.form.get('next_url')
        if next_url:
            return redirect(next_url)
        if request.form.get('save_and_close') == '1':
            return redirect(url_for('products.list_products'))
        active_tab = request.form.get('active_tab', '')
        return redirect(url_for('products.detail_product', id=new_id, tab=active_tab) if active_tab else url_for('products.detail_product', id=new_id))

    except Exception as e:
        flash(f"Error creating product: {e}", "error")
        return redirect(url_for('products.list_products'))

@products_bp.route('/products/<int:id>/save', methods=['POST'])
@products_bp.route('/products/<int:id>/edit', methods=['POST'])
def edit_product(id):
    try:
        prod = query_one("SELECT * FROM products WHERE id = %s", (id,))
        if not prod:
            flash("Product not found.", "error")
            return redirect(url_for('products.list_products'))

        sku = request.form.get('sku', prod['sku']).strip()
        name = request.form.get('name', prod['name']).strip()
        barcode = request.form.get('barcode', '').strip() or None if 'barcode' in request.form else prod['barcode']
        category_id = request.form.get('category_id') or None if 'category_id' in request.form else prod['category_id']
        if category_id == '':
            category_id = None
        uom = request.form.get('uom', prod['uom']).strip()
        
        # Safely preserve fields not present in simple edit
        description = request.form.get('description', prod['description'] or '').strip() if 'description' in request.form else (prod['description'] or '')
        master_pack = float(request.form.get('master_pack_qty', prod['master_pack_qty']) or prod['master_pack_qty'] or 1.0)
        inner_pack = float(request.form.get('inner_pack_qty', prod['inner_pack_qty']) or prod['inner_pack_qty'] or 1.0)
        
        default_loc = request.form.get('default_location_id') if 'default_location_id' in request.form else prod['default_location_id']
        if default_loc == '':
            default_loc = None

        default_subloc = request.form.get('default_sublocation', prod.get('default_sublocation') or '').strip()
        last_vendor_id = request.form.get('last_vendor_id') if 'last_vendor_id' in request.form else prod.get('last_vendor_id')
        if last_vendor_id == '':
            last_vendor_id = None
        sales_uom = request.form.get('sales_uom', prod.get('sales_uom') or 'cases').strip()
        sales_uom_ratio = float(request.form.get('sales_uom_ratio', prod.get('sales_uom_ratio') or 1) or 1)
        sales_uom_ratio_std = float(request.form.get('sales_uom_ratio_std', prod.get('sales_uom_ratio_std') or 200) or 200)
        # Purchases UOM always equal to Sale UOM no need to fill
        purchasing_uom = sales_uom
        purchasing_uom_ratio = sales_uom_ratio
        purchasing_uom_ratio_std = sales_uom_ratio_std
        
        length_val = safe_eval_math(request.form.get('length')) if request.form.get('length') else prod.get('length')
        width_val = safe_eval_math(request.form.get('width')) if request.form.get('width') else prod.get('width')
        height_val = safe_eval_math(request.form.get('height')) if request.form.get('height') else prod.get('height')
        weight_val = safe_eval_math(request.form.get('weight')) if request.form.get('weight') else prod.get('weight')
        remarks = request.form.get('remarks', prod.get('remarks') or '').strip() if 'remarks' in request.form else prod.get('remarks')

        pcs_per_pack = safe_eval_math(request.form.get('pcs_per_pack', prod.get('pcs_per_pack') or 50))
        sales_ratio = safe_eval_math(request.form.get('sales_uom_ratio_std', prod.get('sales_uom_ratio_std') or 1))
        # Number pack per case should automatically calculate: pcs per case / pcs per pack
        if sales_ratio > 0 and pcs_per_pack > 0:
            packs_per_case = round(sales_ratio / pcs_per_pack, 2)
        else:
            packs_per_case = safe_eval_math(request.form.get('packs_per_case') or prod.get('packs_per_case') or 1)
        tier_qty_1 = int(safe_eval_math(request.form.get('tier_qty_1')) or 100) if request.form.get('tier_qty_1') else prod.get('tier_qty_1')
        tier_qty_2 = int(safe_eval_math(request.form.get('tier_qty_2')) or 0) if request.form.get('tier_qty_2') else prod.get('tier_qty_2')
        tier_qty_3 = int(safe_eval_math(request.form.get('tier_qty_3')) or 0) if request.form.get('tier_qty_3') else prod.get('tier_qty_3')
        if tier_qty_2 == 0:
            tier_qty_2 = None
        if tier_qty_3 == 0:
            tier_qty_3 = None
        if user_can_edit_prices():
            tier_price_1 = safe_eval_math(request.form.get('tier_price_1')) if request.form.get('tier_price_1') else prod.get('tier_price_1')
            tier_price_2 = safe_eval_math(request.form.get('tier_price_2')) if request.form.get('tier_price_2') else prod.get('tier_price_2')
            tier_price_3 = safe_eval_math(request.form.get('tier_price_3')) if request.form.get('tier_price_3') else prod.get('tier_price_3')
            sell_price = safe_eval_math(request.form.get('default_price', prod['default_price']) or 0)
        else:
            tier_price_1 = prod.get('tier_price_1')
            tier_price_2 = prod.get('tier_price_2')
            tier_price_3 = prod.get('tier_price_3')
            sell_price = safe_eval_math(prod.get('default_price') or 0)

        price_card_notes = request.form.get('price_card_notes', prod.get('price_card_notes') or '').strip()

        reorder_pt = float(request.form.get('reorder_point', prod['reorder_point']) or 0)
        reorder_qty = float(request.form.get('reorder_quantity', prod['reorder_quantity']) or 0)
        cost_price = safe_eval_math(request.form.get('cost_price', prod['standard_cost']) or 0)

        item_type = request.form.get('item_type', prod['item_type'] or 'Stockable').strip() if 'item_type' in request.form else (prod['item_type'] or 'Stockable')
        tax_code = request.form.get('tax_code', prod['tax_code'] or 'Taxable').strip() if 'tax_code' in request.form else (prod['tax_code'] or 'Taxable')
        costing_method = request.form.get('costing_method', prod['costing_method'] or 'Manual').strip() if 'costing_method' in request.form else (prod['costing_method'] or 'Manual')
        custom1 = request.form.get('custom1', prod['custom1'] or '') if 'custom1' in request.form else prod['custom1']
        custom2 = request.form.get('custom2', prod['custom2'] or '') if 'custom2' in request.form else prod['custom2']
        custom3 = request.form.get('custom3', prod['custom3'] or '') if 'custom3' in request.form else prod['custom3']
        custom4 = request.form.get('custom4', prod['custom4'] or '') if 'custom4' in request.form else prod['custom4']
        custom5 = request.form.get('custom5', prod['custom5'] or '') if 'custom5' in request.form else prod['custom5']

        # Handle Picture Upload & Clear
        image_url = prod['image_url']
        if request.form.get('clear_picture') == '1':
            image_url = None

        if 'picture' in request.files:
            file = request.files['picture']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    filename = f"prod_{id}_{int(time.time())}.{ext}"
                    save_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'products')
                    os.makedirs(save_dir, exist_ok=True)
                    filepath = os.path.join(save_dir, filename)
                    file.save(filepath)
                    image_url = f"/static/uploads/products/{filename}"

        # Check and update multi-tier prices if submitted (only if authorized)
        if user_can_edit_prices():
            pricing_schemes = query_all("SELECT id, name FROM pricing_schemes WHERE is_active = TRUE")
            for ps in pricing_schemes:
                key = f"scheme_price_{ps['id']}"
                if key in request.form and request.form.get(key) != '':
                    try:
                        scheme_val = safe_eval_math(request.form.get(key))
                        execute("""
                            INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (product_id, pricing_scheme_id)
                            DO UPDATE SET unit_price = EXCLUDED.unit_price;
                        """, (id, ps['id'], scheme_val))
                        if 'retail 1' in ps['name'].lower() or ps['id'] == 100:
                            sell_price = scheme_val
                    except (ValueError, TypeError):
                        pass

        price_dec_raw = request.form.get('price_decimals', '').strip()
        cost_dec_raw = request.form.get('cost_decimals', '').strip()
        qty_dec_raw = request.form.get('qty_decimals', '').strip()
        price_decimals = int(price_dec_raw) if price_dec_raw != '' and price_dec_raw != '-1' else None
        cost_decimals = int(cost_dec_raw) if cost_dec_raw != '' and cost_dec_raw != '-1' else None
        qty_decimals = int(qty_dec_raw) if qty_dec_raw != '' and qty_dec_raw != '-1' else None

        factory_cost = safe_eval_math(request.form.get('factory_cost')) if 'factory_cost' in request.form else prod.get('factory_cost')
        factory_cost_formula = (request.form.get('factory_cost_formula', '').strip() or None) if 'factory_cost_formula' in request.form else prod.get('factory_cost_formula')
        cost_rate = safe_eval_math(request.form.get('cost_rate')) if 'cost_rate' in request.form else prod.get('cost_rate')
        cost_rate_formula = (request.form.get('cost_rate_formula', '').strip() or None) if 'cost_rate_formula' in request.form else prod.get('cost_rate_formula')
        shipping_cost = safe_eval_math(request.form.get('shipping_cost')) if 'shipping_cost' in request.form else prod.get('shipping_cost')
        shipping_cost_formula = (request.form.get('shipping_cost_formula', '').strip() or None) if 'shipping_cost_formula' in request.form else prod.get('shipping_cost_formula')
        costing_sheet_pcs = safe_eval_math(request.form.get('costing_sheet_pcs')) if 'costing_sheet_pcs' in request.form else prod.get('costing_sheet_pcs')
        costing_sheet_pcs_formula = (request.form.get('costing_sheet_pcs_formula', '').strip() or None) if 'costing_sheet_pcs_formula' in request.form else prod.get('costing_sheet_pcs_formula')
        costing_sheet_cost = safe_eval_math(request.form.get('costing_sheet_cost')) if 'costing_sheet_cost' in request.form else prod.get('costing_sheet_cost')
        costing_sheet_formula = (request.form.get('costing_sheet_formula', '').strip() or None) if 'costing_sheet_formula' in request.form else prod.get('costing_sheet_formula')
        cost_formula = (request.form.get('cost_formula', '').strip() or None) if 'cost_formula' in request.form else prod.get('cost_formula')
        combine_type = (request.form.get('combine_type', '').strip() or prod.get('combine_type') or 'single') if 'combine_type' in request.form else (prod.get('combine_type') or 'single')

        # Rule: if costing is empty and costing sheet has calculated value, take value automatically! If have value inside keep it!
        if (cost_price is None or cost_price == 0) and costing_sheet_cost and costing_sheet_cost > 0:
            cost_price = costing_sheet_cost
            if not cost_formula and costing_sheet_formula:
                cost_formula = costing_sheet_formula

        execute("""
            UPDATE products SET
                sku = %s,
                name = %s,
                description = %s,
                barcode = %s,
                category_id = %s,
                uom = %s,
                master_pack_qty = %s,
                inner_pack_qty = %s,
                default_location_id = %s,
                default_sublocation = %s,
                last_vendor_id = %s,
                sales_uom = %s,
                sales_uom_ratio = %s,
                sales_uom_ratio_std = %s,
                purchasing_uom = %s,
                purchasing_uom_ratio = %s,
                purchasing_uom_ratio_std = %s,
                length = %s,
                width = %s,
                height = %s,
                weight = %s,
                remarks = %s,
                reorder_point = %s,
                reorder_quantity = %s,
                standard_cost = %s,
                default_price = %s,
                item_type = %s,
                tax_code = %s,
                costing_method = %s,
                image_url = %s,
                custom1 = %s,
                custom2 = %s,
                custom3 = %s,
                custom4 = %s,
                custom5 = %s,
                price_decimals = %s,
                cost_decimals = %s,
                qty_decimals = %s,
                packs_per_case = %s,
                pcs_per_pack = %s,
                tier_qty_1 = %s,
                tier_qty_2 = %s,
                tier_qty_3 = %s,
                tier_price_1 = %s,
                tier_price_2 = %s,
                tier_price_3 = %s,
                price_card_notes = %s,
                cost_formula = %s,
                factory_cost = %s,
                factory_cost_formula = %s,
                cost_rate = %s,
                cost_rate_formula = %s,
                shipping_cost = %s,
                shipping_cost_formula = %s,
                costing_sheet_pcs = %s,
                costing_sheet_pcs_formula = %s,
                costing_sheet_cost = %s,
                costing_sheet_formula = %s,
                combine_type = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (
            sku, name, description, barcode, category_id, uom,
            master_pack, inner_pack, default_loc,
            default_subloc, last_vendor_id,
            sales_uom, sales_uom_ratio, sales_uom_ratio_std,
            purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
            length_val, width_val, height_val, weight_val, remarks,
            reorder_pt, reorder_qty, cost_price, sell_price,
            item_type, tax_code, costing_method, image_url,
            custom1, custom2, custom3, custom4, custom5,
            price_decimals, cost_decimals, qty_decimals,
            packs_per_case, pcs_per_pack,
            tier_qty_1, tier_qty_2, tier_qty_3,
            tier_price_1, tier_price_2, tier_price_3,
            price_card_notes,
            cost_formula, factory_cost, factory_cost_formula,
            cost_rate, cost_rate_formula,
            shipping_cost, shipping_cost_formula,
            costing_sheet_pcs, costing_sheet_pcs_formula,
            costing_sheet_cost, costing_sheet_formula,
            combine_type,
            id
        ))
        update_parent_boms_cost(id)

        # Handle Bill of Materials additions/updates
        has_bom_submitted = 'bom_submitted' in request.form
        bom_comp_ids = request.form.getlist('bom_component_id[]')
        bom_quantities = request.form.getlist('bom_quantity[]')
        new_bom_comp = request.form.get('new_bom_component_id')
        new_bom_qty = request.form.get('new_bom_quantity', 1)

        if new_bom_comp and str(new_bom_comp).strip() and str(new_bom_comp).strip().isdigit():
            c_id_str = str(new_bom_comp).strip()
            if c_id_str not in [str(x).strip() for x in bom_comp_ids]:
                bom_comp_ids.append(c_id_str)
                bom_quantities.append(new_bom_qty or 1)

        if bom_comp_ids:
            execute("DELETE FROM product_boms WHERE product_id = %s", (id,))
            for idx, c_id_raw in enumerate(bom_comp_ids):
                try:
                    c_id = int(c_id_raw)
                    b_qty = float(bom_quantities[idx] if idx < len(bom_quantities) else 1) or 1.0
                    comp_prod = query_one("SELECT description, standard_cost FROM products WHERE id = %s", (c_id,))
                    if comp_prod and c_id != id:
                        execute("""
                            INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
                            VALUES (%s, %s, %s, %s, %s);
                        """, (id, c_id, comp_prod.get('description') or '', b_qty, float(comp_prod.get('standard_cost') or 0)))
                except (ValueError, TypeError):
                    pass
            recalc_product_bom_cost(id)
        elif has_bom_submitted:
            # User cleared all BOM items
            execute("DELETE FROM product_boms WHERE product_id = %s", (id,))
            recalc_product_bom_cost(id)

        # Update inventory stock levels per location if edited
        locations = query_all("SELECT id, name FROM locations WHERE is_active = TRUE")
        for loc in locations:
            stock_key = f"stock_qty_{loc['id']}"
            if stock_key in request.form and request.form.get(stock_key) != '':
                try:
                    raw_val = request.form.get(stock_key).replace(',', '')
                    new_qty = float(raw_val)
                    cur_stock = query_one("SELECT quantity FROM inventory WHERE product_id = %s AND location_id = %s AND sublocation = ''", (id, loc['id']))
                    old_qty = float(cur_stock['quantity']) if cur_stock else 0.0
                    
                    if cur_stock is None:
                        execute("""
                            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                            VALUES (%s, %s, '', %s);
                        """, (id, loc['id'], new_qty))
                    elif new_qty != old_qty:
                        execute("""
                            UPDATE inventory SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE product_id = %s AND location_id = %s AND sublocation = '';
                        """, (new_qty, id, loc['id']))

                    if new_qty != old_qty:
                        diff = new_qty - old_qty
                        execute("""
                            INSERT INTO inventory_logs (
                                product_id, movement_type, reference_type, reference_id,
                                to_location_id, quantity, qty_before, qty_after, unit_cost, reason
                            ) VALUES (%s, 'ADJUSTMENT', 'MANUAL', %s, %s, %s, %s, %s, %s, 'Direct edit on product screen');
                        """, (id, str(id), loc['id'], diff, old_qty, new_qty, cost_price))
                except (ValueError, TypeError):
                    pass

        # Record new version in product_versions
        max_ver = query_one("SELECT COALESCE(MAX(version_number), 0) as mv FROM product_versions WHERE product_id = %s", (id,))['mv']
        execute("""
            INSERT INTO product_versions (product_id, version_number, name, sku, standard_cost, default_price, change_summary)
            VALUES (%s, %s, %s, %s, %s, %s, 'Product specifications and pricing saved in-place');
        """, (id, max_ver + 1, name, sku, cost_price, sell_price))

        flash("Product saved successfully!", "success")
        next_url = request.form.get('next_url')
        if next_url:
            return redirect(next_url)
        if request.form.get('save_and_close') == '1':
            return redirect(url_for('products.list_products'))
        active_tab = request.form.get('active_tab', '')
        return redirect(url_for('products.detail_product', id=id, tab=active_tab) if active_tab else url_for('products.detail_product', id=id))

    except Exception as e:
        flash(f"Error updating product: {e}", "error")
        return redirect(url_for('products.detail_product', id=id))

@products_bp.route('/products/<int:id>/copy', methods=['GET', 'POST'])
def copy_product(id):
    try:
        source = query_one("SELECT * FROM products WHERE id = %s", (id,))
        if not source:
            flash("Original product not found.", "error")
            return redirect(url_for('products.list_products'))

        # Generate unique SKU based on original SKU
        next_id = query_one("SELECT COALESCE(MAX(id), 0) + 1 as nid FROM products")['nid']
        base_sku = (source['sku'] or '').strip()
        if base_sku:
            candidate_sku = f"{base_sku}-Copy"
            suffix = 2
            while query_one("SELECT id FROM products WHERE sku = %s", (candidate_sku,)):
                candidate_sku = f"{base_sku}-Copy-{suffix}"
                suffix += 1
        else:
            candidate_sku = f"SKU-{next_id:04d}"
            suffix = 2
            while query_one("SELECT id FROM products WHERE sku = %s", (candidate_sku,)):
                candidate_sku = f"SKU-{next_id:04d}-{suffix}"
                suffix += 1

        new_name = f"{source['name']} - Copy"

        # Dynamically query all table columns to ensure 100% exact copy of all product specs,
        # dimensions, packaging, UOMs, price card, tiers, and costing sheet formulas
        cols_info = query_all("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'products'
            ORDER BY ordinal_position
        """)
        cols_to_copy = [c['column_name'] for c in cols_info if c['column_name'] not in ('id', 'created_at', 'updated_at')]

        from psycopg2.extras import Json
        insert_cols = []
        insert_placeholders = []
        insert_vals = []

        for col in cols_to_copy:
            insert_cols.append(col)
            insert_placeholders.append('%s')
            if col == 'sku':
                insert_vals.append(candidate_sku)
            elif col == 'name':
                insert_vals.append(new_name)
            else:
                val = source.get(col)
                if isinstance(val, dict):
                    val = Json(val)
                insert_vals.append(val)

        sql_insert = f"""
            INSERT INTO products ({', '.join(insert_cols)})
            VALUES ({', '.join(insert_placeholders)})
            RETURNING id;
        """
        new_id = execute_returning_id(sql_insert, tuple(insert_vals))

        # Copy combine options if multi product (including selling_price)
        source_options = query_all("SELECT * FROM product_combine_options WHERE product_id = %s ORDER BY sort_order ASC, id ASC", (id,))
        for so in source_options:
            execute("""
                INSERT INTO product_combine_options (
                    product_id, option_name, component_product_id, component_quantity,
                    price_modifier, selling_price, is_default, sort_order, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (new_id, so['option_name'], so['component_product_id'], so['component_quantity'],
                  so.get('price_modifier'), so.get('selling_price'), so.get('is_default', False), so.get('sort_order', 0), so.get('notes')))

        # Copy price tiers (product_prices)
        source_prices = query_all("SELECT pricing_scheme_id, unit_price FROM product_prices WHERE product_id = %s", (id,))
        for sp in source_prices:
            execute("""
                INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                VALUES (%s, %s, %s)
                ON CONFLICT (product_id, pricing_scheme_id) DO UPDATE SET unit_price = EXCLUDED.unit_price;
            """, (new_id, sp['pricing_scheme_id'], sp['unit_price']))

        # Copy vendor mappings (product_vendors)
        source_vendors = query_all("SELECT vendor_id, vendor_item_code, cost FROM product_vendors WHERE product_id = %s", (id,))
        for sv in source_vendors:
            execute("""
                INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (product_id, vendor_id) DO UPDATE SET cost = EXCLUDED.cost, vendor_item_code = EXCLUDED.vendor_item_code;
            """, (new_id, sv['vendor_id'], sv['vendor_item_code'], sv['cost']))

        # Copy Bill of Materials components (product_boms)
        source_boms = query_all("SELECT component_product_id, description, quantity, cost FROM product_boms WHERE product_id = %s ORDER BY id ASC", (id,))
        for sb in source_boms:
            execute("""
                INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
                VALUES (%s, %s, %s, %s, %s)
            """, (new_id, sb['component_product_id'], sb['description'], sb['quantity'], sb['cost']))

        # Copy product attachments (product_attachments)
        source_attachments = query_all("SELECT file_name, file_path, file_size FROM product_attachments WHERE product_id = %s ORDER BY id ASC", (id,))
        for sa in source_attachments:
            execute("""
                INSERT INTO product_attachments (product_id, file_name, file_path, file_size)
                VALUES (%s, %s, %s, %s)
            """, (new_id, sa['file_name'], sa['file_path'], sa['file_size']))

        # Record initial version in product_versions
        execute("""
            INSERT INTO product_versions (product_id, version_number, name, sku, standard_cost, default_price, change_summary)
            VALUES (%s, 1, %s, %s, %s, %s, %s);
        """, (new_id, new_name, candidate_sku, source['standard_cost'] or 0, source['default_price'] or 0, f"Duplicated from {source['sku'] or source['name']}"))

        flash(f"Product '{new_name}' ({candidate_sku}) duplicated successfully with all specifications and pricing!", "success")
        return redirect(url_for('products.detail_product', id=new_id))

    except Exception as e:
        flash(f"Error copying product: {e}", "error")
        return redirect(url_for('products.detail_product', id=id))

@products_bp.route('/products/<int:id>/attachments/upload', methods=['POST'])
def upload_attachment(id):
    if 'attachment_file' in request.files:
        f = request.files['attachment_file']
        if f and f.filename:
            orig_name = f.filename
            safe_name = f"{int(time.time())}_{secure_filename(orig_name)}"
            attach_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'attachments')
            os.makedirs(attach_dir, exist_ok=True)
            fpath = os.path.join(attach_dir, safe_name)
            f.save(fpath)
            fsize = os.path.getsize(fpath)
            url_path = f"/static/uploads/attachments/{safe_name}"
            execute("""
                INSERT INTO product_attachments (product_id, file_name, file_path, file_size)
                VALUES (%s, %s, %s, %s)
            """, (id, orig_name, url_path, fsize))
            flash(f"Attachment '{orig_name}' uploaded successfully!", "success")
    return redirect(url_for('products.detail_product', id=id))

@products_bp.route('/products/<int:id>/attachments/<int:att_id>/delete', methods=['POST'])
def delete_attachment(id, att_id):
    execute("DELETE FROM product_attachments WHERE id = %s AND product_id = %s", (att_id, id))
    flash("Attachment removed.", "success")
    return redirect(url_for('products.detail_product', id=id))

@products_bp.route('/products/<int:id>/toggle-status', methods=['POST'])
def toggle_product_status(id):
    prod = query_one("SELECT is_active, name FROM products WHERE id = %s", (id,))
    if prod:
        new_status = not prod['is_active']
        execute("UPDATE products SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_status, id))
        action = "activated" if new_status else "archived"
        flash(f"Product '{prod['name']}' has been {action}.", "success")
    return redirect(url_for('products.detail_product', id=id))

@products_bp.route('/products/<int:id>/versions')
def get_product_versions(id):
    versions = query_all("""
        SELECT id, product_id, version_number, name, sku, standard_cost, default_price, change_summary,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM product_versions
        WHERE product_id = %s
        ORDER BY version_number DESC, created_at DESC
    """, (id,))
    return jsonify([dict(v) for v in versions])

# ==========================================================================
# PRODUCT CATEGORIES MANAGEMENT (FULL CRUD)
# ==========================================================================
@products_bp.route('/categories', methods=['GET'])
def list_categories():
    status = request.args.get('status', 'all')
    search = request.args.get('q', '').strip()

    where_clauses = []
    params = []

    if status == 'active':
        where_clauses.append("c.is_active = TRUE")
    elif status == 'inactive':
        where_clauses.append("c.is_active = FALSE")

    if search:
        where_clauses.append("(c.name ILIKE %s OR c.description ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT 
            c.id, c.name, c.description, COALESCE(c.color, '#00A3E0') as color,
            COALESCE(c.price_table_style, 'classic') as price_table_style,
            c.is_active, c.created_at,
            COUNT(p.id) as product_count
        FROM categories c
        LEFT JOIN products p ON c.id = p.category_id AND p.is_active = TRUE
        {where_sql}
        GROUP BY c.id, c.name, c.description, c.color, c.price_table_style, c.is_active, c.created_at
        ORDER BY c.name ASC
    """
    categories = query_all(query, tuple(params))

    # Overall stats for metric cards
    total_categories = query_one("SELECT COUNT(*) as cnt FROM categories")['cnt']
    active_categories = query_one("SELECT COUNT(*) as cnt FROM categories WHERE is_active = TRUE")['cnt']
    categorized_products = query_one("SELECT COUNT(*) as cnt FROM products WHERE category_id IS NOT NULL AND is_active = TRUE")['cnt']
    uncategorized_products = query_one("SELECT COUNT(*) as cnt FROM products WHERE category_id IS NULL AND is_active = TRUE")['cnt']

    # Global price table style setting
    global_setting = query_one("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style'")
    global_price_table_style = (global_setting['setting_value'] if global_setting and global_setting.get('setting_value') else 'classic').lower()
    if global_price_table_style not in ('classic', 'modern'):
        global_price_table_style = 'classic'

    return render_template(
        'products/categories.html',
        categories=categories,
        status_filter=status,
        search_query=search,
        total_categories=total_categories,
        active_categories=active_categories,
        categorized_products=categorized_products,
        uncategorized_products=uncategorized_products,
        global_price_table_style=global_price_table_style
    )

@products_bp.route('/categories/create', methods=['POST'])
def create_category():
    name = request.form.get('name', '').strip()
    color = request.form.get('color', '#00A3E0').strip()
    description = request.form.get('description', '').strip()
    price_table_style = (request.form.get('price_table_style') or 'classic').strip().lower()
    if price_table_style not in ('classic', 'modern'):
        price_table_style = 'classic'
    is_active = request.form.get('is_active') in ('1', 'true', 'on', 'yes') if 'is_active' in request.form else True

    if not name:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': 'Category name is required.'}), 400
        flash("Category name is required.", "error")
        return redirect(url_for('products.list_categories'))

    # Check for duplicate category name
    existing = query_one("SELECT id FROM categories WHERE LOWER(name) = LOWER(%s)", (name,))
    if existing:
        msg = f"A category named '{name}' already exists."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('products.list_categories'))

    try:
        cat_id = execute_returning_id("""
            INSERT INTO categories (name, color, description, is_active, price_table_style)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (name, color, description, is_active, price_table_style))

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                'success': True,
                'message': f"Category '{name}' created successfully!",
                'category': {'id': cat_id, 'name': name, 'color': color, 'price_table_style': price_table_style}
            })
        flash(f"Category '{name}' created successfully!", "success")
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error creating category: {e}", "error")

    return redirect(url_for('products.list_categories'))

@products_bp.route('/categories/<int:id>/edit', methods=['POST'])
def edit_category(id):
    name = request.form.get('name', '').strip()
    color = request.form.get('color', '#00A3E0').strip()
    description = request.form.get('description', '').strip()
    price_table_style = (request.form.get('price_table_style') or 'classic').strip().lower()
    if price_table_style not in ('classic', 'modern'):
        price_table_style = 'classic'
    is_active = request.form.get('is_active') in ('1', 'true', 'on', 'yes') if 'is_active' in request.form else True

    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for('products.list_categories'))

    dup = query_one("SELECT id FROM categories WHERE LOWER(name) = LOWER(%s) AND id != %s", (name, id))
    if dup:
        flash(f"Another category named '{name}' already exists.", "error")
        return redirect(url_for('products.list_categories'))

    try:
        execute("""
            UPDATE categories 
            SET name = %s, color = %s, description = %s, is_active = %s, price_table_style = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (name, color, description, is_active, price_table_style, id))
        flash(f"Category '{name}' updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating category: {e}", "error")

    return redirect(url_for('products.list_categories'))

@products_bp.route('/categories/<int:id>/delete', methods=['POST'])
def delete_category(id):
    cat = query_one("SELECT name FROM categories WHERE id = %s", (id,))
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for('products.list_categories'))

    try:
        prod_count = query_one("SELECT COUNT(*) as cnt FROM products WHERE category_id = %s", (id,))['cnt']
        if prod_count > 0:
            execute("UPDATE products SET category_id = NULL WHERE category_id = %s", (id,))

        execute("DELETE FROM categories WHERE id = %s", (id,))
        if prod_count > 0:
            flash(f"Category '{cat['name']}' deleted. ({prod_count} product(s) reassigned to Uncategorized)", "success")
        else:
            flash(f"Category '{cat['name']}' deleted successfully!", "success")
    except Exception as e:
        flash(f"Error deleting category: {e}", "error")

    return redirect(url_for('products.list_categories'))

@products_bp.route('/categories/<int:id>/toggle_active', methods=['POST'])
def toggle_active_category(id):
    cat = query_one("SELECT name, is_active FROM categories WHERE id = %s", (id,))
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for('products.list_categories'))

    new_status = not cat['is_active']
    execute("UPDATE categories SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, id))
    action_text = "activated" if new_status else "deactivated"
    flash(f"Category '{cat['name']}' {action_text} successfully!", "success")
    return redirect(url_for('products.list_categories'))

@products_bp.route('/api/categories/<int:id>/set-style', methods=['POST'])
def api_set_category_style(id):
    """
    Sets price table style ('classic' or 'modern') for a single category.
    """
    data = request.get_json(silent=True) or request.form
    style = (data.get('style') or 'classic').strip().lower()
    if style not in ('classic', 'modern'):
        return jsonify({'success': False, 'message': 'Style must be either "classic" or "modern".'}), 400

    cat = query_one("SELECT id, name FROM categories WHERE id = %s", (id,))
    if not cat:
        return jsonify({'success': False, 'message': 'Category not found.'}), 404

    execute("UPDATE categories SET price_table_style = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (style, id))
    return jsonify({
        'success': True,
        'category_id': id,
        'category_name': cat['name'],
        'style': style,
        'message': f"Category '{cat['name']}' price table style set to {style.capitalize()}."
    })

@products_bp.route('/api/categories/set-all-style', methods=['POST'])
def api_set_all_categories_style():
    """
    Sets price table style ('classic' or 'modern') for ALL categories and updates default_price_table_style.
    """
    data = request.get_json(silent=True) or request.form
    style = (data.get('style') or 'classic').strip().lower()
    if style not in ('classic', 'modern'):
        return jsonify({'success': False, 'message': 'Style must be either "classic" or "modern".'}), 400

    count = execute("UPDATE categories SET price_table_style = %s, updated_at = CURRENT_TIMESTAMP", (style,))
    execute("""
        INSERT INTO app_settings (setting_key, setting_value, description, updated_at)
        VALUES ('default_price_table_style', %s, 'Default style for product price cards (classic or modern)', CURRENT_TIMESTAMP)
        ON CONFLICT (setting_key)
        DO UPDATE SET setting_value = EXCLUDED.setting_value, updated_at = CURRENT_TIMESTAMP;
    """, (style,))

    return jsonify({
        'success': True,
        'style': style,
        'updated_count': count,
        'message': f"All {count} categories and products set to {style.capitalize()} style."
    })

@products_bp.route('/api/categories', methods=['GET'])
def api_get_categories():
    cats = query_all("SELECT id, name, COALESCE(color, '#00A3E0') as color, COALESCE(price_table_style, 'classic') as price_table_style, description, is_active FROM categories WHERE is_active = TRUE ORDER BY name ASC")
    return jsonify([dict(c) for c in cats])

@products_bp.route('/api/products/search')
def search_products_json():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    param = f"%{query}%"
    results = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.uom, p.default_price, p.average_cost,
            p.last_purchase_cost, p.standard_cost,
            COALESCE(p.last_purchase_cost, p.average_cost, p.standard_cost, 0) as purchase_cost,
            COALESCE(inv.total_qty, 0) as on_hand
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE p.is_active = TRUE AND (p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)
        ORDER BY p.name ASC
        LIMIT 25
    """, (param, param, param))

    return jsonify([dict(r) for r in results])

@products_bp.route('/api/pricing-schemes', methods=['GET'])
def get_pricing_schemes():
    show_all = request.args.get('all', 'false').lower() in ('true', '1')
    if show_all:
        schemes = query_all("""
            SELECT id, name, COALESCE(currency, 'US Dollar ($)') as currency, is_active, is_default
            FROM pricing_schemes
            ORDER BY id ASC
        """)
    else:
        schemes = query_all("""
            SELECT id, name, COALESCE(currency, 'US Dollar ($)') as currency, is_active, is_default
            FROM pricing_schemes
            WHERE is_active = TRUE
            ORDER BY id ASC
        """)
    return jsonify({'success': True, 'schemes': [dict(s) for s in schemes]})

@products_bp.route('/api/pricing-schemes/batch', methods=['POST'])
def save_pricing_schemes_batch():
    if not user_can_edit_prices():
        return jsonify({'success': False, 'message': 'Permission denied: Editing pricing schemes is disabled.'}), 403
    try:
        data = request.get_json(force=True) or {}
        schemes = data.get('schemes', [])
        deleted_ids = data.get('deleted_ids', [])

        # Process deleted schemes: set is_active = FALSE
        for del_id in deleted_ids:
            try:
                del_id = int(del_id)
                execute("UPDATE pricing_schemes SET is_active = FALSE WHERE id = %s", (del_id,))
            except Exception as e:
                print(f"Error deactivating pricing scheme {del_id}: {e}")

        # Process schemes to insert or update
        for item in schemes:
            s_id = item.get('id')
            name = (item.get('name') or '').strip()
            currency = (item.get('currency') or 'US Dollar ($)').strip()
            is_active = bool(item.get('is_active', True))

            if not name:
                continue

            if s_id and int(s_id) > 0:
                execute("""
                    UPDATE pricing_schemes 
                    SET name = %s, currency = %s, is_active = %s
                    WHERE id = %s
                """, (name, currency, is_active, int(s_id)))
            else:
                execute("""
                    INSERT INTO pricing_schemes (name, currency, is_active, is_default)
                    VALUES (%s, %s, %s, FALSE)
                """, (name, currency, is_active))

        active_schemes = query_all("""
            SELECT id, name, COALESCE(currency, 'US Dollar ($)') as currency, is_active, is_default
            FROM pricing_schemes
            WHERE is_active = TRUE
            ORDER BY id ASC
        """)
        all_schemes = query_all("""
            SELECT id, name, COALESCE(currency, 'US Dollar ($)') as currency, is_active, is_default
            FROM pricing_schemes
            ORDER BY id ASC
        """)

        return jsonify({
            'success': True,
            'message': 'Pricing schemes saved successfully.',
            'active_schemes': [dict(s) for s in active_schemes],
            'all_schemes': [dict(s) for s in all_schemes]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/pricing-schemes/<int:id>/delete', methods=['POST'])
def delete_pricing_scheme(id):
    if not user_can_edit_prices():
        return jsonify({'success': False, 'message': 'Permission denied: Editing pricing schemes is disabled.'}), 403
    try:
        execute("UPDATE pricing_schemes SET is_active = FALSE WHERE id = %s", (id,))
        return jsonify({'success': True, 'message': 'Pricing scheme deleted.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@products_bp.route('/api/products/price-cards-data', methods=['GET'])
def api_get_price_cards_data():
    try:
        category_id = request.args.get('category_id')
        export_all = request.args.get('all') == '1'
        
        query = """
            SELECT 
                p.*,
                COALESCE(c.name, 'General') as category_name,
                COALESCE(c.color, '#00A3E0') as category_color
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active = TRUE
        """
        params = []
        if not export_all and category_id:
            query += " AND p.category_id = %s"
            params.append(int(category_id))
            
        query += " ORDER BY c.name ASC, p.name ASC, p.id ASC"
        
        products = query_all(query, tuple(params))
        if not products:
            return jsonify({'success': False, 'message': 'No products found', 'items': [], 'count': 0})
            
        p_ids = [p['id'] for p in products]
        tiers_by_pid = {}
        if p_ids:
            all_tiers = query_all("""
                SELECT 
                    pp.product_id,
                    ps.id as pricing_scheme_id, ps.name as scheme_name,
                    pp.unit_price
                FROM product_prices pp
                JOIN pricing_schemes ps ON pp.pricing_scheme_id = ps.id
                WHERE pp.product_id = ANY(%s) AND ps.is_active = TRUE
                ORDER BY ps.is_default DESC, ps.id ASC
            """, (p_ids,))
            for t in all_tiers:
                tiers_by_pid.setdefault(t['product_id'], []).append(t)
                
        items = []
        for prod in products:
            p_tiers = tiers_by_pid.get(prod['id'], [])
            card_data = _build_price_card_data(prod, p_tiers)
            items.append({
                'id': prod['id'],
                'sku': prod.get('sku') or '',
                'name': prod.get('name') or '',
                'category_id': prod.get('category_id'),
                'category_name': prod.get('category_name') or 'General',
                'image_url': prod.get('image_url') or '',
                'card': card_data
            })
            
        cat_name = 'All_Products'
        if category_id and not export_all and products:
            cat_name = products[0].get('category_name') or f"Category_{category_id}"
            
        return jsonify({
            'success': True,
            'category_name': cat_name,
            'count': len(items),
            'items': items
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'items': []}), 400


# ==============================================================================
# MULTI-COMBINE PRODUCTS & VARIANT OPTIONS API (e.g. Bowls with Lids)
# ==============================================================================

@products_bp.route('/api/products/<int:id>/combine-type', methods=['POST'])
def api_set_combine_type(id):
    """Update product combine_type: 'single' (Default) or 'multi' (Multi Combine / With Options)"""
    data = request.get_json() or {}
    c_type = data.get('combine_type', 'single')
    if c_type not in ('single', 'multi'):
        c_type = 'single'
    execute("UPDATE products SET combine_type = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (c_type, id))
    return jsonify({'success': True, 'combine_type': c_type})


@products_bp.route('/api/products/<int:id>/combine-options', methods=['GET'])
def api_get_combine_options(id):
    """Retrieve all combine options and components for a product"""
    prod = query_one("SELECT id, name, sku, default_price, combine_type FROM products WHERE id = %s", (id,))
    if not prod:
        return jsonify({'success': False, 'message': 'Product not found'}), 404
        
    options = query_all("""
        SELECT pco.*, 
               p.name as component_name, p.sku as component_sku, p.uom as component_uom,
               p.default_price as component_default_price,
               COALESCE(inv.total_qty, 0) as component_stock
        FROM product_combine_options pco
        LEFT JOIN products p ON pco.component_product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE pco.product_id = %s
        ORDER BY pco.sort_order ASC, pco.id ASC
    """, (id,))
    
    return jsonify({
        'success': True,
        'product': prod,
        'combine_type': prod.get('combine_type') or 'single',
        'options': options
    })


@products_bp.route('/api/products/<int:id>/combine-options', methods=['POST'])
def api_add_combine_option(id):
    """Add a new combine option / add-on component to a product"""
    data = request.get_json() or {}
    opt_name = (data.get('option_name') or '').strip()
    if not opt_name:
        return jsonify({'success': False, 'message': 'Option name is required'}), 400

    comp_id = data.get('component_product_id')
    comp_id = int(comp_id) if comp_id else None
    comp_qty = float(data.get('component_quantity') or 1.0)
    price_mod = float(data.get('price_modifier') or 0.0)
    selling_p = float(data.get('selling_price') or 0.0)
    is_def = bool(data.get('is_default'))
    notes = (data.get('notes') or '').strip()

    if is_def:
        execute("UPDATE product_combine_options SET is_default = FALSE WHERE product_id = %s", (id,))

    new_id = execute_returning_id("""
        INSERT INTO product_combine_options (
            product_id, option_name, component_product_id, component_quantity,
            price_modifier, selling_price, is_default, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (id, opt_name, comp_id, comp_qty, price_mod, selling_p, is_def, notes))

    # Ensure product is marked as multi combine
    execute("UPDATE products SET combine_type = 'multi', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))

    return jsonify({'success': True, 'id': new_id, 'message': 'Option added successfully'})


@products_bp.route('/api/products/<int:id>/combine-options/<int:option_id>', methods=['PUT', 'POST'])
def api_update_combine_option(id, option_id):
    """Update an existing combine option"""
    data = request.get_json() or {}
    opt_name = (data.get('option_name') or '').strip()
    if not opt_name:
        return jsonify({'success': False, 'message': 'Option name is required'}), 400

    comp_id = data.get('component_product_id')
    comp_id = int(comp_id) if comp_id else None
    comp_qty = float(data.get('component_quantity') or 1.0)
    price_mod = float(data.get('price_modifier') or 0.0)
    selling_p = float(data.get('selling_price') or 0.0)
    is_def = bool(data.get('is_default'))
    notes = (data.get('notes') or '').strip()

    if is_def:
        execute("UPDATE product_combine_options SET is_default = FALSE WHERE product_id = %s", (id,))

    execute("""
        UPDATE product_combine_options SET
            option_name = %s, component_product_id = %s, component_quantity = %s,
            price_modifier = %s, selling_price = %s, is_default = %s, notes = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND product_id = %s;
    """, (opt_name, comp_id, comp_qty, price_mod, selling_p, is_def, notes, option_id, id))

    return jsonify({'success': True, 'message': 'Option updated successfully'})


@products_bp.route('/api/products/<int:id>/combine-options/<int:option_id>', methods=['DELETE'])
def api_delete_combine_option(id, option_id):
    """Delete a combine option"""
    execute("DELETE FROM product_combine_options WHERE id = %s AND product_id = %s", (option_id, id))
    rem = query_one("SELECT COUNT(*) as cnt FROM product_combine_options WHERE product_id = %s", (id,))
    if rem and rem['cnt'] == 0:
        execute("UPDATE products SET combine_type = 'single', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
    return jsonify({'success': True, 'message': 'Option deleted'})


@products_bp.route('/api/products/<int:id>/preset-lid-options', methods=['POST'])
def api_preset_lid_options(id):
    """Auto-populate standard 3 packaging options (Without Lid, Flat Lid, Clear PET Lid)"""
    prod = query_one("SELECT id, name, sku, default_price FROM products WHERE id = %s", (id,))
    if not prod:
        return jsonify({'success': False, 'message': 'Product not found'}), 404

    base_price = float(prod.get('default_price') or 0.0)

    # Search for matching flat lid and clear pet lid in database
    flat_lid = query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%flat%lid%', '%flat%lid%')) \
               or query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%គម្រប%សំប៉ែត%', '%គម្រប%សំប៉ែត%')) \
               or query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%lid%', '%lid%'))

    pet_lid = query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%pet%lid%', '%pet%lid%')) \
              or query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%clear%lid%', '%clear%lid%')) \
              or query_one("SELECT id, name, default_price FROM products WHERE is_active = TRUE AND (name ILIKE %s OR sku ILIKE %s) LIMIT 1", ('%គម្រប%ថ្លា%', '%គម្រប%ថ្លា%'))

    flat_mod = float(flat_lid['default_price'] or 0.02) if flat_lid else 0.02
    pet_mod = float(pet_lid['default_price'] or 0.04) if pet_lid else 0.04

    # 1. Option 1: Without Lid
    execute("""
        INSERT INTO product_combine_options (product_id, option_name, component_product_id, component_quantity, price_modifier, selling_price, is_default, sort_order, notes)
        VALUES (%s, 'Without Lid (អត់គម្រប)', NULL, 0, 0.0, %s, TRUE, 1, 'Base product only')
        ON CONFLICT DO NOTHING;
    """, (id, base_price))

    # 2. Option 2: With Flat Lid
    execute("""
        INSERT INTO product_combine_options (product_id, option_name, component_product_id, component_quantity, price_modifier, selling_price, is_default, sort_order, notes)
        VALUES (%s, 'With Flat Lid (គម្របសំប៉ែត)', %s, 1.0, %s, %s, FALSE, 2, 'Combined with standard flat lid')
        ON CONFLICT DO NOTHING;
    """, (id, flat_lid['id'] if flat_lid else None, flat_mod, base_price + flat_mod))

    # 3. Option 3: With Clear PET Lid
    execute("""
        INSERT INTO product_combine_options (product_id, option_name, component_product_id, component_quantity, price_modifier, selling_price, is_default, sort_order, notes)
        VALUES (%s, 'With Clear PET Lid (គម្រប PET ថ្លា)', %s, 1.0, %s, %s, FALSE, 3, 'Combined with premium clear PET dome/flat lid')
        ON CONFLICT DO NOTHING;
    """, (id, pet_lid['id'] if pet_lid else None, pet_mod, base_price + pet_mod))

    execute("UPDATE products SET combine_type = 'multi', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (id,))
    return jsonify({'success': True, 'message': 'Standard 3 lid options generated successfully'})


# ==============================================================================
# COMBINED / BOM (BILL OF MATERIALS) KIT ENDPOINTS
# ==============================================================================

@products_bp.route('/products/<int:id>/boms', methods=['GET'])
def get_product_boms(id):
    boms = query_all("""
        SELECT pb.id, pb.component_product_id, p.name as component_name, p.sku as component_sku,
               p.image_url as component_image_url,
               COALESCE(pb.description, p.description, '') as description,
               pb.quantity, 
               COALESCE(p.standard_cost, pb.cost, 0) as cost,
               ROUND(pb.quantity * COALESCE(p.standard_cost, pb.cost, 0), 4) as subtotal_cost,
               COALESCE((SELECT SUM(quantity) FROM inventory WHERE product_id = pb.component_product_id), 0) as component_stock
        FROM product_boms pb
        LEFT JOIN products p ON pb.component_product_id = p.id
        WHERE pb.product_id = %s
        ORDER BY pb.id ASC
    """, (id,))
    
    total_cost = 0.0
    available_bundle_qty = 999999999 if boms else 0
    bottleneck_component = None

    for b in boms:
        b_cost = float(b.get('cost') or 0.0)
        b_qty = float(b.get('quantity') or 1.0)
        b_sub = round(b_cost * b_qty, 4)
        b['subtotal_cost'] = b_sub
        total_cost += b_sub

        c_stock = float(b.get('component_stock') or 0.0)
        possible = int(c_stock // b_qty) if b_qty > 0 else 0
        b['max_kits_possible'] = max(0, possible)
        if possible < available_bundle_qty:
            available_bundle_qty = max(0, possible)
            bottleneck_component = b

    total_cost = round(total_cost, 4)
    if boms:
        execute("UPDATE products SET standard_cost = %s, average_cost = %s, combine_type = 'multi', cost_formula = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (total_cost, total_cost, id))
    else:
        available_bundle_qty = 0

    return jsonify({
        'success': True,
        'boms': boms,
        'total_cost': total_cost,
        'available_kits': available_bundle_qty,
        'available_bundle_qty': available_bundle_qty,
        'bottleneck_component': bottleneck_component
    })

@products_bp.route('/products/<int:id>/boms/add', methods=['POST'])
def add_product_bom_component(id):
    try:
        data = request.get_json(silent=True) or request.form
        comp_id = data.get('component_product_id')
        if not comp_id:
            return jsonify({'success': False, 'message': 'Component product is required'}), 400
        
        comp_id = int(comp_id)
        if comp_id == id:
            return jsonify({'success': False, 'message': 'A product cannot be added as a component of itself'}), 400

        qty = max(0.0001, float(data.get('quantity') or 1.0))
        
        comp_prod = query_one("SELECT id, name, sku, standard_cost, description FROM products WHERE id = %s", (comp_id,))
        if not comp_prod:
            return jsonify({'success': False, 'message': 'Component product not found'}), 404

        comp_cost = float(comp_prod.get('standard_cost') or 0.0)
        desc = (data.get('description') or comp_prod.get('description') or '').strip()

        # Check if already present in product_boms
        existing = query_one("SELECT id, quantity FROM product_boms WHERE product_id = %s AND component_product_id = %s", (id, comp_id))
        if existing:
            new_qty = float(existing['quantity']) + qty
            execute("UPDATE product_boms SET quantity = %s, cost = %s, description = %s WHERE id = %s", (new_qty, comp_cost, desc, existing['id']))
        else:
            execute("""
                INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
                VALUES (%s, %s, %s, %s, %s)
            """, (id, comp_id, desc, qty, comp_cost))

        total_cost = recalc_product_bom_cost(id)
        return jsonify({
            'success': True,
            'message': f"Added '{comp_prod['name']}' to kit successfully",
            'total_cost': total_cost
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@products_bp.route('/products/<int:id>/boms/<int:bom_id>/delete', methods=['POST'])
def delete_product_bom_component(id, bom_id):
    try:
        execute("DELETE FROM product_boms WHERE id = %s AND product_id = %s", (bom_id, id))
        total_cost = recalc_product_bom_cost(id)
        return jsonify({
            'success': True,
            'message': 'Component removed from kit',
            'total_cost': total_cost
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@products_bp.route('/products/<int:id>/boms/<int:bom_id>/update', methods=['POST'])
def update_product_bom_component(id, bom_id):
    try:
        data = request.get_json(silent=True) or request.form
        qty = max(0.0001, float(data.get('quantity') or 1.0))
        execute("UPDATE product_boms SET quantity = %s WHERE id = %s AND product_id = %s", (qty, bom_id, id))
        total_cost = recalc_product_bom_cost(id)
        return jsonify({
            'success': True,
            'message': 'Quantity updated',
            'total_cost': total_cost
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@products_bp.route('/products/<int:id>/boms/sync_cost', methods=['POST'])
def sync_product_bom_cost(id):
    try:
        total_cost = recalc_product_bom_cost(id)
        return jsonify({
            'success': True,
            'message': 'Cost recalculated and synchronized with components',
            'total_cost': total_cost
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@products_bp.route('/products/create_combined_ajax', methods=['POST'])
def create_combined_product_ajax():
    """
    Creates a new combined product with new name, photo, category, prices,
    and BOM components, automatically summing the cost from the components.
    """
    try:
        name = request.form.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'message': 'Product name is required'}), 400

        sku = request.form.get('sku', '').strip()
        if not sku:
            next_id = query_one("SELECT COALESCE(MAX(id), 0) + 1 as nid FROM products")['nid']
            sku = f"SKU-{next_id:04d}"

        category_id = request.form.get('category_id') or None
        if category_id: category_id = int(category_id)
        
        description = request.form.get('description', '').strip()
        sell_price = float(request.form.get('default_price', 0.0) or 0.0)
        uom = request.form.get('uom', 'pcs.').strip()

        # Parse components from components_json or form arrays
        comps_raw = request.form.get('components_json')
        components = []
        if comps_raw:
            import json
            try:
                components = json.loads(comps_raw)
            except Exception:
                components = []

        if not components:
            c_ids = request.form.getlist('component_product_id[]')
            c_qtys = request.form.getlist('component_quantity[]')
            for idx, c_id in enumerate(c_ids):
                if c_id and str(c_id).isdigit():
                    q = float(c_qtys[idx] if idx < len(c_qtys) else 1.0) or 1.0
                    components.append({'component_product_id': int(c_id), 'quantity': q})

        new_id = execute_returning_id("""
            INSERT INTO products (
                sku, name, description, category_id, uom,
                default_price, standard_cost, average_cost,
                item_type, combine_type, is_active
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, 0.0, 0.0,
                'Stockable', 'multi', TRUE
            ) RETURNING id;
        """, (sku, name, description, category_id, uom, sell_price))

        # Handle Picture Upload
        if 'picture' in request.files:
            file = request.files['picture']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    filename = f"prod_{new_id}_{int(time.time())}.{ext}"
                    save_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'products')
                    os.makedirs(save_dir, exist_ok=True)
                    filepath = os.path.join(save_dir, filename)
                    file.save(filepath)
                    image_url = f"/static/uploads/products/{filename}"
                    execute("UPDATE products SET image_url = %s WHERE id = %s", (image_url, new_id))

        # Insert BOM components
        for c in components:
            c_pid = int(c.get('component_product_id') or c.get('id') or 0)
            c_qty = float(c.get('quantity') or 1.0)
            if c_pid and c_pid != new_id and c_qty > 0:
                cp = query_one("SELECT description, standard_cost FROM products WHERE id = %s", (c_pid,))
                if cp:
                    execute("""
                        INSERT INTO product_boms (product_id, component_product_id, description, quantity, cost)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (new_id, c_pid, cp.get('description') or '', c_qty, float(cp.get('standard_cost') or 0.0)))

        # Recalculate combined cost automatically
        total_cost = recalc_product_bom_cost(new_id)

        # Record initial version
        execute("""
            INSERT INTO product_versions (product_id, version_number, name, sku, standard_cost, default_price, change_summary)
            VALUES (%s, 1, %s, %s, %s, %s, 'Created as Combined Kit product');
        """, (new_id, name, sku, total_cost, sell_price))

        return jsonify({
            'success': True,
            'message': f"Combined product '{name}' created successfully!",
            'product_id': new_id,
            'sku': sku,
            'standard_cost': total_cost,
            'redirect_url': url_for('products.list_products', id=new_id)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# --- Merge Duplicate Products Feature (Bilingual Khmer & English Detection) ---

@products_bp.route('/products/merge-duplicates')
def merge_duplicates_view():
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))
    
    is_main_admin = session.get('role') == 'main_admin'
    selected_id = request.args.get('id', type=int)
    
    return render_template('products/merge_duplicates.html',
                           selected_id=selected_id,
                           is_main_admin=is_main_admin)

@products_bp.route('/api/products/duplicate-candidates')
def api_duplicate_candidates():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        from services.product_merge import find_duplicate_groups
        threshold = float(request.args.get('threshold', 0.75))
        limit = int(request.args.get('limit', 100))
        groups = find_duplicate_groups(threshold=threshold, limit=limit)
        return jsonify({
            'success': True,
            'count': len(groups),
            'groups': groups
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@products_bp.route('/api/products/search-for-merge')
def api_search_for_merge():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        from services.product_merge import search_products_for_merge
        query = request.args.get('q', '').strip()
        results = search_products_for_merge(query, limit=30)
        return jsonify({
            'success': True,
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@products_bp.route('/api/products/merge', methods=['POST'])
def api_execute_merge():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        from services.product_merge import execute_product_merge
        data = request.get_json() or {}
        master_id = data.get('master_id')
        source_ids = data.get('source_ids') or []
        overrides = data.get('overrides') or {}

        if not master_id:
            return jsonify({'success': False, 'error': 'Please select a master product to keep.'}), 400
        if not source_ids:
            return jsonify({'success': False, 'error': 'Please select at least one duplicate product to merge into the master.'}), 400

        result = execute_product_merge(master_id, source_ids, overrides=overrides)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@products_bp.route('/api/products/bulk-merge-all', methods=['POST'])
def api_bulk_merge_all():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        from services.product_merge import bulk_merge_all_duplicates
        data = request.get_json() or {}
        threshold = float(data.get('threshold') or 0.85)
        only_category_master = bool(data.get('only_category_master', False))

        result = bulk_merge_all_duplicates(threshold=threshold, only_category_master=only_category_master)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@products_bp.route('/inventory/price-list')
@products_bp.route('/products/price-list')
def price_list_view():
    if not session.get('user_id'):
        return redirect(url_for('auth.login', next=request.path))

    categories = query_all("""
        SELECT c.id, c.name, COALESCE(c.color, '#00A3E0') as color,
               COALESCE(c.price_table_style, 'classic') as price_table_style,
               COUNT(p.id) as product_count
        FROM categories c
        LEFT JOIN products p ON p.category_id = c.id AND p.is_active = TRUE
        WHERE c.is_active = TRUE
        GROUP BY c.id, c.name, c.color, c.price_table_style
        ORDER BY c.name ASC
    """)

    pricing_schemes = query_all("""
        SELECT id, name, currency, is_default, is_active
        FROM pricing_schemes
        WHERE is_active = TRUE
        ORDER BY is_default DESC, id ASC
    """)

    # Global price table style setting
    global_setting = query_one("SELECT setting_value FROM app_settings WHERE setting_key = 'default_price_table_style'")
    global_price_table_style = (global_setting['setting_value'] if global_setting and global_setting.get('setting_value') else 'classic').lower()
    if global_price_table_style not in ('classic', 'modern'):
        global_price_table_style = 'classic'

    stock_rows = query_all("""
        SELECT product_id, SUM(quantity) as total_qty
        FROM inventory
        GROUP BY product_id
    """)
    stock_map = {r['product_id']: float(r['total_qty'] or 0) for r in stock_rows}

    products = query_all("""
        SELECT 
            p.*,
            COALESCE(c.name, 'General') as category_name,
            COALESCE(c.color, '#00A3E0') as category_color,
            COALESCE(p.price_card_style, c.price_table_style, %s, 'classic') as price_table_style
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = TRUE
        ORDER BY c.name ASC, p.name ASC, p.id ASC
    """, (global_price_table_style,))

    p_ids = [p['id'] for p in products]
    tiers_by_pid = {}
    if p_ids:
        all_tiers = query_all("""
            SELECT pp.product_id, ps.id as pricing_scheme_id, ps.name as scheme_name, pp.unit_price
            FROM product_prices pp
            JOIN pricing_schemes ps ON pp.pricing_scheme_id = ps.id
            WHERE pp.product_id = ANY(%s) AND ps.is_active = TRUE
            ORDER BY ps.is_default DESC, ps.id ASC
        """, (p_ids,))
        for t in all_tiers:
            tiers_by_pid.setdefault(t['product_id'], []).append(t)

    items = []
    for prod in products:
        p_tiers = tiers_by_pid.get(prod['id'], [])
        card_data = _build_price_card_data(prod, p_tiers, can_view_costs=False)

        # Extract volume/capacity badge (e.g. "2000 ml", "500 ml", "5 OZ", etc.)
        badge = None
        if prod.get('capacity'):
            badge = str(prod['capacity']).strip()
        else:
            m = re.search(r'(\d+\s*(?:ml|ML|oz|OZ|g|G|kg|KG|l|L)\b)', prod.get('name') or '')
            if m:
                badge = m.group(1).strip()

        # Packaging breakdown specs
        pcs_case = card_data.get('pcs_per_case') or 400
        pcs_case_formatted = f"{pcs_case:g}" if isinstance(pcs_case, (int, float)) else str(pcs_case)
        packs_case = card_data.get('packs_per_case') or 10
        pcs_pack = card_data.get('pcs_per_pack') or 50
        dim_str = card_data.get('dim_str') or ''

        # Map scheme prices for quick client-side switching
        prices_by_scheme = {}
        for t in p_tiers:
            try:
                prices_by_scheme[t['pricing_scheme_id']] = float(t['unit_price'] or 0)
            except (ValueError, TypeError):
                pass

        default_price = float(prod.get('default_price') or 0)
        stock_qty = stock_map.get(prod['id'], 0)

        items.append({
            'id': prod['id'],
            'sku': prod.get('sku') or '',
            'name': prod.get('name') or '',
            'khmer_name': card_data.get('khmer_name') or prod.get('name') or '',
            'english_name': card_data.get('english_name') or '',
            'uom': prod.get('uom') or 'កេស',
            'category_id': prod.get('category_id') or 0,
            'category_name': prod.get('category_name') or 'General',
            'category_color': prod.get('category_color') or '#00A3E0',
            'price_table_style': prod.get('price_table_style') or global_price_table_style or 'classic',
            'image_url': prod.get('image_url') or '',
            'badge': badge,
            'dim_str': dim_str,
            'pcs_case': pcs_case,
            'pcs_case_formatted': pcs_case_formatted,
            'packs_per_case': packs_case,
            'pcs_per_pack': pcs_pack,
            'stock_qty': stock_qty,
            'default_price': default_price,
            'prices_by_scheme': prices_by_scheme,
            'card': card_data
        })

    return render_template('products/price_list.html',
                           categories=categories,
                           pricing_schemes=pricing_schemes,
                           items=items,
                           total_products=len(items),
                           global_price_table_style=global_price_table_style)

DEFAULT_PRICE_CARD_UNITS = ['ប្រអប់', 'គូរ', 'បេ', 'ឈុត', 'កែវ', 'សម']

@products_bp.route('/api/products/price-card-units', methods=['GET', 'POST'])
def api_price_card_units():
    """
    GET: returns available Khmer unit words for price cards.
    POST: adds a new custom unit word to app_settings.
    """
    import json
    setting = query_one("SELECT setting_value FROM app_settings WHERE setting_key = 'price_card_units'")
    units = list(DEFAULT_PRICE_CARD_UNITS)
    if setting and setting.get('setting_value'):
        try:
            saved_units = json.loads(setting['setting_value'])
            if isinstance(saved_units, list):
                for u in saved_units:
                    u_clean = str(u).strip()
                    if u_clean and u_clean not in units:
                        units.append(u_clean)
        except Exception:
            pass

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        new_unit = (data.get('unit') or request.form.get('unit') or '').strip()
        if new_unit and new_unit not in units:
            units.append(new_unit)
            try:
                execute("""
                    INSERT INTO app_settings (setting_key, setting_value, description, updated_at)
                    VALUES ('price_card_units', %s, 'Custom Khmer unit words for price cards', CURRENT_TIMESTAMP)
                    ON CONFLICT (setting_key) 
                    DO UPDATE SET setting_value = EXCLUDED.setting_value, updated_at = CURRENT_TIMESTAMP;
                """, (json.dumps(units, ensure_ascii=False),))
            except Exception as e:
                logger.warning(f"Failed to persist custom unit to app_settings: {e}")
        return jsonify({'success': True, 'units': units, 'added': new_unit})

    return jsonify({'success': True, 'units': units})

