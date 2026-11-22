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

The complete phasewise plan is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Phase 4 adds sales orders, GST invoices, dispatch, and payments; Phase 5 adds reports.

## Sales workflow

Open `/login/` to sign in, then `/orders/` to submit a customer order with multiple products. Salesmen see their own orders and customer sales totals. Admin-role users can edit submitted quantities, approve and invoice, reject, dispatch, and record payments. Approval and dispatch both check stock. Approval snapshots customer, price, HSN, and tax details into a financial-year-numbered invoice. Tamil Nadu customers receive CGST/SGST; other states receive IGST. Invoice PDF downloads are available from order details. Payments cannot exceed outstanding balances.

## Current status

Phases 0 through 3 are complete. The repository contains the Django baseline, PostgreSQL and Docker Compose configuration, role groups, validated master data, benchmark master-data seeding, an inventory ledger, and BOM-based production runs. Draft opening balances, purchase receipts, and production runs can be created in Django Admin and posted with their posting actions. Production runs snapshot BOM quantities in base units, post consumption and output movements atomically, and record yield and consumption variances and costs. The stock summary is at `/stock/`, with item ledgers linked from it.

After migrating, run `python manage.py provision_roles` again to grant inventory permissions to the existing groups. The benchmark opening balance of 100 kg flour at INR 20/kg followed by a 60 kg purchase at INR 30/kg results in 160 kg, INR 3,800 stock value, and INR 23.75/kg weighted-average cost.
