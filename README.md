# QUILL - Quantified Unified Inventory And Logistics Ledger

QUILL is an order-to-audit system for a small food manufacturer. It links field orders, GST invoicing, BOM-based production, stock movements, costing, collections, and audit-ready reports.

## Technology

- Backend: Python and Django
- Database: PostgreSQL
- Frontend: Django templates, HTML, CSS, Bootstrap, and JavaScript
- Mobile experience: installable PWA with an offline fallback page
- Authentication: Django Authentication and role-based access control
- PDF invoices: ReportLab
- Excel/CSV reports: OpenPyXL and Python's CSV module
- Tests: pytest and Django's test framework
- Deployment: Docker-compatible platforms such as Render

Django keeps the order forms, role permissions, admin screens, and reports in one application. PostgreSQL provides transactions and row locks for the stock ledger, and server-rendered pages keep the mobile order flow lightweight.

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

Phases 0 through 8 establish the business workflows, the shared light workspace, and dedicated purchasing and inventory screens. Sign in at `/login/` to reach your role's home screen. Production, master data, and the audit log use Django Admin through permission-filtered links. Phases 9–12 cover their dedicated screens and integrated acceptance checks. [Implementation plan](IMPLEMENTATION_PLAN.md)

## Purchases and inventory

After upgrading, run `python manage.py migrate` and `python manage.py provision_roles`. An admin or production supervisor can open **Purchase receipts**, choose **New purchase receipt**, enter quantities in each item's base unit, save a draft, and review **Post to stock**. Posting records the actor and time. **Stock** shows quantities, valuation, low-stock status, and source documents for the movements you can access. Use **Stock as of** to see balances through a selected date. Admins can create and post opening balances from **Stock → Opening balances**, once per item.

## Sales workflow

Open `/login/` to sign in, then `/orders/` to submit a customer order with multiple products. Sales staff see their own orders, their order status, and customer sales totals. At submission, QUILL takes the latest active price for each product from the customer's price list, then falls back to an active general list or the product default. Price list start and end dates are inclusive. Existing orders retain their recorded prices. Admins can override quantities and prices on submitted orders. The review page shows required stock, available stock, and shortages. Approval and dispatch check stock again inside their transactions. Approved orders do not reserve stock.

An issued invoice snapshots the factory and customer identities, place of supply, prices, HSN, and tax amounts. The factory and place-of-supply state codes determine whether to apply CGST/SGST or IGST. The invoice PDF shows the tax breakdown per line. For local demos, the factory identity is fictional. For operational use, configure the `QUILL_FACTORY_NAME`, `QUILL_FACTORY_ADDRESS`, `QUILL_FACTORY_GSTIN`, `QUILL_FACTORY_STATE_NAME`, and `QUILL_FACTORY_STATE_CODE` environment variables before issuing invoices. Older invoices retain their original records and can have no factory snapshot.

## Current status

QUILL connects posted inventory and production movements to sales orders, GST invoices, dispatch, collections, and reports. Admins and auditors with Django Admin access can open **Audit log** to see the actor, time, action, and recorded changes.

## Reports and dashboard

After applying migrations, sign in and open **Reports** at `/reports/` (Admin or Auditor) or **Dashboard** at `/dashboard/` (Admin or Owner). Reports default to the current month to date. Set a date range and, where offered, a customer or item filter. CSV, Excel, and PDF downloads use the same filters and include all matching rows.

Stock summaries reconcile the opening balance, inward and outward movements, and closing value from the ledger. Receivables use payments received through the selected date and age from the invoice date. The GST outward summary groups recorded tax by place of supply, customer registration, HSN, and rate for reconciliation. Dispatched sales margin uses revenue before GST and the cost recorded at dispatch. Production cost uses weighted-average stock valuation plus overhead entered for the run. Admins can set an item's reorder point in **Admin → Items**. It defaults to zero.

To populate the reports on an empty demo ledger, run the following with an existing demo username:

```powershell
python manage.py seed_benchmark_reports --username YOUR_DEMO_USERNAME
```

