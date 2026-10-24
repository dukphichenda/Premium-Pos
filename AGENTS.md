# inFlow Premium - Project Rules & Guidelines

## 1. Product Catalog Protection (Strict & Absolute)
- **Zero Product Mutations Outside Product Catalog Tasks**:
  - When correcting, editing, debugging, or importing sales orders, purchase orders, customers, reports, or any other features:
  - **DO NOT change, delete, or edit anything in `products` and product details**.
  - This includes: `products` table, `product_boms`, `product_prices`, `product_vendors`, `product_attachments`, `product_versions`, `sku`, `name`, `default_price`, `cost`, `standard_cost`, `average_cost`, `uom`, `sales_uom`, `purchasing_uom`, `packaging`, `images`, `categories`, or kit components.
  - Sales order and purchase order imports must **never** create new products or mutate existing products. If an item code/name does not match the product catalog, it is treated as an unlinked line item or mapped via user replacement only, never altering the catalog product itself.
  - Any product creation, update, or deletion must **only** occur if the USER explicitly and directly asks to edit or manage the product catalog.

## 2. Sales Order Import Rules
- Under "Keep existing data and add / update records" mode:
  - New orders: added with their line items.
  - Existing orders with status changes: **only** status and payment status fields are updated. Existing order lines and customer profiles are **never** deleted, modified, or overwritten.
  - Existing orders with unchanged status: skipped completely.
  - The import preview must show **only** actionable orders (new orders and orders with status updates). Unchanged orders are excluded from preview.
