-- ====================================================================
-- inFlow Premium Database Schema (PostgreSQL 16)
-- Enterprise-grade, high performance inventory & ERP architecture
-- ====================================================================

-- 1. Company Profile
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL DEFAULT 'inFlow Premium Business',
    phone VARCHAR(100),
    fax VARCHAR(100),
    email VARCHAR(255),
    website VARCHAR(255),
    address1 VARCHAR(255),
    address2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100) DEFAULT 'Cambodia',
    postal_code VARCHAR(50),
    tax_number VARCHAR(100),
    currency_code VARCHAR(10) DEFAULT 'USD',
    currency_symbol VARCHAR(10) DEFAULT '$',
    decimal_places_price INTEGER DEFAULT 2,
    decimal_places_cost INTEGER DEFAULT 3,
    decimal_places_qty INTEGER DEFAULT 0,
    decimal_places_markup INTEGER DEFAULT 2,
    decimal_places_total INTEGER DEFAULT 2,
    decimal_places_measurement INTEGER DEFAULT 2,
    logo_url TEXT,
    app_logo_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Product Categories
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2b. Store Branches (Multi-Branch Sales Operations)
CREATE TABLE IF NOT EXISTS branches (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(100),
    address TEXT,
    manager_name VARCHAR(150),
    so_prefix VARCHAR(20) DEFAULT 'SO-TK-',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Warehouse Locations (Shared Central Inventory)
CREATE TABLE IF NOT EXISTS locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    code VARCHAR(50),
    address TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    is_central BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Sublocations / Bins / Aisles
CREATE TABLE IF NOT EXISTS sublocations (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_loc_subloc UNIQUE(location_id, name)
);

-- 5. Pricing Schemes (Wholesale, Retail, Tier 1, etc.)
CREATE TABLE IF NOT EXISTS pricing_schemes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5b. Vendors / Suppliers
CREATE TABLE IF NOT EXISTS vendors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    contact_name VARCHAR(255),
    phone VARCHAR(100),
    email VARCHAR(255),
    address1 TEXT,
    address2 TEXT,
    city VARCHAR(100),
    country VARCHAR(100) DEFAULT 'Cambodia',
    postal_code VARCHAR(50),
    payment_terms VARCHAR(100) DEFAULT 'Net 30',
    currency_code VARCHAR(10) DEFAULT 'USD',
    balance NUMERIC(16, 4) DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Products Master Table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(100) UNIQUE,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    barcode VARCHAR(100),
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    uom VARCHAR(50) DEFAULT 'pcs',
    master_pack_qty NUMERIC(12, 4) DEFAULT 1.0,
    inner_pack_qty NUMERIC(12, 4) DEFAULT 1.0,
    default_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    reorder_point NUMERIC(12, 4) DEFAULT 0,
    reorder_quantity NUMERIC(12, 4) DEFAULT 0,
    min_stock NUMERIC(12, 4) DEFAULT 0,
    max_stock NUMERIC(12, 4) DEFAULT 0,
    standard_cost NUMERIC(16, 4) DEFAULT 0,
    average_cost NUMERIC(16, 4) DEFAULT 0,
    last_purchase_cost NUMERIC(16, 4) DEFAULT 0,
    default_price NUMERIC(16, 4) DEFAULT 0,
    is_sellable BOOLEAN DEFAULT TRUE,
    is_purchaseable BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    image_url TEXT,
    item_type VARCHAR(50) DEFAULT 'Stockable',
    tax_code VARCHAR(50) DEFAULT 'Taxable',
    costing_method VARCHAR(50) DEFAULT 'Manual',
    custom1 TEXT,
    custom2 TEXT,
    custom3 TEXT,
    custom4 TEXT,
    custom5 TEXT,
    default_sublocation VARCHAR(100),
    last_vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    sales_uom VARCHAR(50) DEFAULT 'cases',
    sales_uom_ratio NUMERIC(12, 4) DEFAULT 1.0,
    sales_uom_ratio_std NUMERIC(12, 4) DEFAULT 200.0,
    purchasing_uom VARCHAR(50) DEFAULT 'cases',
    purchasing_uom_ratio NUMERIC(12, 4) DEFAULT 1.0,
    purchasing_uom_ratio_std NUMERIC(12, 4) DEFAULT 1.0,
    length NUMERIC(12, 4),
    width NUMERIC(12, 4),
    height NUMERIC(12, 4),
    weight NUMERIC(12, 4),
    remarks TEXT,
    price_decimals INTEGER DEFAULT NULL,
    cost_decimals INTEGER DEFAULT NULL,
    qty_decimals INTEGER DEFAULT NULL,
    packs_per_case NUMERIC(12, 2) DEFAULT 3,
    pcs_per_pack NUMERIC(12, 2) DEFAULT 50,
    tier_qty_1 INTEGER DEFAULT 100,
    tier_qty_2 INTEGER DEFAULT 300,
    tier_qty_3 INTEGER DEFAULT 600,
    tier_price_1 NUMERIC(16, 4) DEFAULT NULL,
    tier_price_2 NUMERIC(16, 4) DEFAULT NULL,
    tier_price_3 NUMERIC(16, 4) DEFAULT NULL,
    price_card_notes TEXT DEFAULT '',
    combine_type VARCHAR(20) DEFAULT 'single',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6b. Product Attachments
CREATE TABLE IF NOT EXISTS product_attachments (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6c. Bill of Materials (BOM)
CREATE TABLE IF NOT EXISTS product_boms (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    description TEXT,
    quantity NUMERIC(12, 4) DEFAULT 1.0,
    cost NUMERIC(16, 4) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6c2. Product Combine Options & Multi-Component Sets (e.g. Bowls with Lids: Without Lid, Flat Lid, Clear PET Lid)
CREATE TABLE IF NOT EXISTS product_combine_options (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    option_name VARCHAR(255) NOT NULL,
    component_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    component_quantity NUMERIC(12, 4) DEFAULT 1.0,
    price_modifier NUMERIC(16, 4) DEFAULT 0.0,
    selling_price NUMERIC(16, 4) DEFAULT 0.0,
    is_default BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prod_combine_pid ON product_combine_options(product_id);

-- 6d. Product Version History
CREATE TABLE IF NOT EXISTS product_versions (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(500),
    sku VARCHAR(100),
    standard_cost NUMERIC(16, 4) DEFAULT 0,
    default_price NUMERIC(16, 4) DEFAULT 0,
    change_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prod_versions_pid ON product_versions(product_id);

-- 7. Product Prices by Scheme
CREATE TABLE IF NOT EXISTS product_prices (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    pricing_scheme_id INTEGER NOT NULL REFERENCES pricing_schemes(id) ON DELETE CASCADE,
    unit_price NUMERIC(16, 4) NOT NULL DEFAULT 0,
    CONSTRAINT uq_prod_scheme UNIQUE(product_id, pricing_scheme_id)
);

-- 8. Multi-Location Inventory Stock
CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    sublocation VARCHAR(100) NOT NULL DEFAULT '',
    quantity NUMERIC(14, 4) NOT NULL DEFAULT 0,
    reserved_quantity NUMERIC(14, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_inventory_loc UNIQUE(product_id, location_id, sublocation)
);

-- 9. Comprehensive Stock Movement Audit Ledger
CREATE TABLE IF NOT EXISTS inventory_logs (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    movement_type VARCHAR(50) NOT NULL, -- INITIAL, ADJUSTMENT, TRANSFER, SALE_PICK, SALE_SHIP, PO_RECEIVE, RETURN
    reference_type VARCHAR(50),         -- SO, PO, ADJUST, TRANSFER, MANUAL
    reference_id VARCHAR(100),
    from_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    to_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    quantity NUMERIC(14, 4) NOT NULL,
    qty_before NUMERIC(14, 4) DEFAULT 0,
    qty_after NUMERIC(14, 4) DEFAULT 0,
    unit_cost NUMERIC(16, 4) DEFAULT 0,
    reason TEXT,
    notes TEXT,
    created_by VARCHAR(100) DEFAULT 'system',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. Customers
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    contact_name VARCHAR(255),
    phone VARCHAR(100),
    fax VARCHAR(100),
    email VARCHAR(255),
    website VARCHAR(255),
    tax_number VARCHAR(100),
    address1 TEXT,
    address2 TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100) DEFAULT 'Cambodia',
    postal_code VARCHAR(50),
    billing_address TEXT,
    shipping_address TEXT,
    payment_terms VARCHAR(100) DEFAULT 'Due on Receipt',
    discount_percent NUMERIC(6, 2) DEFAULT 0,
    default_pricing_scheme_id INTEGER REFERENCES pricing_schemes(id) ON DELETE SET NULL,
    balance NUMERIC(16, 4) DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. Vendors / Suppliers (defined above for foreign key integrity)

-- 11b. Product Vendors Catalog (BASE_VendorItem mapping)
CREATE TABLE IF NOT EXISTS product_vendors (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    vendor_item_code VARCHAR(100),
    cost NUMERIC(16, 4) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_product_vendor UNIQUE(product_id, vendor_id)
);
CREATE INDEX IF NOT EXISTS idx_prod_vendors_pid ON product_vendors(product_id);

-- 12. Sales Orders
CREATE TABLE IF NOT EXISTS sales_orders (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(100) NOT NULL UNIQUE,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'OPEN', -- QUOTE, OPEN, PICKED, PACKED, SHIPPED, INVOICED, PAID, CANCELLED
    payment_status VARCHAR(50) NOT NULL DEFAULT 'UNPAID', -- UNPAID, PARTIAL, PAID
    subtotal NUMERIC(16, 4) DEFAULT 0,
    tax_rate NUMERIC(6, 2) DEFAULT 0,
    tax_amount NUMERIC(16, 4) DEFAULT 0,
    discount_amount NUMERIC(16, 4) DEFAULT 0,
    shipping_fee NUMERIC(16, 4) DEFAULT 0,
    total_amount NUMERIC(16, 4) DEFAULT 0,
    paid_amount NUMERIC(16, 4) DEFAULT 0,
    balance_due NUMERIC(16, 4) DEFAULT 0,
    sales_rep VARCHAR(100),
    po_number VARCHAR(100),
    carrier VARCHAR(100),
    tracking_number VARCHAR(100),
    picked_date TIMESTAMP WITH TIME ZONE,
    packed_date TIMESTAMP WITH TIME ZONE,
    shipped_date TIMESTAMP WITH TIME ZONE,
    invoiced_date TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    customer_address TEXT,
    customer_contact VARCHAR(255),
    customer_phone VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 13. Sales Order Lines
CREATE TABLE IF NOT EXISTS sales_order_lines (
    id SERIAL PRIMARY KEY,
    sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    line_num INTEGER NOT NULL DEFAULT 1,
    product_id INTEGER REFERENCES products(id) ON DELETE RESTRICT,
    description TEXT,
    quantity NUMERIC(14, 4) NOT NULL DEFAULT 1,
    unit_price NUMERIC(16, 4) NOT NULL DEFAULT 0,
    discount_percent NUMERIC(6, 2) DEFAULT 0,
    subtotal NUMERIC(16, 4) NOT NULL DEFAULT 0,
    cost_price NUMERIC(16, 4) DEFAULT 0,
    picked_qty NUMERIC(14, 4) DEFAULT 0,
    packed_qty NUMERIC(14, 4) DEFAULT 0,
    shipped_qty NUMERIC(14, 4) DEFAULT 0,
    addon_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    addon_quantity NUMERIC(12, 4) DEFAULT 1.0,
    combine_option_id INTEGER REFERENCES product_combine_options(id) ON DELETE SET NULL
);

-- 13b. Sales Order Attachments (Photos, Proof of Delivery, Invoices, Slips)
CREATE TABLE IF NOT EXISTS sales_order_attachments (
    id SERIAL PRIMARY KEY,
    sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    file_type VARCHAR(100),
    caption TEXT,
    uploaded_by VARCHAR(150),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_so_attachments_order_id ON sales_order_attachments(sales_order_id);

-- 13c. Sales Order Version History & Snapshot Audit
CREATE TABLE IF NOT EXISTS sales_order_versions (
    id SERIAL PRIMARY KEY,
    sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL DEFAULT 1,
    order_number VARCHAR(100),
    status VARCHAR(50),
    payment_status VARCHAR(50),
    customer_name VARCHAR(255),
    total_amount NUMERIC(16, 4) DEFAULT 0,
    paid_amount NUMERIC(16, 4) DEFAULT 0,
    balance_due NUMERIC(16, 4) DEFAULT 0,
    items_count INTEGER DEFAULT 0,
    user_name VARCHAR(150),
    change_summary TEXT,
    snapshot_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_so_versions_order_id ON sales_order_versions(sales_order_id);

-- 14. Purchase Orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(100) NOT NULL UNIQUE,
    vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expected_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT', -- DRAFT, ISSUED, PARTIAL_RECEIVED, RECEIVED, PAID, CANCELLED
    payment_status VARCHAR(50) NOT NULL DEFAULT 'UNPAID', -- UNPAID, PARTIAL, PAID
    subtotal NUMERIC(16, 4) DEFAULT 0,
    discount_amount NUMERIC(16, 4) DEFAULT 0,
    tax_rate NUMERIC(6, 2) DEFAULT 0,
    tax_amount NUMERIC(16, 4) DEFAULT 0,
    shipping_fee NUMERIC(16, 4) DEFAULT 0,
    total_amount NUMERIC(16, 4) DEFAULT 0,
    paid_amount NUMERIC(16, 4) DEFAULT 0,
    balance_due NUMERIC(16, 4) DEFAULT 0,
    carrier VARCHAR(100),
    vendor_invoice_no VARCHAR(100),
    contact VARCHAR(255),
    phone VARCHAR(50),
    vendor_address TEXT,
    non_vendor_costs NUMERIC(16, 4) DEFAULT 0,
    currency_code VARCHAR(10) DEFAULT 'USD',
    received_date TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 15. Purchase Order Lines
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    line_num INTEGER NOT NULL DEFAULT 1,
    product_id INTEGER REFERENCES products(id) ON DELETE RESTRICT,
    description TEXT,
    vendor_product_code VARCHAR(100),
    quantity NUMERIC(14, 4) NOT NULL DEFAULT 1,
    uom VARCHAR(50) DEFAULT 'pcs.',
    unit_cost NUMERIC(16, 4) NOT NULL DEFAULT 0,
    discount_percent NUMERIC(6, 2) DEFAULT 0,
    subtotal NUMERIC(16, 4) NOT NULL DEFAULT 0,
    received_qty NUMERIC(14, 4) DEFAULT 0
);

-- 15b. Purchase Order Attachments (Photos, Invoices, Delivery Slips)
CREATE TABLE IF NOT EXISTS purchase_order_attachments (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    file_type VARCHAR(100),
    caption TEXT,
    uploaded_by VARCHAR(150),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_po_attachments_order_id ON purchase_order_attachments(purchase_order_id);

-- 16. Stock Transfers (Inter-warehouse)
CREATE TABLE IF NOT EXISTS stock_transfers (
    id SERIAL PRIMARY KEY,
    transfer_number VARCHAR(100) NOT NULL UNIQUE,
    from_location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    to_location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT', -- DRAFT, COMPLETED, CANCELLED
    transfer_date DATE NOT NULL DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 17. Stock Transfer Lines
CREATE TABLE IF NOT EXISTS stock_transfer_lines (
    id SERIAL PRIMARY KEY,
    transfer_id INTEGER NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity NUMERIC(14, 4) NOT NULL DEFAULT 1
);

-- 18. Stock Adjustments (Physical counts & Reconciliation)
CREATE TABLE IF NOT EXISTS stock_adjustments (
    id SERIAL PRIMARY KEY,
    adjustment_number VARCHAR(100) NOT NULL UNIQUE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    adjustment_date DATE NOT NULL DEFAULT CURRENT_DATE,
    reason VARCHAR(100) NOT NULL DEFAULT 'Recount', -- Recount, Damaged, Shrinkage, Found Stock, Internal Use, Other
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED', -- DRAFT, COMPLETED
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 19. Stock Adjustment Lines
CREATE TABLE IF NOT EXISTS stock_adjustment_lines (
    id SERIAL PRIMARY KEY,
    adjustment_id INTEGER NOT NULL REFERENCES stock_adjustments(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    old_qty NUMERIC(14, 4) NOT NULL DEFAULT 0,
    new_qty NUMERIC(14, 4) NOT NULL DEFAULT 0,
    diff_qty NUMERIC(14, 4) NOT NULL DEFAULT 0,
    unit_cost NUMERIC(16, 4) DEFAULT 0
);

-- 20. Application System Settings
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ====================================================================
-- PERFORMANCE INDEXES (Sub-millisecond query execution)
-- ====================================================================
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_name ON products USING gin(to_tsvector('simple', name));

CREATE INDEX IF NOT EXISTS idx_inventory_prod_loc ON inventory(product_id, location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_qty ON inventory(quantity);

CREATE INDEX IF NOT EXISTS idx_inv_logs_prod ON inventory_logs(product_id);
CREATE INDEX IF NOT EXISTS idx_inv_logs_created ON inventory_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inv_logs_type ON inventory_logs(movement_type);

CREATE INDEX IF NOT EXISTS idx_so_number ON sales_orders(order_number);
CREATE INDEX IF NOT EXISTS idx_so_customer ON sales_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_so_status ON sales_orders(status);
CREATE INDEX IF NOT EXISTS idx_so_date ON sales_orders(order_date DESC);

CREATE INDEX IF NOT EXISTS idx_so_lines_so ON sales_order_lines(sales_order_id);
CREATE INDEX IF NOT EXISTS idx_so_lines_prod ON sales_order_lines(product_id);

CREATE INDEX IF NOT EXISTS idx_po_number ON purchase_orders(order_number);
CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders(vendor_id);
CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_po_date ON purchase_orders(order_date DESC);

CREATE INDEX IF NOT EXISTS idx_po_lines_po ON purchase_order_lines(purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_prod ON purchase_order_lines(product_id);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_vendors_name ON vendors(name);

-- 21. Order Payments Audit Ledger (Sales Orders & Purchase Orders)
CREATE TABLE IF NOT EXISTS order_payments (
    id SERIAL PRIMARY KEY,
    order_type VARCHAR(10) NOT NULL, -- 'SO' or 'PO'
    order_id INTEGER NOT NULL,
    amount NUMERIC(16, 4) NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    payment_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reference VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payments_order ON order_payments(order_type, order_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON order_payments(payment_date DESC);

-- Sequences for concurrent-safe sequential numbering
CREATE SEQUENCE IF NOT EXISTS so_number_seq;
CREATE SEQUENCE IF NOT EXISTS po_number_seq;
CREATE SEQUENCE IF NOT EXISTS adj_number_seq;
CREATE SEQUENCE IF NOT EXISTS trf_number_seq;

-- 22. Invoice Customization Settings
CREATE TABLE IF NOT EXISTS invoice_settings (
    id SERIAL PRIMARY KEY,
    font_family VARCHAR(100) DEFAULT 'Kantumruy Pro',
    primary_color VARCHAR(50) DEFAULT '#0284C7',
    secondary_color VARCHAR(50) DEFAULT '#0F172A',
    logo_url TEXT,
    shop_name_kh VARCHAR(255) DEFAULT 'ក្រុមហ៊ុន អ៊ិនហ្វ្លូ ត្រេឌីង (ខេមបូឌា)',
    shop_name_en VARCHAR(255) DEFAULT 'inFlow Premium Trading Co., Ltd.',
    shop_address_kh TEXT DEFAULT 'ផ្ទះលេខ ១២៣, មហាវិថីព្រះមុនីវង្ស, សង្កាត់បឹងកេងកង១, ខណ្ឌចំការមន, រាជធានីភ្នំពេញ',
    shop_address_en TEXT DEFAULT '#123, Preah Monivong Blvd, Sangkat Boeung Keng Kang 1, Phnom Penh, Cambodia',
    phone VARCHAR(100) DEFAULT '+855 23 888 999 / +855 12 345 678',
    email VARCHAR(100) DEFAULT 'billing@inflowpremium.com.kh',
    website VARCHAR(100) DEFAULT 'www.inflowpremium.com.kh',
    vat_tin VARCHAR(100) DEFAULT 'K001-902103456',
    invoice_title_kh VARCHAR(100) DEFAULT 'វិក្កយបត្រ',
    invoice_title_en VARCHAR(100) DEFAULT 'INVOICE',
    enable_khr_total BOOLEAN DEFAULT TRUE,
    khr_exchange_rate NUMERIC(12, 2) DEFAULT 4100.00,
    qr_code_url TEXT,
    bank_name VARCHAR(100) DEFAULT 'ABA Bank (KHQR / Bakong)',
    account_name VARCHAR(150) DEFAULT 'INFLOW TRADING CO LTD',
    account_number VARCHAR(100) DEFAULT '001 234 567 (USD) | 001 234 568 (KHR)',
    payment_terms TEXT DEFAULT 'ទូទាត់ភ្លាមៗពេលទទួលទំនិញ / Due on Receipt',
    footer_notes_kh TEXT DEFAULT 'ទំនិញដែលបានទិញរួចមិនអាចប្តូរវិញបានទេ! សូមអរគុណចំពោះការគាំទ្ររបស់លោកអ្នក!',
    footer_notes_en TEXT DEFAULT 'Goods sold are not returnable. Thank you for your business!',
    show_signature BOOLEAN DEFAULT TRUE,
    show_sku BOOLEAN DEFAULT TRUE,
    show_tax BOOLEAN DEFAULT TRUE,
    qr_size INTEGER DEFAULT 180,
    qr_position VARCHAR(50) DEFAULT 'left',
    bank_info_size VARCHAR(50) DEFAULT 'small',
    bank_info_position VARCHAR(50) DEFAULT 'below_qr',
    qr_offset_x INTEGER DEFAULT 0,
    qr_offset_y INTEGER DEFAULT 0,
    bank_offset_x INTEGER DEFAULT 0,
    bank_offset_y INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS qr_size INTEGER DEFAULT 180;
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS qr_position VARCHAR(50) DEFAULT 'left';
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS bank_info_size VARCHAR(50) DEFAULT 'small';
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS bank_info_position VARCHAR(50) DEFAULT 'below_qr';
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS qr_offset_x INTEGER DEFAULT 0;
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS qr_offset_y INTEGER DEFAULT 0;
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS bank_offset_x INTEGER DEFAULT 0;
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS bank_offset_y INTEGER DEFAULT 0;

-- 23. Delivery Services / Carriers (Cambodia)
CREATE TABLE IF NOT EXISTS delivery_services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(50),
    phone VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 24. Expenses & Daily Expense Tracker (Matching Monthly report for Premium Package)
CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
    item VARCHAR(255) NOT NULL,
    category VARCHAR(100) DEFAULT 'General',
    unit_price NUMERIC(16, 2) NOT NULL DEFAULT 0,
    quantity NUMERIC(10, 2) NOT NULL DEFAULT 1,
    total_price NUMERIC(16, 2) NOT NULL DEFAULT 0,
    paid_by VARCHAR(100) DEFAULT '',
    payment_account VARCHAR(100) DEFAULT 'Cash',
    notes TEXT,
    month_key VARCHAR(7) NOT NULL, -- e.g. '2026-10'
    branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE expenses ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_expenses_month ON expenses(month_key);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_branch ON expenses(branch_id);

-- 25. Monthly Cash & Financial Summaries (Monthly report settings & bank/cash breakdown per store/branch)
CREATE TABLE IF NOT EXISTS monthly_cash_summaries (
    id SERIAL PRIMARY KEY,
    month_key VARCHAR(7) NOT NULL, -- e.g. '2026-10'
    branch_id INTEGER REFERENCES branches(id) ON DELETE CASCADE,
    opening_balance NUMERIC(16, 2) DEFAULT 0, -- លុយចាស់ (Calculated or saved)
    manual_opening_balance NUMERIC(16, 2), -- User manual override if filled; if null/empty auto-uses previous month money in hand
    media_expense NUMERIC(16, 2) DEFAULT 0, -- Media legacy/cached field
    manual_media_income NUMERIC(16, 2), -- User manual override if filled; if null/empty auto-uses sum from media_receipts
    clear_stm NUMERIC(16, 2) DEFAULT 0, -- Clear STM
    custom_sales_income NUMERIC(16, 2), -- Optional manual override for លុយលក់
    accounts_json JSONB DEFAULT '{"ABA": 0, "Cash USD": 0, "Cash KHR": 0, "ACELEDA": 0, "WING": 0, "Office": 0, "Teamwork": 0, "Tola": 0, "Borrow": 0}'::jsonb,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE monthly_cash_summaries ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id) ON DELETE CASCADE;
ALTER TABLE monthly_cash_summaries DROP CONSTRAINT IF EXISTS monthly_cash_summaries_month_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly_cash_summaries_month_branch ON monthly_cash_summaries(month_key, COALESCE(branch_id, 0));
CREATE INDEX IF NOT EXISTS idx_monthly_cash_summaries_branch ON monthly_cash_summaries(branch_id);

-- 26. Media Receipts / Money Received from Media (ប្រាក់ទទួលបានពី Media)
CREATE TABLE IF NOT EXISTS media_receipts (
    id SERIAL PRIMARY KEY,
    receipt_date DATE NOT NULL DEFAULT CURRENT_DATE,
    customer_name VARCHAR(255) NOT NULL,
    amount NUMERIC(16, 2) NOT NULL DEFAULT 0,
    notes TEXT,
    month_key VARCHAR(7) NOT NULL, -- e.g. '2026-10'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_media_receipts_month ON media_receipts(month_key);
CREATE INDEX IF NOT EXISTS idx_media_receipts_date ON media_receipts(receipt_date);

-- 27. Branch Customizations & Settings
ALTER TABLE branches ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#FF5A5F';
ALTER TABLE branches ADD COLUMN IF NOT EXISTS settings_json JSONB DEFAULT '{}'::jsonb;

-- 28. System Users & Access Control (Main Store Admin vs Branch Admin)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(150) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(100),
    role VARCHAR(50) NOT NULL DEFAULT 'branch_admin', -- 'main_admin', 'branch_admin', 'branch_cashier'
    branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
    permissions_json JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_branch_id ON users(branch_id);

-- 29. Application Branding
ALTER TABLE companies ADD COLUMN IF NOT EXISTS app_logo_url TEXT;

-- 30. Delivery Personnel & Logistics
CREATE TABLE IF NOT EXISTS delivery_men (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) UNIQUE NOT NULL,
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_delivery_men_name ON delivery_men(name);

ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS delivery_man VARCHAR(150);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS delivery_helper VARCHAR(150);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS delivery_fee_khr NUMERIC(14, 2) DEFAULT 0;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50);

ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS contact VARCHAR(255);
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS vendor_address TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS currency_code VARCHAR(10) DEFAULT 'USD';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(16, 4) DEFAULT 0;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS non_vendor_costs NUMERIC(16, 4) DEFAULT 0;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS vendor_invoice_no VARCHAR(100);

ALTER TABLE purchase_order_lines ADD COLUMN IF NOT EXISTS discount_percent NUMERIC(6, 2) DEFAULT 0;
ALTER TABLE purchase_order_lines ADD COLUMN IF NOT EXISTS vendor_product_code VARCHAR(100);

-- 31. Database Backup & Google Drive Integration
CREATE TABLE IF NOT EXISTS backup_settings (
    id SERIAL PRIMARY KEY,
    auto_backup_enabled BOOLEAN DEFAULT FALSE,
    auto_backup_frequency VARCHAR(50) DEFAULT 'daily',
    auto_backup_time VARCHAR(10) DEFAULT '23:00',
    auto_save_gdrive BOOLEAN DEFAULT FALSE,
    gdrive_mode VARCHAR(50) DEFAULT 'local_sync',
    gdrive_local_path TEXT DEFAULT 'G:\My Drive\inFlow_Backups',
    gdrive_folder_id VARCHAR(255) DEFAULT '',
    gdrive_service_account_json TEXT DEFAULT '',
    retention_count INTEGER DEFAULT 15,
    last_backup_at TIMESTAMP WITH TIME ZONE,
    last_backup_status VARCHAR(50),
    last_backup_file TEXT,
    last_backup_size BIGINT DEFAULT 0,
    last_gdrive_sync_at TIMESTAMP WITH TIME ZONE,
    last_gdrive_sync_status VARCHAR(50),
    last_gdrive_error TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backup_logs (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    filepath TEXT NOT NULL,
    file_size_bytes BIGINT DEFAULT 0,
    backup_type VARCHAR(50) DEFAULT 'manual',
    status VARCHAR(50) DEFAULT 'completed',
    error_message TEXT,
    gdrive_status VARCHAR(50) DEFAULT 'none',
    gdrive_details TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
