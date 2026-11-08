# SmartStock ERP — Upgraded Dashboard (Django)

A runnable internship demonstration application inspired by *general ERP inventory/procurement workflows* and the style of the dashboard screenshot. **Independent educational prototype; not a PrismERP product or integration.** All sample business data is synthetic.

## What works in this version

- **🤖 Google Gemini AI Copilot**: Live inventory assistant bubble on every page answering stock questions, calculating valuation, and alerting on shortages in natural language
- **📋 1-Click Executive AI Audit**: Automated management briefing on `/reports/` evaluating stock velocity, capital concentration, and risk
- Responsive purple-and-white admin dashboard with navigation sidebar, KPI cards and notification indicator
- **Real database metrics**: total products, in-stock / low-stock / out-of-stock counts, inventory value, total units, open requisitions
- **Chart.js charts**: 7-day inbound/outbound stock movements and product status doughnut
- Global product search, inventory filtering by status/warehouse, product create/edit and CSV export
- Warehouse and supplier setup pages
- Audited stock-in/stock-out transactions, with protection against negative stock
- Reorder rules per product (reorder threshold and target stock); a stock movement or changed rule can generate a **draft requisition**
- Duplicate open requisitions prevented by a database constraint
- Staff-only procurement workflow: **draft → approved → ordered → fulfilled** (or reject)
- Create purchase orders from approved requisitions; receive a full order and automatically update stock
- Movement history, downloadable CSV reports, user profile settings, Django admin
- Automated test cases for stock and purchase workflow (run them on your machine)
- **Production-ready deployment**: Configured for Render.com with Gunicorn, WhiteNoise asset compression, and PostgreSQL support

## Requirements

- Python 3.10–3.14; Python 3.12 recommended
- Internet during installation and to load Bootstrap / Bootstrap Icons / Chart.js CDNs
- VS Code (recommended), or a similar editor
- SQLite is bundled with Python, no extra database installation

## Installation — Windows PowerShell

Extract the ZIP and open the **smartstock-erp-upgraded** folder in VS Code.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py makemigrations inventory
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

PowerShell execution-policy error? Use Command Prompt instead: `.venv\Scripts\activate.bat`. Or skip activation and run `.venv\Scripts\python.exe` before pip and manage.py commands.

## Installation — macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py makemigrations inventory
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in using the **superuser** credentials you created. Django admin is at <http://127.0.0.1:8000/admin/>.

Run automated tests:

```bash
python manage.py test
```

### If you already have the previous starter installed

This is a new project directory, not a patch file. **Start with a fresh SQLite database** to avoid migration mismatches with any migration files you previously generated. If you've recorded important data in the old project, back it up first. Existing records are not imported automatically.

## Demo for internship defense

1. Sign in as the superuser and open **Dashboard**. The KPI cards and charts are populated from the synthetic demo data.
2. Open **Inventory** and view the stock status of **Wireless Headphones (HP-401)**. It has 12 units and a reorder point of 20.
3. Go to **Requisitions**, find the draft PR created by the stock trigger (suggested quantity 108).
4. Click **Approve**, then **Create PO**. The requisition moves from draft to approved to ordered.
5. Go to **Purchase Orders** and click **Receive Goods** for the PO. A stock-in movement is recorded, stock increases to 120, and the requisition becomes fulfilled.
6. Return to the dashboard and show the KPI and alert changes. Visit **Stock Movements** to show the audit record.
7. Use **Reports** to download inventory and movement CSV files.

Other demos: adjust reorder levels in **Manage Reorder Rules**, filter inventory, add a warehouse or supplier, and create a new product.

## Main project structure

```text
smartstock-erp-upgraded/
├── manage.py
├── requirements.txt
├── smartstock/       # Django settings and URLs
├── inventory/
│   ├── models.py     # Product, Warehouse, Requisition, PO, etc.
│   ├── services.py   # Transactional inventory and purchase business rules
│   ├── views.py      # Pages, approvals, export endpoints
│   ├── forms.py
│   ├── urls.py
│   ├── tests.py
│   └── management/commands/seed_demo.py
├── templates/        # Dashboard, tables, forms, login
└── static/css/       # Dashboard styling
```

## Limitations and roadmap

- Inventory is modeled as **one warehouse per product**, not true multi-warehouse balances. A production-grade ERP uses Product + Warehouse + InventoryBalance and transfer transactions.
- Reorder calculations currently use a **manual reorder point** and target stock. Lead-time-based reorder points, safety stock and outstanding-order netting are future improvements.
- Receipts are for **full PO quantities**; no partial deliveries, tax treatment, invoice settlement, returns, reservations or supplier performance scoring yet.
- CSV reports are provided; PDF exports are not yet implemented.
- Django `DEBUG=True` and a static development SECRET_KEY are for **local demonstration only**. Add secret management, secure configuration, PostgreSQL, and deployment security before real hosting.
- **SQLite** is suitable for a single-user local demo. Production concurrency control requires a database with reliable row locking (e.g., PostgreSQL).
- UI chart/CDN assets require an internet connection. The Python backend and database still work offline after installing dependencies.
- Currency is not enforced. Enter prices in a single consistent currency and explain the valuation assumption at defense.

## Testing status

Source files were syntax-checked in the build environment. Django could not be installed in that environment due to blocked network/DNS, so **Django tests and browser rendering need to be run locally** using the commands above. This is not a claim that tests passed.
