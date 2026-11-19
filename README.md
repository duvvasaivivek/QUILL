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

The complete phasewise plan is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). The immediate next stage is Phase 1: roles, permissions, and master data.

## Current status

Phases 0 and 1 are complete. The repository contains the Django project baseline, PostgreSQL configuration, Docker Compose setup, custom user model, RBAC role groups, validated master-data models, Django Admin registrations, benchmark master-data seeding, static/template configuration, a health endpoint, and automated tests.