The demo posts the 60 kg flour purchase at INR 45/kg, the 188-packet production run, the Retailer A invoice and dispatch, and the INR 4,000 collection. Distributor B's 120-packet order stays submitted so you can see the 32-packet shortage on approval. The reports show 120 kg flour, 19.5 L oil, 306 pouches, and 88 finished packets closing. Yield variance is −6%, oil variance is +5%, and Retailer A owes INR 3,875. Production cost is INR 31.1436 per good packet, including INR 1,800 overhead. The assignment supplies no cost for the 50 opening finished packets, so the demo values them at zero. This affects dispatch cost and margin.

## Demo logins and reset

Use an isolated Compose project for evaluation. With Docker Desktop running and a local `.env` copied from `.env.example`:

```powershell
$env:POSTGRES_PORT = "55433"
$env:QUILL_WEB_PORT = "8001"
docker compose -p quill-demo up --build -d --wait
docker compose -p quill-demo exec web python manage.py setup_demo
```

Choose a local demo password at the prompt. Sign in at `http://localhost:8001/login/`.

- `demo_sales_a` and `demo_sales_b` submit and view their own orders.
- `demo_admin` verifies orders, invoices, dispatches, and collects payments.
- `demo_production` enters purchases in **Purchase receipts** and production in Django Admin.
- `demo_auditor` views reports and the audit log.
- `demo_owner` views the dashboard.

For a hands-on run, add `--opening-only` to `setup_demo` on a fresh database. The command creates logins, master data, and opening stock. Post the flour receipt. Create a Murukku production run for 200 packets, enter 188 good packets and 12 waste, and set overhead to INR 1,800 (INR 1,200 labour and INR 600 gas/power). Save once to copy the BOM. Reopen the draft and enter 10.5 L of oil, 194 pouches (including 6 damaged), and 9 cartons. Enter 6 in the pouches' damaged quantity field. Posting deducts 194 pouches in total. Submit Retailer A's 150-packet order, approve it, dispatch it, and collect INR 4,000. Try to approve Distributor B's 120-packet order and confirm the 32-packet shortage. Use the auditor and owner logins to inspect the result.

To start over, `docker compose -p quill-demo down --volumes` deletes the **isolated demo database**. Run the startup and setup commands again. Use the named demo project for this reset.

## Corrections

Posted invoices and production runs stay in the history. An admin can cancel an unpaid invoice from its order page with a reason. For a dispatched invoice, confirm that all goods have been returned. QUILL issues a credit note, restores the stock at its recorded cost, and includes the credit in reports for the period it was issued. Refunds and partial returns require a separate workflow.

Admins can open a posted purchase receipt and choose **Reverse receipt** to preview the quantity and value to remove. The reversal requires a reason and enough stock and value. It keeps the original receipt and creates linked ledger entries. Enter a replacement receipt for corrected quantities or costs. Posted opening balances require reconciliation with the inventory administrator.

To reverse a production run, enter a reason in the Django Admin production run list and use **Reverse selected posted production runs**. QUILL checks that the finished goods quantity and value can be removed, then writes movements that undo the original entries.

## Install and deploy

On localhost or an HTTPS deployment, use **Install app** or **Add to Home Screen** in the browser. The service worker caches public assets and an offline page. Opening business records and submitting orders require a connection.

## Assignment coverage and limits

The two-page [design note](output/pdf/QUILL-Design-Note.pdf) covers the data model, posting logic, valuation, and benchmark checkpoints.

- Core workflow: role-based access, product and BOM masters, mobile order entry, price and stock review, invoice PDFs, production and stock movements, and monthly sales and stock exports.
- Extended workflow: purchase receipts, payments and ageing, production costing and variance alerts, GST summaries, owner dashboard, audit events, credit notes, and production reversals.
- Scope boundaries: orders require a connection, approved orders do not reserve stock, and cancellation supports unpaid invoices and full goods returns. Partial returns, refunds, and direct GST filing are outside this prototype.

The [Render Blueprint](render.yaml) defines the Docker web service and managed PostgreSQL database. Create a [Render Blueprint](https://render.com/docs/blueprints) from the repository, review the paid service plans, and enter a generated `DJANGO_SECRET_KEY` of at least 50 characters when prompted. Render runs migrations and provisions roles during pre-deploy. After the first deploy, create your administrator in the Render shell with `python manage.py createsuperuser` and confirm `/health/` returns HTTP 200. Demo account setup is for local development.
