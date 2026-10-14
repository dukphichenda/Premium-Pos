import re
from difflib import SequenceMatcher
from database import get_db_cursor, query_one, query_all, execute

def clean_text(text):
    """
    Cleans and normalizes text for bilingual Khmer and English comparison:
    - Strips zero-width and invisible unicode characters (e.g. \u200b)
    - Converts English characters to lowercase
    - Normalizes packaging units (e.g. 500ចាន/កេស, 200ដប/ដុំ, 50pcs/case, etc.)
    - Removes punctuation and extra whitespace
    """
    if not text:
        return ""
    # Strip zero-width spaces and invisible characters
    t = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    # Lowercase
    t = t.lower()
    # Normalize packaging noise frequently appended to product titles
    t = re.sub(r'\d+\s*(?:pcs|pc|កេស|ចាន|ដប|ប្រអប់|ដុំ|សន្លឹក|គ្រាប់|box|case)\s*(?:/\s*(?:កេស|ដុំ|case|box|ចាន))?', ' ', t)
    # Remove punctuation
    t = re.sub(r'[\(\)\[\]\{\}\-_/\\\+,\.:;!?"\'`~@#\$%\^&\*]', ' ', t)
    # Collapse multiple whitespaces
    t = re.sub(r'\s+', ' ', t).strip()
    return t

OPPOSING_ATTRIBUTE_PAIRS = [
    ({'black', 'ខ្មៅ'}, {'clear', 'ថ្លា', 'transparent'}),
    ({'black', 'ខ្មៅ'}, {'white', 'ស'}),
    ({'gold', 'មាស'}, {'silver', 'ប្រាក់'}),
    ({'មានគម្រប', 'with lid', 'withlid'}, {'អត់គម្រប', 'no lid', 'nolid', 'without lid'}),
    ({'អត់រន្ធ', 'no hole'}, {'មានរន្ធ', 'with hole'}),
    ({'1ថត', '1 tray', '1 compartment'}, {'2ថត', '2 trays', '2 compartments'}),
    ({'2ថត', '2 trays', '2 compartments'}, {'3ថត', '3 trays', '3 compartments'}),
    ({'3ថត', '3 trays', '3 compartments'}, {'4ថត', '4 trays', '4 compartments'}),
    ({'1ជាន់', '1 wall', 'single wall'}, {'2ជាន់', '2 wall', 'double wall'}),
]

def extract_dimensions_and_sizes(text):
    if not text:
        return set(), set(), set(), set()
    text_upper = text.upper()
    vols = set(re.sub(r'\s+', '', v) for v in re.findall(r'\b\d+(?:\.\d+)?\s*(?:ML|OZ|L|G|KG|CM|MM)\b', text_upper))
    trays = set(re.findall(r'\b(\d+)\s*(?:ថត|TRAY|TRAYS|COMPARTMENT)', text_upper))
    models = set(re.findall(r'\b(?:[A-Z]{1,5})\s*(\d+(?:\.\d+)?)\b', text_upper))
    colors = set(re.findall(r'(\d+)\s*COLOR', text_upper))
    return vols, trays, models, colors

def has_opposing_attributes(t1, t2):
    c1 = (t1 or '').lower()
    c2 = (t2 or '').lower()
    for set_a, set_b in OPPOSING_ATTRIBUTE_PAIRS:
        has_a1 = any(w in c1 for w in set_a)
        has_b1 = any(w in c1 for w in set_b)
        has_a2 = any(w in c2 for w in set_a)
        has_b2 = any(w in c2 for w in set_b)
        if (has_a1 and has_b2) or (has_b1 and has_a2):
            return True
    return False

