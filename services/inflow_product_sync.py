import sys
import os
sys.path.insert(0, os.path.abspath('.'))
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
import re
import logging
from datetime import datetime
import pyodbc
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config
from database import get_db_cursor, query_all, query_one

logger = logging.getLogger('inflow.product_sync')

def clean_str(s):
    if not s:
        return ''
    s = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', str(s))
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()

def get_sqlserver_connection():
    conn_str = (
        f"Driver={{SQL Server}};"
        f"Server={Config.SQLSERVER_HOST};"
        f"Database={Config.SQLSERVER_DB};"
        f"UID={Config.SQLSERVER_USER};"
        f"PWD={Config.SQLSERVER_PASSWORD};"
    )
    return pyodbc.connect(conn_str)

def sync_all_products_from_inflow():
    """
    Reads the authentic inFlow Inventory database on SQL Server (.\\INFLOWSQL)
    and updates all product info in PostgreSQL:
    - Master Catalog (Names, Descriptions, Remarks, Barcodes, Dimensions, UOMs, Packs)
    - Product Images (218 extracted images from BASE_FileAttachment)
    - Categories & Hierarchies (BASE_Category)
    - Multi-Tier Pricing Schemes & Prices (Retail 1, 2, 3, 1000 pcs, Wholesale...)
    - Costs (Standard, Average, Last Purchase, Costing Method)
    - Current Stock Levels on Hand (VIEW_CurrentStock)
    - Vendor Product Codes & Pricing (BASE_VendorItem)
    - Bill of Materials (BASE_ItemBom)
    """
    logger.info("Connecting to inFlow SQL Server database...")
    sql_conn = get_sqlserver_connection()
    sql_cur = sql_conn.cursor()

    # Image directory
    img_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'products')
    os.makedirs(img_dir, exist_ok=True)

    stats = {
        'categories_synced': 0,
        'pricing_schemes_synced': 0,
        'locations_synced': 0,
        'images_extracted': 0,
        'products_updated': 0,
        'products_inserted': 0,
        'prices_synced': 0,
        'inventory_synced': 0,
        'vendor_items_synced': 0,
        'boms_synced': 0
    }

    with get_db_cursor(commit=True) as pg_cur:
        # =====================================================================
        # 1. CATEGORIES SYNCHRONIZATION
        # =====================================================================
        logger.info("Synchronizing Categories...")
        sql_cur.execute("SELECT CategoryId, ParentCategoryId, Name, IsActive FROM BASE_Category ORDER BY CategoryId;")
        cat_rows = sql_cur.fetchall()
        for c in cat_rows:
            cat_id, p_cat_id, c_name, is_act = c[0], c[1], (c[2] or '').strip(), bool(c[3])
            pg_cur.execute("""
                INSERT INTO categories (id, name, is_active)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active;
            """, (cat_id, c_name, is_act))
            stats['categories_synced'] += 1

        # Link parent categories
        for c in cat_rows:
            cat_id, p_cat_id = c[0], c[1]
            if p_cat_id:
                pg_cur.execute("UPDATE categories SET parent_id = %s WHERE id = %s;", (p_cat_id, cat_id))

        # =====================================================================
        # 2. PRICING SCHEMES SYNCHRONIZATION
        # =====================================================================
        logger.info("Synchronizing Pricing Schemes...")
        sql_cur.execute("SELECT PricingSchemeId, Name, IsActive FROM BASE_PricingScheme ORDER BY PricingSchemeId;")
        for s in sql_cur.fetchall():
            s_id, s_name, s_active = s[0], (s[1] or '').strip(), bool(s[2])
            is_def = (s_id == 100) # Retail 1 is default
            pg_cur.execute("""
                INSERT INTO pricing_schemes (id, name, is_active, is_default)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    is_default = EXCLUDED.is_default;
            """, (s_id, s_name, s_active, is_def))
            stats['pricing_schemes_synced'] += 1

        # =====================================================================
        # 3. LOCATIONS SYNCHRONIZATION
        # =====================================================================
        logger.info("Synchronizing Locations...")
        sql_cur.execute("SELECT LocationId, Name FROM BASE_Location WHERE LocationId IN (100, 101);")
        for loc in sql_cur.fetchall():
            l_id, l_name = loc[0], (loc[1] or '').strip()
            is_def = (l_id == 100)
            pg_cur.execute("""
                INSERT INTO locations (id, name, is_active, is_default)
                VALUES (%s, %s, TRUE, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_default = EXCLUDED.is_default;
            """, (l_id, l_name, is_def))
            stats['locations_synced'] += 1

        # =====================================================================
        # 4. EXTRACT PRODUCT PICTURES
        # =====================================================================
        logger.info("Extracting Product Pictures from BASE_FileAttachment...")
        sql_cur.execute("""
            SELECT p.ProdId, fa.Data
            FROM BASE_Product p
            JOIN BASE_FileAttachment fa ON p.PictureFileAttachmentId = fa.FileAttachmentId
            WHERE fa.Data IS NOT NULL;
        """)
        img_map = {}
        for pid, data in sql_cur.fetchall():
            if data:
                raw_bytes = bytes(data)
                ext = 'png' if raw_bytes.startswith(b'\x89PNG') else 'jpg'
                fname = f"prod_{pid}.{ext}"
                fpath = os.path.join(img_dir, fname)
                try:
                    with open(fpath, 'wb') as img_f:
                        img_f.write(raw_bytes)
                    img_map[pid] = f"/static/uploads/products/{fname}"
                    stats['images_extracted'] += 1
                except Exception as e:
                    logger.warning(f"Could not save image for ProdId {pid}: {e}")

        # =====================================================================
        # 5. PRODUCT MASTER CATALOG (UPDATE & INSERT)
        # =====================================================================
        logger.info("Fetching products from inFlow BASE_Product...")
        sql_cur.execute("""
            SELECT 
                p.ProdId,
                ISNULL(p.Name, '') as Name,
                p.Description,
                p.Remarks,
                p.BarCode,
                p.CategoryId,
                p.Uom,
                p.MasterPackQty,
                p.InnerPackQty,
                p.DefaultLocationId,
                p.DefaultSublocation,
                p.ReorderPoint,
                p.ReorderQuantity,
                p.ProductLength,
                p.ProductWidth,
                p.ProductHeight,
                p.ProductWeight,
                p.CaseLength,
                p.CaseWidth,
                p.CaseHeight,
                p.CaseWeight,
                p.Custom1, p.Custom2, p.Custom3, p.Custom4, p.Custom5,
                p.Custom6, p.Custom7, p.Custom8, p.Custom9, p.Custom10,
                p.IsSellable, p.IsPurchaseable, p.IsActive,
                p.ItemType, p.ItemTaxCodeId, p.LastVendorId,
                p.SoUomName, p.SoUomRatioStd, p.SoUomRatio,
                p.PoUomName, p.PoUomRatioStd, p.PoUomRatio,
                ISNULL(c.StandardCost, 0) as StandardCost,
                ISNULL(c.AverageCost, 0) as AverageCost,
                ISNULL(c.LastPurchaseCost, 0) as LastPurchaseCost,
                ISNULL(c.CostingMethod, 1) as CostingMethod,
                ISNULL(pr1.UnitPrice, 0) as Retail1Price
            FROM BASE_Product p
            LEFT JOIN BASE_InventoryCost c ON p.ProdId = c.ProdId
            LEFT JOIN BASE_ItemPrice pr1 ON p.ProdId = pr1.ProdId AND pr1.PricingSchemeId = 100
            ORDER BY p.ProdId;
        """)
        sql_products = sql_cur.fetchall()

        # Build existing PG products lookup by clean name and id
        pg_cur.execute("SELECT id, name, sku, custom_attributes FROM products;")
        existing_pg_prods = pg_cur.fetchall()
        pg_by_name = {clean_str(p['name']): p['id'] for p in existing_pg_prods}
        pg_by_inflow_id = {}
        for p in existing_pg_prods:
            ca = p['custom_attributes'] or {}
            if isinstance(ca, dict) and ca.get('inflow_prod_id'):
                pg_by_inflow_id[int(ca['inflow_prod_id'])] = p['id']

        type_map = {1: 'Stockable', 2: 'Non-Stocked', 3: 'Service'}
        tax_map = {100: 'Taxable', 101: 'Non-Taxable'}
        costing_map = {1: 'Manual', 2: 'Average', 3: 'Standard', 4: 'FIFO'}

        # Map to remember PG product_id for each inFlow ProdId
        prod_id_map = {}

        for row in sql_products:
            prod_id = row[0]
            name = (row[1] or '').strip()
            desc = row[2] or ''
            remarks = row[3] or ''
            barcode = row[4] or ''
            cat_id = row[5]
            uom = row[6] or 'pcs'
            m_pack = float(row[7]) if row[7] is not None else 1.0
            i_pack = float(row[8]) if row[8] is not None else 1.0
            def_loc = row[9] if row[9] in (100, 101) else 100
            def_subloc = row[10] or ''
            reorder_pt = float(row[11]) if row[11] is not None else 0.0
            reorder_qty = float(row[12]) if row[12] is not None else 0.0
            p_len = float(row[13]) if row[13] is not None else 0.0
            p_wid = float(row[14]) if row[14] is not None else 0.0
            p_hgt = float(row[15]) if row[15] is not None else 0.0
            p_wgt = float(row[16]) if row[16] is not None else 0.0
            c_len = float(row[17]) if row[17] is not None else 0.0
            c_wid = float(row[18]) if row[18] is not None else 0.0
            c_hgt = float(row[19]) if row[19] is not None else 0.0
            c_wgt = float(row[20]) if row[20] is not None else 0.0
            custom1 = row[21] or ''
            custom2 = row[22] or ''
            custom3 = row[23] or ''
            custom4 = row[24] or ''
            custom5 = row[25] or ''
            custom6 = row[26] or ''
            custom7 = row[27] or ''
            custom8 = row[28] or ''
            custom9 = row[29] or ''
            custom10 = row[30] or ''
            sellable = bool(row[31])
            purchasable = bool(row[32])
            active = bool(row[33])
            item_type = type_map.get(row[34], 'Stockable')
            tax_code = tax_map.get(row[35], 'Taxable')
            last_vend = row[36]
            so_uom = row[37] or ''
            so_uom_ratio_std = float(row[38]) if row[38] is not None else 1.0
            so_uom_ratio = float(row[39]) if row[39] is not None else 1.0
            po_uom = row[40] or ''
            po_uom_ratio_std = float(row[41]) if row[41] is not None else 1.0
            po_uom_ratio = float(row[42]) if row[42] is not None else 1.0
            std_cost = float(row[43]) if row[43] is not None else 0.0
            avg_cost = float(row[44]) if row[44] is not None else 0.0
            last_cost = float(row[45]) if row[45] is not None else 0.0
            costing_method = costing_map.get(row[46], 'Manual')
            retail1_price = float(row[47]) if row[47] is not None else 0.0
            img_url = img_map.get(prod_id)

            custom_attrs = {
                'inflow_prod_id': prod_id,
                'case_length': c_len,
                'case_width': c_wid,
                'case_height': c_hgt,
                'case_weight': c_wgt,
                'custom6': custom6,
                'custom7': custom7,
                'custom8': custom8,
                'custom9': custom9,
                'custom10': custom10
            }
            import json
            custom_attrs_json = json.dumps(custom_attrs)

            # Match target product in PostgreSQL
            target_pg_id = pg_by_inflow_id.get(prod_id) or pg_by_name.get(clean_str(name))

            if target_pg_id:
                # Update existing product
                pg_cur.execute("""
                    UPDATE products
                    SET name = %s,
                        description = COALESCE(NULLIF(%s, ''), description),
                        remarks = COALESCE(NULLIF(%s, ''), remarks),
                        barcode = COALESCE(NULLIF(%s, ''), barcode),
                        category_id = COALESCE(%s, category_id),
                        uom = COALESCE(NULLIF(%s, ''), uom),
                        master_pack_qty = %s,
                        inner_pack_qty = %s,
                        default_location_id = %s,
                        default_sublocation = COALESCE(NULLIF(%s, ''), default_sublocation),
                        reorder_point = %s,
                        reorder_quantity = %s,
                        length = %s,
                        width = %s,
                        height = %s,
                        weight = %s,
                        custom1 = COALESCE(NULLIF(%s, ''), custom1),
                        custom2 = COALESCE(NULLIF(%s, ''), custom2),
                        custom3 = COALESCE(NULLIF(%s, ''), custom3),
                        custom4 = COALESCE(NULLIF(%s, ''), custom4),
                        custom5 = COALESCE(NULLIF(%s, ''), custom5),
                        is_sellable = %s,
                        is_purchaseable = %s,
                        is_active = %s,
                        item_type = %s,
                        tax_code = %s,
                        sales_uom = COALESCE(NULLIF(%s, ''), sales_uom),
                        sales_uom_ratio = %s,
                        sales_uom_ratio_std = %s,
                        purchasing_uom = COALESCE(NULLIF(%s, ''), purchasing_uom),
                        purchasing_uom_ratio = %s,
                        purchasing_uom_ratio_std = %s,
                        standard_cost = %s,
                        average_cost = %s,
                        last_purchase_cost = %s,
                        costing_method = %s,
                        default_price = CASE WHEN %s > 0 THEN %s ELSE default_price END,
                        image_url = COALESCE(%s, image_url),
                        custom_attributes = COALESCE(custom_attributes, '{}'::jsonb) || %s::jsonb,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (
                    name, desc, remarks, barcode, cat_id, uom,
                    m_pack, i_pack, def_loc, def_subloc,
                    reorder_pt, reorder_qty,
                    p_len, p_wid, p_hgt, p_wgt,
                    custom1, custom2, custom3, custom4, custom5,
                    sellable, purchasable, active, item_type, tax_code,
                    so_uom, so_uom_ratio, so_uom_ratio_std,
                    po_uom, po_uom_ratio, po_uom_ratio_std,
                    std_cost, avg_cost, last_cost, costing_method,
                    retail1_price, retail1_price,
                    img_url, custom_attrs_json,
                    target_pg_id
                ))
                prod_id_map[prod_id] = target_pg_id
                stats['products_updated'] += 1
            else:
                # Insert missing product
                sku = f"SKU-{prod_id:04d}"
                pg_cur.execute("""
                    INSERT INTO products (
                        sku, name, description, remarks, barcode, category_id, uom,
                        master_pack_qty, inner_pack_qty, default_location_id, default_sublocation,
                        reorder_point, reorder_quantity, length, width, height, weight,
                        custom1, custom2, custom3, custom4, custom5,
                        is_sellable, is_purchaseable, is_active, item_type, tax_code,
                        sales_uom, sales_uom_ratio, sales_uom_ratio_std,
                        purchasing_uom, purchasing_uom_ratio, purchasing_uom_ratio_std,
                        standard_cost, average_cost, last_purchase_cost, costing_method,
                        default_price, image_url, custom_attributes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s::jsonb
                    )
                    RETURNING id;
                """, (
                    sku, name, desc, remarks, barcode, cat_id, uom,
                    m_pack, i_pack, def_loc, def_subloc,
                    reorder_pt, reorder_qty, p_len, p_wid, p_hgt, p_wgt,
                    custom1, custom2, custom3, custom4, custom5,
                    sellable, purchasable, active, item_type, tax_code,
                    so_uom, so_uom_ratio, so_uom_ratio_std,
                    po_uom, po_uom_ratio, po_uom_ratio_std,
                    std_cost, avg_cost, last_cost, costing_method,
                    retail1_price, img_url, custom_attrs_json
                ))
                new_pg_id = pg_cur.fetchone()['id']
                prod_id_map[prod_id] = new_pg_id
                pg_by_name[clean_str(name)] = new_pg_id
                stats['products_inserted'] += 1

        # =====================================================================
        # 6. MULTI-TIER PRODUCT PRICES (BASE_ItemPrice)
        # =====================================================================
        logger.info("Synchronizing Multi-Tier Product Prices (BASE_ItemPrice)...")
        sql_cur.execute("""
            SELECT ProdId, PricingSchemeId, UnitPrice
            FROM BASE_ItemPrice
            WHERE UnitPrice IS NOT NULL;
        """)
        for pid, scheme_id, price in sql_cur.fetchall():
            pg_pid = prod_id_map.get(pid)
            if pg_pid:
                u_price = float(price) if price is not None else 0.0
                pg_cur.execute("""
                    INSERT INTO product_prices (product_id, pricing_scheme_id, unit_price)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (product_id, pricing_scheme_id) DO UPDATE SET
                        unit_price = EXCLUDED.unit_price;
                """, (pg_pid, scheme_id, u_price))
                stats['prices_synced'] += 1

        # =====================================================================
        # 7. INVENTORY STOCK LEVELS (VIEW_CurrentStock)
        # =====================================================================
        logger.info("Synchronizing Inventory Stock Levels (VIEW_CurrentStock)...")
        sql_cur.execute("""
            SELECT ProdId, LocationId, Sublocation, Quantity
            FROM VIEW_CurrentStock;
        """)
        for pid, loc_id, subloc, qty in sql_cur.fetchall():
            pg_pid = prod_id_map.get(pid)
            if pg_pid:
                t_loc_id = loc_id if loc_id in (100, 101) else 100
                t_subloc = (subloc or '').strip()
                t_qty = float(qty) if qty is not None else 0.0

                pg_cur.execute("""
                    INSERT INTO inventory (product_id, location_id, sublocation, quantity)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_id, location_id, sublocation) DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        updated_at = CURRENT_TIMESTAMP;
                """, (pg_pid, t_loc_id, t_subloc, t_qty))
                stats['inventory_synced'] += 1

        # =====================================================================
        # 8. VENDOR ITEMS (BASE_VendorItem)
        # =====================================================================
        logger.info("Synchronizing Vendor Items (BASE_VendorItem)...")
        # Ensure vendors exist
        sql_cur.execute("SELECT VendorId, Name, ContactName, Phone, Email FROM BASE_Vendor;")
        for v in sql_cur.fetchall():
            v_id, v_name, v_contact, v_phone, v_email = v[0], (v[1] or '').strip(), v[2], v[3], v[4]
            pg_cur.execute("""
                INSERT INTO vendors (id, name, contact_name, phone, email, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    contact_name = COALESCE(NULLIF(EXCLUDED.contact_name, ''), vendors.contact_name);
            """, (v_id, v_name, v_contact, v_phone, v_email))

        sql_cur.execute("""
            SELECT ProdId, VendorId, VendorItemCode, Cost
            FROM BASE_VendorItem
            WHERE Cost IS NOT NULL OR VendorItemCode IS NOT NULL;
        """)
        for pid, vid, vcode, vcost in sql_cur.fetchall():
            pg_pid = prod_id_map.get(pid)
            if pg_pid:
                v_pr = float(vcost) if vcost is not None else 0.0
                pg_cur.execute("""
                    INSERT INTO product_vendors (product_id, vendor_id, vendor_item_code, cost)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_id, vendor_id) DO UPDATE SET
                        vendor_item_code = COALESCE(NULLIF(EXCLUDED.vendor_item_code, ''), product_vendors.vendor_item_code),
                        cost = EXCLUDED.cost;
                """, (pg_pid, vid, vcode, v_pr))
                stats['vendor_items_synced'] += 1

        # =====================================================================
        # 9. BILL OF MATERIALS (BASE_ItemBom)
        # =====================================================================
        logger.info("Synchronizing Bill of Materials (BASE_ItemBom)...")
        sql_cur.execute("SELECT ProdId, ChildProdId, Quantity FROM BASE_ItemBom;")
        for parent_pid, comp_pid, bqty in sql_cur.fetchall():
            parent_pg_id = prod_id_map.get(parent_pid)
            comp_pg_id = prod_id_map.get(comp_pid)
            if parent_pg_id and comp_pg_id:
                pg_cur.execute("""
                    INSERT INTO product_boms (product_id, component_product_id, quantity)
                    VALUES (%s, %s, %s);
                """, (parent_pg_id, comp_pg_id, float(bqty or 1.0)))
                stats['boms_synced'] += 1

    sql_conn.close()
    logger.info("Product synchronization completed successfully: %s", stats)
    return stats

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    res = sync_all_products_from_inflow()
    print("SYNC RESULT:", res)
