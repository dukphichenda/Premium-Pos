# inFlow Premium (v2.0 Enterprise)

A state-of-the-art, high-performance, modern Web ERP and Inventory Management System engineered around the concepts of **inFlow Inventory**, powered by **PostgreSQL 16** on localhost with lightning-fast response times (< 2ms query latency), responsive UI, and native Khmer Unicode and English support.

---

## 1. Deep Overview of Legacy inFlow vs inFlow Premium

| Feature | Legacy inFlow (`C:\Program Files (x86)\inFlow Inventory`) | inFlow Premium (`f:\inflow premium`) |
| :--- | :--- | :--- |
| **Platform** | Windows desktop (.NET WinForms / C# 2.0 / 3.5) | Modern Responsive Web Application (Localhost & LAN) |
| **Database** | Microsoft SQL Server Express (`.\INFLOWSQL`) | **PostgreSQL 16** (ACID compliant, high concurrency) |
| **Performance** | Desktop heavy rendering, UI freezes on large orders | Sub-millisecond indexed queries, streaming web UI |
| **Unicode Fidelity** | Legacy code-page encoding issues with complex scripts | **Native UTF-8 Unicode** (Khmer, English, Chinese) |
| **Order Lifecycle** | Rigid desktop forms (Quote -> Pick -> Pack -> Ship) | Dynamic reactive workflow stepper with 1-click status transitions |
| **Audit Ledger** | Separate batch procedures (`BASE_InventoryLogBatch`) | Instant double-entry movement ledger (`inventory_logs`) |
| **Reporting** | Crystal Reports (`.rpt`) dependent on desktop runtime | Web-native responsive reports with 1-click CSV & printouts |
| **Migration** | Manual backup/restore (`.ifi` files) | **1-Click automated ETL** directly from legacy SQL Server |

---

## 2. Core Modules & Business Concepts

### 📦 1. Products Master Catalog
- **Specification Details**: SKU, Name, Description, Barcode/UPC, Category, UOM (pcs, case, box, bottle), Master & Inner Pack quantities.
- **Costing & Pricing**: Standard Cost, Moving Average Cost, Last Purchase Cost, Wholesale Base Price, and multi-tier Pricing Schemes.
- **Stock Rules**: Minimum stock, Maximum stock, Reorder Point, and Reorder Quantity.
- **Product 360° View**: Multi-warehouse stock distribution, pricing tier margins, and full stock movement history.

### 🏢 2. Multi-Warehouse Inventory Matrix
- Real-time stock levels across warehouses (**Main Warehouse**, **STM Warehouse**, **Showroom**).
- **Stock Adjustments**: Cycle recounts, damaged goods write-offs, shrinkage, and found inventory with before/after units and audit tracking.
- **Inter-Warehouse Transfers**: Source to destination warehouse transfer dispatch and receipt.
- **Reorder Assistant**: Automatic calculation of items below reorder points with suggested order quantities and 1-click PO generator.

### 🛒 3. Sales Order Fulfillment Lifecycle
- **Stages**: `Quote` ➔ `Open` ➔ `Picked` ➔ `Packed` ➔ `Shipped` ➔ `Invoiced` ➔ `Paid`.
- **Order Builder**: Fast customer selection with credit terms, line item product lookup with live on-hand stock indicators, automatic tax and discounts.
- **1-Click Shipment**: Deducts physical warehouse stock and creates ledger audit entries.
- **Receivables & Payments**: Cash, Bank Transfer (Bakong KHQR, ABA), Cheque payments with live balance recalculation.
- **Printable Documents**: Commercial Sales Invoice, Warehouse Pick List, and Packing Slip.

### 📥 4. Purchase Orders & Vendor Receiving
- **Stages**: `Draft` ➔ `Issued` ➔ `Received` ➔ `Paid`.
- **Vendor Management**: Supplier contact details, credit terms, and accounts payable balances.
- **1-Click Warehouse Receiving**: Increments on-hand inventory, recalculates moving average unit cost, and creates ledger records.
- **Printable Documents**: Official Purchase Order document.

### 📊 5. Executive Reports & Intelligence
- **Inventory Valuation Report**: Itemized stock valuation at cost vs retail, breakdown by warehouse and category, with CSV export.
- **Sales & Profit Margin Report**: Gross sales revenue, Cost of Goods Sold (COGS), Gross Profit, and Margin %.
- **Stock Movement Audit Ledger**: Chronological transaction history of every single inventory change with timestamps, references, and reasons.

### 🔄 6. Legacy inFlow SQL Server ETL Sync Hub
- Built-in connection to `.\INFLOWSQL` database `inFlow`.
- Fast batched migration engine (`migrate_inflow.py`) migrating:
  - **406** Products & Specifications
  - **2,602** Customers
  - **24** Vendors
  - **4** Warehouses
  - **20** Categories
  - **8** Pricing Schemes & 1,944 Tiers
  - **792** Stock level records
  - **22,774** Sales Orders & **50,324** Line Items
  - **462** Purchase Orders & **1,982** Line Items
- Completed in **5.71 seconds** using batched binary insertion!

---

## 3. Technology Stack

- **Backend**: Python 3.12 (Flask 3.1.3, psycopg2 2.9.9, pyodbc 5.3.0)
- **Database**: PostgreSQL 16.4 on port 5432
- **Frontend**: Clean Modern CSS, Semantic HTML5, Chart.js 4.4, Vanilla JS controllers
- **Typography**: Plus Jakarta Sans, Kantumruy Pro (Khmer Unicode), JetBrains Mono

---

## 4. How to Run

### 1-Click Launch:
Double-click `run.bat` or run in terminal:
```cmd
run.bat
```
The application will launch on **`http://localhost:5050`** and open your default browser.

### Run Tests:
```cmd
"E:\odoo-ai-19.0\odoo-ai-19.0\runtime\python3\python.exe" -m unittest discover tests
```

### Re-run Migration from Legacy inFlow:
```cmd
migrate.bat
```
or via the Web UI under **inFlow SQL Sync** (`/settings/migration`).