def calculate_similarity(p1, p2):
    """
    Computes a hybrid similarity score (0.0 to 1.0) between two products
    taking into account Khmer text, English text, and SKUs, while strictly
    differentiating product variants (e.g. colors, lids, volumes, and models).
    """
    name1 = p1.get('name') or ''
    name2 = p2.get('name') or ''
    sku1 = p1.get('sku') or ''
    sku2 = p2.get('sku') or ''
    full1 = f"{name1} {sku1}"
    full2 = f"{name2} {sku2}"

    # 1. Opposing attributes check (black vs clear, with lid vs without lid, etc.)
    if has_opposing_attributes(full1, full2):
        return 0.10

    # 2. Dimensions, volumes & models conflict check
    v1, tr1, m1, col1 = extract_dimensions_and_sizes(full1)
    v2, tr2, m2, col2 = extract_dimensions_and_sizes(full2)

    # If both specify volumes and they differ (e.g., 500ml vs 1000ml)
    if v1 and v2 and not (v1 & v2):
        return 0.10
    # If both specify tray count and they differ (e.g., 1 vs 2 trays)
    if tr1 and tr2 and not (tr1 & tr2):
        return 0.10
    # If both specify model/size codes and they differ (e.g., S22 vs S24, N3 vs N14, ST02 vs ST04)
    if m1 and m2 and not (m1 & m2):
        return 0.10
    # If both specify printing color count and they differ
    if col1 and col2 and col1 != col2:
        return 0.10

    c1 = clean_text(name1)
    c2 = clean_text(name2)
    if not c1 or not c2:
        return 0.0

    # Exact match after normalization
    if c1 == c2:
        return 1.0

    # Substring containment (e.g. short title inside long title)
    if c1 in c2 or c2 in c1:
        shorter_len = min(len(c1), len(c2))
        longer_len = max(len(c1), len(c2))
        if shorter_len >= 4 and (shorter_len / longer_len) >= 0.40:
            return min(0.98, 0.88 + 0.10 * (shorter_len / longer_len))

    # Character sequence ratio
    seq_ratio = SequenceMatcher(None, c1, c2).ratio()

    # Token overlap (Jaccard similarity on Khmer & English words)
    tokens1 = set(c1.split())
    tokens2 = set(c2.split())
    jaccard = (len(tokens1 & tokens2) / len(tokens1 | tokens2)) if (tokens1 and tokens2) else 0.0

    score = 0.55 * seq_ratio + 0.45 * jaccard

    # Boost score if SKUs are very similar or one SKU matches the other's name
    if sku1 and sku2:
        csku1 = clean_text(sku1)
        csku2 = clean_text(sku2)
        if csku1 and csku2 and (csku1 == csku2 or csku1 in csku2 or csku2 in csku1):
            score = max(score, 0.85)

    return min(1.0, score)

