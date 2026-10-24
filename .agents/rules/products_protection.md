---
description: Absolute protection of products and product details during imports and editing
globs: **/*
---

# Product Catalog Protection Rule

- **Do NOT change, delete, or edit anything in products and product details**:
  - When fixing bugs, refactoring, adding features, or running data imports (especially Sales Orders and Purchase Orders), the `products` table and all associated tables (`product_boms`, `product_prices`, `product_vendors`, `product_attachments`, `product_versions`) must remain completely untouched.
  - Never run `UPDATE products`, `INSERT INTO products`, or `DELETE FROM products` during sales order imports, sales order edits, or any non-product feature work.
  - Do not alter prices, costs, barcodes, units of measure (UOM), packaging ratios, images, categories, or kit components.
  - Product modifications are strictly prohibited unless the user explicitly and specifically instructs to modify products in the product catalog.
