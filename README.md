# QUILL - Quantified Unified Inventory And Logistics Ledger

QUILL is an order-to-audit system for a small food manufacturer. It links field orders, GST invoicing, BOM-based production, stock movements, costing, collections, and audit-ready reports.

## Technology

- Backend: Python and Django
- Database: PostgreSQL
- Frontend: Django templates, HTML, CSS, Bootstrap, and JavaScript
- Mobile experience: responsive PWA, introduced after the core flow is complete
- Authentication: Django Authentication and role-based access control
- PDF invoices: ReportLab
- Excel/CSV reports: Pandas and OpenPyXL
- Tests: pytest and Django's test framework
- Deployment: Docker-compatible platforms such as Render

## Local setup

1. Copy `.env.example` to `.env` and set a secure `DJANGO_SECRET_KEY`.
2. Start the application and PostgreSQL with Docker:

   ```powershell
   docker compose up --build
   ```

3. Open `http://localhost:8000/`.

The health check is available at `http://localhost:8000/health/`.

## Initialise application data

After applying migrations, create the required role groups and load the mandatory benchmark master data:

```powershell
python manage.py provision_roles
python manage.py seed_benchmark_masters
python manage.py createsuperuser
```

Roles are represented by Django Groups: Salesman, Admin, Production Supervisor, Auditor, and Owner. The administrator assigns these groups to users through Django Admin.

### Run without Docker

You need a local PostgreSQL database matching the values in `.env`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

## Development checks

```powershell
python manage.py check
$env:USE_SQLITE_FOR_TESTS = "true"
python manage.py test
```

## Delivery plan

The complete phasewise plan is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Phase 6 is next.

## Sales workflow

Open `/login/` to sign in, then `/orders/` to submit a customer order with multiple products. Salesmen see their own orders and customer sales totals. Admin-role users can edit submitted quantities, approve and invoice, reject, dispatch, and record payments. Approval and dispatch both check stock. Approval snapshots customer, price, HSN, and tax details into a financial-year-numbered invoice. Tamil Nadu customers receive CGST/SGST; other states receive IGST. Invoice PDF downloads are available from order details. Payments cannot exceed outstanding balances.

## Current status

Phases 0 through 5 are implemented. QUILL connects posted inventory and production movements to sales orders, GST invoices, dispatch, collections, and reports.

## Reports and dashboard

After applying migrations, sign in and open **Reports** at `/reports/` (Admin or Auditor) or **Dashboard** at `/dashboard/` (Admin or Owner). Reports default to the current month to date. Set a date range and, where offered, a customer or item filter. CSV, Excel, and PDF downloads use the same filters and include all matching rows.

Stock summaries reconcile the opening balance, inward and outward movements, and closing value from the ledger. Receivables use payments received through the selected date and age from the invoice date. The GST outward summary groups recorded tax by place of supply, customer registration, HSN, and rate for reconciliation. Dispatched sales margin uses revenue before GST and the cost recorded at dispatch. Production cost uses weighted-average stock valuation plus overhead entered for the run. Admins can set an item's reorder point in **Admin → Items**. It defaults to zero.

To populate the reports on an empty demo ledger, run the following with an existing demo username:

```powershell
python manage.py seed_benchmark_reports --username YOUR_DEMO_USERNAME
```

The demo posts the 60 kg flour purchase at INR 45/kg, the 188-packet production run, the Retailer A invoice and dispatch, and the INR 4,000 collection. Distributor B's 120-packet order stays submitted so you can see the 32-packet shortage on approval. The reports show 120 kg flour, 19.5 L oil, 306 pouches, and 88 finished packets closing. Yield variance is −6%, oil variance is +5%, and Retailer A owes INR 3,875. Production cost is INR 31.1436 per good packet, including INR 1,800 overhead. The assignment supplies no cost for the 50 opening finished packets, so the demo values them at zero. This affects dispatch cost and margin.
