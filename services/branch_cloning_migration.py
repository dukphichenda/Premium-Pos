import sys
import json
sys.path.insert(0, '.')
from database import execute, query_all, query_one

def run_migration():
    print("Starting branch cloning and permissions schema migration...")

    # Default permissions dictionary
    default_permissions = {
        "dashboard": True,
        "pos": True,
        "sales_orders": True,
        "invoices": True,
        "inventory": True,
        "transfers": True,
        "adjustments": False,
        "purchasing": False,
        "expenses": True,
        "customers": True,
        "reports": True,
        "edit_prices": False,
        "view_costs": False
    }

    full_permissions = {
        "dashboard": True,
        "pos": True,
        "sales_orders": True,
        "invoices": True,
        "inventory": True,
        "transfers": True,
        "adjustments": True,
        "purchasing": True,
        "expenses": True,
        "customers": True,
        "reports": True,
        "edit_prices": True,
        "view_costs": True
    }

    execute("""
        ALTER TABLE branches 
        ADD COLUMN IF NOT EXISTS permissions_json JSONB DEFAULT %s,
        ADD COLUMN IF NOT EXISTS location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS is_main BOOLEAN DEFAULT FALSE;
    """, (json.dumps(default_permissions),))

    execute("""
        ALTER TABLE stock_transfers
        ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;
    """)

    execute("""
        ALTER TABLE stock_adjustments
        ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;
    """)

    execute("""
        ALTER TABLE purchase_orders
        ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;
    """)

    # Link Branch 1 (STM) to Location 101 if exists, and give full permissions
    execute("""
        UPDATE branches 
        SET location_id = 101,
            permissions_json = %s
        WHERE id = 1 AND (location_id IS NULL OR permissions_json IS NULL);
    """, (json.dumps(full_permissions),))

    print("Checking columns in branches:")
    cols = query_all("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'branches'")
    for c in cols:
        print(f" - {c['column_name']} ({c['data_type']})")

    b1 = query_one("SELECT id, name, location_id, permissions_json FROM branches WHERE id = 1")
    print("Branch 1:", b1['id'], b1['location_id'], b1['permissions_json'])
    print("Branch cloning schema migration finished successfully!")

if __name__ == '__main__':
    run_migration()