def find_duplicate_groups(threshold=0.75, limit=100):
    """
    Scans active products and groups duplicate candidates into clusters.
    Returns a list of cluster dicts, sorted by similarity descending.
    """
    prods = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.uom, p.default_price, p.standard_cost,
            p.image_url, p.category_id, COALESCE(c.name, 'Uncategorized') as category_name,
            COALESCE(inv.total_qty, 0) as stock_qty,
            COALESCE(so.order_count, 0) as sales_order_count,
            COALESCE(so.total_revenue, 0) as sales_revenue,
            COALESCE(po.po_count, 0) as po_count,
            COALESCE(po.total_cost, 0) as po_cost
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty 
            FROM inventory 
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(DISTINCT sales_order_id) as order_count, SUM(subtotal) as total_revenue
            FROM sales_order_lines
            GROUP BY product_id
        ) so ON p.id = so.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(DISTINCT purchase_order_id) as po_count, SUM(subtotal) as total_cost
            FROM purchase_order_lines
            GROUP BY product_id
        ) po ON p.id = po.product_id
        WHERE p.is_active = TRUE
        ORDER BY p.id ASC
    """)

    # Fast clustering using Union-Find / Adjacency
    parent = {p['id']: p['id'] for p in prods}
    prod_map = {p['id']: p for p in prods}
    scores = {}

    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def union(i, j, sim):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j
            pair_key = tuple(sorted([root_i, root_j]))
            scores[pair_key] = max(scores.get(pair_key, 0.0), sim)

    # Compute pairwise similarities
    n = len(prods)
    for i in range(n):
        p1 = prods[i]
        for j in range(i + 1, n):
            p2 = prods[j]
            sim = calculate_similarity(p1, p2)
            if sim >= threshold:
                union(p1['id'], p2['id'], sim)
                scores[(min(p1['id'], p2['id']), max(p1['id'], p2['id']))] = sim

    # Group into clusters
    clusters = {}
    for p in prods:
        root = find(p['id'])
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(p)

    results = []
    for root, items in clusters.items():
        if len(items) > 1:
            # Determine best match score in group
            max_sim = 0.0
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    sim = scores.get((min(items[i]['id'], items[j]['id']), max(items[i]['id'], items[j]['id'])), 0.0)
                    if sim > max_sim:
                        max_sim = sim

            # Pick recommended master:
            # 1. Has exact category (category_id is NOT null and NOT 'Uncategorized')
            # 2. Sales order count (from HQ and all branches)
            # 3. PO count
            # 4. Stock quantity
            # 5. Length of name
            # 6. Lowest ID (earliest created / original master)
            def _master_rank(x):
                has_exact_category = 1 if (x.get('category_id') and str(x.get('category_name', '')).strip().lower() not in ('uncategorized', 'none', '')) else 0
                return (
                    has_exact_category,
                    float(x.get('sales_order_count') or 0),
                    float(x.get('po_count') or 0),
                    float(x.get('stock_qty') or 0),
                    len(x.get('name') or ''),
                    -int(x['id'])
                )

            items_sorted = sorted(items, key=_master_rank, reverse=True)

            recommended_master_id = items_sorted[0]['id']

            results.append({
                'cluster_id': root,
                'similarity_score': round(max_sim * 100, 1),
                'recommended_master_id': recommended_master_id,
                'products': items_sorted,
                'total_combined_stock': sum(float(x.get('stock_qty') or 0) for x in items),
                'total_combined_orders': sum(int(x.get('sales_order_count') or 0) for x in items),
                'total_combined_pos': sum(int(x.get('po_count') or 0) for x in items)
            })

    results.sort(key=lambda x: (x['similarity_score'], len(x['products'])), reverse=True)
    return results[:limit]

def search_products_for_merge(keyword, limit=25):
    """
    Searches products by Khmer name, English name, SKU, or Barcode,
    returning rich stats for the merge picker.
    """
    kw = (keyword or '').strip()
    if not kw:
        return []

    # Clean keyword for comparison
    clean_kw = clean_text(kw)
    pattern = f"%{kw}%"
    clean_pattern = f"%{clean_kw}%" if clean_kw else pattern

    rows = query_all("""
        SELECT 
            p.id, p.sku, p.name, p.barcode, p.uom, p.default_price, p.standard_cost,
            p.image_url, p.category_id, COALESCE(c.name, 'Uncategorized') as category_name,
            COALESCE(inv.total_qty, 0) as stock_qty,
            COALESCE(so.order_count, 0) as sales_order_count,
            COALESCE(so.total_revenue, 0) as sales_revenue,
            COALESCE(po.po_count, 0) as po_count,
            COALESCE(po.total_cost, 0) as po_cost
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty 
            FROM inventory 
            GROUP BY product_id
        ) inv ON p.id = inv.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(DISTINCT sales_order_id) as order_count, SUM(subtotal) as total_revenue
            FROM sales_order_lines
            GROUP BY product_id
        ) so ON p.id = so.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(DISTINCT purchase_order_id) as po_count, SUM(subtotal) as total_cost
            FROM purchase_order_lines
            GROUP BY product_id
        ) po ON p.id = po.product_id
        WHERE p.is_active = TRUE
          AND (p.name ILIKE %s OR p.sku ILIKE %s OR p.barcode ILIKE %s)
        ORDER BY 
            CASE WHEN p.name ILIKE %s THEN 1 WHEN p.sku ILIKE %s THEN 2 ELSE 3 END,
            p.name ASC
        LIMIT %s
    """, (pattern, pattern, pattern, pattern, pattern, limit))

    return [dict(r) for r in rows]

def execute_product_merge(master_id, source_ids, overrides=None):
    """
    Executes an atomic product merge transaction:
    - Moves all sales order lines (product_id & addon_product_id) to master_id.
    - Moves all purchase order lines to master_id.
    - Consolidates warehouse inventory stocks.
    - Moves inventory logs, transfers, adjustments, attachments, BOMs.
    - Merges product prices and vendors without unique constraint conflicts.
    - Saves duplicate SKUs & barcodes into master metadata/remarks for searchability.
    - Permanently deletes the duplicate source product(s) or marks inactive.
    - All Sales Orders and Purchase Orders are 100% PRESERVED, NOT DELETED.
    """
    if not master_id:
        raise ValueError("Master product ID is required.")

    # Normalize source_ids
    if isinstance(source_ids, (int, str)):
        source_ids = [int(source_ids)]
    else:
        source_ids = [int(sid) for sid in source_ids if int(sid) != int(master_id)]

    if not source_ids:
        raise ValueError("At least one duplicate product must be selected to merge.")

    overrides = overrides or {}

    with get_db_cursor(commit=True) as cur:
        # 1. Fetch Master and Source products with Category details
        cur.execute("""
            SELECT p.*, COALESCE(c.name, 'Uncategorized') as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.id = %s
        """, (master_id,))
        master = cur.fetchone()
        if not master:
            raise ValueError(f"Master product #{master_id} not found.")

        cur.execute("""
            SELECT p.*, COALESCE(c.name, 'Uncategorized') as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.id = ANY(%s)
        """, (source_ids,))
        sources = cur.fetchall()
        if not sources:
            raise ValueError("No valid duplicate products found to merge.")

        sources_summary = [{
            'id': s['id'],
            'name': s['name'],
            'sku': s.get('sku') or 'NO-SKU',
            'category_name': s.get('category_name') or 'Uncategorized'
        } for s in sources]

        total_so_relinked = 0
        total_po_relinked = 0
        total_stock_moved = 0
        merged_skus = []
        merged_barcodes = []

        for src in sources:
            src_id = src['id']
            if src.get('sku'):
                merged_skus.append(src['sku'])
            if src.get('barcode'):
                merged_barcodes.append(src['barcode'])

            # 2. Relink Sales Order Lines (Preserve all sales orders!)
            cur.execute("""
                UPDATE sales_order_lines 
                SET product_id = %s 
                WHERE product_id = %s
            """, (master_id, src_id))
            so_cnt = cur.rowcount

            cur.execute("""
                UPDATE sales_order_lines 
                SET addon_product_id = %s 
                WHERE addon_product_id = %s
            """, (master_id, src_id))
            so_addon_cnt = cur.rowcount
            total_so_relinked += (so_cnt + so_addon_cnt)

            # 3. Relink Purchase Order Lines (Preserve all purchase orders!)
            cur.execute("""
                UPDATE purchase_order_lines 
                SET product_id = %s 
                WHERE product_id = %s
            """, (master_id, src_id))
            total_po_relinked += cur.rowcount

            # 4. Consolidate Warehouse Inventory
            cur.execute("SELECT * FROM inventory WHERE product_id = %s", (src_id,))
            src_inv = cur.fetchall()
            for sinv in src_inv:
                loc_id = sinv['location_id']
                subloc = sinv.get('sublocation') or ''
                qty = float(sinv.get('quantity') or 0)
                res_qty = float(sinv.get('reserved_quantity') or 0)
                total_stock_moved += qty

                cur.execute("""
                    SELECT id, quantity, reserved_quantity FROM inventory 
                    WHERE product_id = %s AND location_id = %s AND COALESCE(sublocation, '') = %s
                """, (master_id, loc_id, subloc))
                minv = cur.fetchone()

                if minv:
                    cur.execute("""
                        UPDATE inventory 
                        SET quantity = quantity + %s,
                            reserved_quantity = reserved_quantity + %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (qty, res_qty, minv['id']))
                    cur.execute("DELETE FROM inventory WHERE id = %s", (sinv['id'],))
                else:
                    cur.execute("""
                        UPDATE inventory 
                        SET product_id = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (master_id, sinv['id']))

            # Clean any remaining inventory records for src_id
            cur.execute("DELETE FROM inventory WHERE product_id = %s", (src_id,))

            # 5. Relink Inventory Logs
            cur.execute("UPDATE inventory_logs SET product_id = %s WHERE product_id = %s", (master_id, src_id))

            # 6. Relink Stock Transfers & Adjustments
            cur.execute("UPDATE stock_transfer_lines SET product_id = %s WHERE product_id = %s", (master_id, src_id))
            cur.execute("UPDATE stock_adjustment_lines SET product_id = %s WHERE product_id = %s", (master_id, src_id))

            # 7. Relink Product Attachments & Versions
            cur.execute("UPDATE product_attachments SET product_id = %s WHERE product_id = %s", (master_id, src_id))
            cur.execute("DELETE FROM product_versions WHERE product_id = %s", (src_id,))

            # 8. Relink BOMs & Combos (prevent circular self-references)
            cur.execute("DELETE FROM product_boms WHERE (product_id = %s AND component_product_id = %s) OR (product_id = %s AND component_product_id = %s)", (src_id, master_id, master_id, src_id))
            cur.execute("UPDATE product_boms SET product_id = %s WHERE product_id = %s", (master_id, src_id))
            cur.execute("UPDATE product_boms SET component_product_id = %s WHERE component_product_id = %s", (master_id, src_id))
            cur.execute("DELETE FROM product_boms WHERE product_id = component_product_id")

            cur.execute("DELETE FROM product_combine_options WHERE (product_id = %s AND component_product_id = %s) OR (product_id = %s AND component_product_id = %s)", (src_id, master_id, master_id, src_id))
            cur.execute("UPDATE product_combine_options SET product_id = %s WHERE product_id = %s", (master_id, src_id))
            cur.execute("UPDATE product_combine_options SET component_product_id = %s WHERE component_product_id = %s", (master_id, src_id))
            cur.execute("DELETE FROM product_combine_options WHERE product_id = component_product_id")

            # 9. Product Prices (Tiers)
            cur.execute("SELECT * FROM product_prices WHERE product_id = %s", (src_id,))
            src_prices = cur.fetchall()
            for sp in src_prices:
                scheme_id = sp['pricing_scheme_id']
                cur.execute("SELECT id FROM product_prices WHERE product_id = %s AND pricing_scheme_id = %s", (master_id, scheme_id))
                mp = cur.fetchone()
                if mp:
                    cur.execute("DELETE FROM product_prices WHERE id = %s", (sp['id'],))
                else:
                    cur.execute("UPDATE product_prices SET product_id = %s WHERE id = %s", (master_id, sp['id']))
            cur.execute("DELETE FROM product_prices WHERE product_id = %s", (src_id,))

            # 10. Product Vendors
            cur.execute("SELECT * FROM product_vendors WHERE product_id = %s", (src_id,))
            src_vendors = cur.fetchall()
            for sv in src_vendors:
                v_id = sv['vendor_id']
                cur.execute("SELECT id FROM product_vendors WHERE product_id = %s AND vendor_id = %s", (master_id, v_id))
                mv = cur.fetchone()
                if mv:
                    cur.execute("DELETE FROM product_vendors WHERE id = %s", (sv['id'],))
                else:
                    cur.execute("UPDATE product_vendors SET product_id = %s WHERE id = %s", (master_id, sv['id']))
            cur.execute("DELETE FROM product_vendors WHERE product_id = %s", (src_id,))

            # 11. Delete the duplicate product record permanently so ONLY master is kept
            cur.execute("DELETE FROM products WHERE id = %s", (src_id,))

            # Verify deletion
            cur.execute("SELECT id FROM products WHERE id = %s", (src_id,))
            if cur.fetchone():
                raise RuntimeError(f"Failed to delete duplicate product #{src_id}")

        # 12. Apply any field overrides to Master Product
        update_fields = []
        update_params = []
        for field in ['name', 'sku', 'barcode', 'uom', 'category_id', 'default_price', 'standard_cost', 'description']:
            if field in overrides and overrides[field]:
                update_fields.append(f"{field} = %s")
                update_params.append(overrides[field])

        # If master product has no category assigned, adopt category from first source product with one
        if not master.get('category_id') and 'category_id' not in overrides:
            for s in sources:
                if s.get('category_id'):
                    update_fields.append("category_id = %s")
                    update_params.append(s['category_id'])
                    break

        # Append merged SKUs and barcodes to remarks for searchability
        if merged_skus or merged_barcodes:
            current_remarks = master.get('remarks') or ''
            audit_note = f"[Merged with SKUs: {', '.join(merged_skus)}]" if merged_skus else ""
            if merged_barcodes:
                audit_note += f" [Merged Barcodes: {', '.join(merged_barcodes)}]"
            new_remarks = f"{current_remarks}\n{audit_note}".strip() if current_remarks else audit_note
            update_fields.append("remarks = %s")
            update_params.append(new_remarks)

            # If master has no barcode but source had one, set master barcode
            if not master.get('barcode') and merged_barcodes and 'barcode' not in overrides:
                update_fields.append("barcode = %s")
                update_params.append(merged_barcodes[0])

        if update_fields:
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE products SET {', '.join(update_fields)} WHERE id = %s"
            update_params.append(master_id)
            cur.execute(sql, tuple(update_params))

    # Fetch updated master product
    updated_master = query_one("""
        SELECT p.*, COALESCE(c.name, 'Uncategorized') as category_name,
               COALESCE(inv.total_qty, 0) as current_qty
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_qty FROM inventory GROUP BY product_id
        ) inv ON p.id = inv.product_id
        WHERE p.id = %s
    """, (master_id,))

    return {
        'success': True,
        'master_id': master_id,
        'master_name': updated_master['name'] if updated_master else master['name'],
        'master_sku': updated_master['sku'] if updated_master else master['sku'],
        'master_category_name': updated_master['category_name'] if updated_master else (master.get('category_name') or 'Uncategorized'),
        'merged_source_ids': source_ids,
        'deleted_products': sources_summary,
        'sales_orders_relinked': total_so_relinked,
        'purchase_orders_relinked': total_po_relinked,
        'stock_units_consolidated': total_stock_moved,
        'merged_skus': merged_skus,
        'merged_barcodes': merged_barcodes
    }

def bulk_merge_all_duplicates(threshold=0.85, only_category_master=False):
    """
    Automatically detects duplicate product clusters and merges them:
    - Prioritizes the product with an exact category as master.
    - If only_category_master is True, only merges groups where master has an exact category.
    - Re-links all sales orders & lines from HQ and all branches to the master.
    - Re-links all purchase orders & lines to the master.
    - Consolidates warehouse inventory stocks across all locations into the master.
    - Moves inventory logs, transfers, adjustments, BOMs, vendor prices to master.
    - Permanently deletes the duplicate source product(s) (non-category duplicates).
    - Preserves 100% of orders, sales lines, and historical records.
    """
    groups = find_duplicate_groups(threshold=threshold, limit=500)
    merged_results = []
    total_deleted = 0
    total_so_relinked = 0
    total_po_relinked = 0
    total_stock_consolidated = 0

    for g in groups:
        products = g.get('products') or []
        if len(products) < 2:
            continue

        master = products[0]
        sources = products[1:]
        master_id = master['id']

        # Verify master still exists (might have been merged if clusters overlapped)
        m_row = query_one("SELECT id, name, category_id FROM products WHERE id = %s", (master_id,))
        if not m_row:
            continue

        # If only_category_master is requested, skip groups where master has no category
        master_has_cat = bool(m_row.get('category_id'))
        if only_category_master and not master_has_cat:
            continue

        # Filter sources that still exist
        source_ids = []
        for s in sources:
            s_row = query_one("SELECT id FROM products WHERE id = %s", (s['id'],))
            if s_row:
                source_ids.append(s['id'])

        if not source_ids:
            continue

        try:
            res = execute_product_merge(master_id, source_ids)
            merged_results.append({
                'master_id': master_id,
                'master_name': res.get('master_name') or master['name'],
                'master_sku': res.get('master_sku') or master.get('sku'),
                'master_category': res.get('master_category_name') or master.get('category_name'),
                'deleted_count': len(res.get('deleted_products', [])),
                'deleted_products': res.get('deleted_products', []),
                'sales_orders_relinked': res.get('sales_orders_relinked', 0),
                'purchase_orders_relinked': res.get('purchase_orders_relinked', 0),
                'stock_units_consolidated': res.get('stock_units_consolidated', 0)
            })
            total_deleted += len(res.get('deleted_products', []))
            total_so_relinked += res.get('sales_orders_relinked', 0)
            total_po_relinked += res.get('purchase_orders_relinked', 0)
            total_stock_consolidated += res.get('stock_units_consolidated', 0)
        except Exception as e:
            import logging
            logging.getLogger('inflow.product_merge').error(f"Error merging group for master #{master_id}: {e}")

    return {
        'success': True,
        'merged_groups_count': len(merged_results),
        'deleted_products_count': total_deleted,
        'total_sales_orders_relinked': total_so_relinked,
        'total_purchase_orders_relinked': total_po_relinked,
        'total_stock_units_consolidated': total_stock_consolidated,
        'groups': merged_results
    }
