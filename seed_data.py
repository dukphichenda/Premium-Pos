import logging
from database import init_db, execute, query_one

logger = logging.getLogger('inflow.seed')

def seed_sample_data():
    """
    Populates sample data if database is empty.
    """
    init_db()

    # Check if products already exist
    count = query_one("SELECT COUNT(*) as cnt FROM products")['cnt']
    if count > 0:
        logger.info(f"Database already contains {count} products. Skipping sample seeding.")
        return False

    logger.info("Seeding initial company, locations, and sample inventory data...")

    # 1. Company
    execute("""
        INSERT INTO companies (name, email, phone, address1, city, country, currency_code, currency_symbol)
        VALUES ('inFlow Premium Wholesale & Packaging', 'sales@inflowpremium.local', '+855 23 888 999', 'Russian Federation Blvd', 'Phnom Penh', 'Cambodia', 'USD', '$')
        ON CONFLICT DO NOTHING;
    """)

    # 2. Locations
    execute("""
        INSERT INTO locations (name, code, is_default, is_active)
        VALUES 
            ('Main Warehouse', 'WH-MAIN', TRUE, TRUE),
            ('STM Warehouse', 'WH-STM', FALSE, TRUE),
            ('Display Showroom', 'SHOWROOM', FALSE, TRUE)
        ON CONFLICT (name) DO NOTHING;
    """)

    # 3. Categories
    execute("""
        INSERT INTO categories (name, description)
        VALUES 
            ('Plastic Containers', 'Food-grade plastic meal boxes and cups'),
            ('Paper Packaging', 'Eco-friendly biodegradable paper bags and bowls'),
            ('Bottles & Jars', 'Plastic and glass beverage containers'),
            ('Cutlery & Straws', 'Forks, spoons, and accessories')
        ON CONFLICT DO NOTHING;
    """)

    # 4. Pricing Schemes
    execute("""
        INSERT INTO pricing_schemes (name, is_default)
        VALUES 
            ('Wholesale Base', TRUE),
            ('VIP Distributor', FALSE),
            ('Walk-in Retail', FALSE)
        ON CONFLICT DO NOTHING;
    """)

    # 5. Sample Products
    sample_products = [
        ('SKU-1001', 'HT17-2-TTK ប្រអប់បាយ២ថត 500 pcs/Case', 'Premium 2-compartment meal box', '8850001001', 1, 'case', 500, 1, 1, 10, 50, 14.50, 14.50, 14.50, 18.00),
        ('SKU-1002', 'HT17-1-TTK ប្រអប់បាយ1ថត 500 pcs/Case', 'Standard single compartment food box', '8850001002', 1, 'case', 500, 1, 1, 15, 60, 13.00, 13.00, 13.00, 16.50),
        ('SKU-1003', 'ដបជ្រុងកធំ 330 Square Bottle 200 pcs/Pack', 'Clear PET beverage bottle 330ml', '8850001003', 3, 'pack', 200, 1, 1, 20, 80, 8.20, 8.20, 8.20, 11.00),
        ('SKU-1004', 'Eco Bagasse Bowl 850ml 300 pcs/Box', 'Sugar cane fiber eco soup bowl', '8850001004', 2, 'box', 300, 1, 2, 5, 30, 22.00, 22.00, 22.00, 28.00),
        ('SKU-1005', 'Bio Fork & Spoon Set 1000 pcs/Box', 'Heavy duty wrapped biodegradable cutlery', '8850001005', 4, 'box', 1000, 1, 1, 8, 40, 9.50, 9.50, 9.50, 13.50)
    ]

    for p in sample_products:
        execute("""
            INSERT INTO products (sku, name, description, barcode, category_id, uom, master_pack_qty, inner_pack_qty, default_location_id, reorder_point, reorder_quantity, standard_cost, average_cost, last_purchase_cost, default_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sku) DO NOTHING;
        """, p)

    # 6. Sample Customers
    execute("""
        INSERT INTO customers (name, contact_name, phone, email, address1, city, balance)
        VALUES 
            ('Bamboo Hut Restaurant', 'Mr. David', '+855 71 773 9643', 'contact@bamboohut.local', 'St 310, BKK1', 'Phnom Penh', 250.00),
            ('Khmer Kitchen Chain', 'Ms. Sreyneang', '+855 12 345 678', 'srey@khmerkitchen.local', 'Riverside Blvd', 'Phnom Penh', 0.00),
            ('Cafe Amazon Franchisee', 'Mr. Rithy', '+855 98 223 344', 'rithy@cafeamazon.local', 'TK Avenue', 'Phnom Penh', 0.00)
        ON CONFLICT DO NOTHING;
    """)

    # 7. Sample Vendors
    execute("""
        INSERT INTO vendors (name, contact_name, phone, email, address1, city)
        VALUES 
            ('Thai Plastic Packaging Co., Ltd', 'Sompong', '+66 2 123 4567', 'sales@thaiplastic.co.th', 'Bangna Trad Km 18', 'Bangkok'),
            ('EcoPack Industries China', 'Mr. Chen', '+86 20 8899 0011', 'export@ecopack-cn.com', 'Huangpu District', 'Guangzhou')
        ON CONFLICT DO NOTHING;
    """)

    # 8. Initial Inventory
    prods = query_one("SELECT id FROM products LIMIT 1")
    if prods:
        loc = query_one("SELECT id FROM locations WHERE is_default = TRUE LIMIT 1")
        execute("""
            INSERT INTO inventory (product_id, location_id, sublocation, quantity)
            SELECT id, %s, 'A-01', 100 FROM products
            ON CONFLICT DO NOTHING;
        """, (loc['id'],))

    logger.info("Sample data seeded successfully!")
    return True

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    seed_sample_data()
