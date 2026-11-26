# QUILL: Phasewise Implementation Plan

## 1. Solution approach

Build QUILL as a ledger-first Django monolith: one deployable application, one PostgreSQL database, and role-specific responsive screens. This is the best trade-off for a solo internship submission: reliable, explainable, quick to deploy, and easy to scale later.

The non-negotiable principle is:

```text
Business event -> immutable stock/accounting ledger entries -> current balances and reports
```

Never update stock by directly editing a "quantity in stock" field. Purchases, production, dispatches, returns, and adjustments must each create traceable ledger movements.

## 2. Phase 0 - Scope and foundation

**Estimated duration:** Day 1

Set up the repository, virtual environment, Django project, PostgreSQL, Bootstrap base template, environment variables, GitHub repository, and CI.

Create these Django applications:

```text
accounts, masters, inventory, production, sales, reports
```

Decide and document:

- Weighted-average valuation for material cost.
- `DecimalField` for money and quantities.
- Base units and conversions.
- A 3% default production-variance threshold.
- Financial-year invoice numbering.
- Posted invoices and production runs are reversed or adjusted, never deleted.

**Done when:** The project starts locally with one command and migrations run successfully.

## 3. Phase 1 - Identity and master data

**Estimated duration:** Days 2-3

Implement authentication and role-based access control.

Roles:

- Salesman
- Admin
- Production supervisor
- Auditor (read-only)
- Owner (optional summary-only role)

Create master data for:

- Units and conversions
- Raw materials, packaging materials, and finished goods
- Product pack sizes
- Customers and suppliers
- GSTIN, state, and place-of-supply details
- Price lists
- BOM headers and BOM lines

**Done when:** An admin can create Murukku 200 g, its 200-packet BOM, Retailer A, Distributor B, and the supplied opening balances.

## 4. Phase 2 - Inventory ledger and purchase receipt

**Estimated duration:** Days 4-6

This is the core technical phase.

Create `StockMovement` as the source of truth, with:

- Item and stock category
- Signed quantity
- Base unit
- Movement type: opening, purchase, production issue, production output, dispatch, return, adjustment
- Source document reference
- Unit cost and extended value where relevant
- Created time and responsible user

Implement:

- Opening-balance posting
- Purchase receipt
- Current-stock summary derived from the ledger
- Item-wise stock ledger with document links
- Weighted-average material valuation

**Done when:** Buying 60 kg flour correctly changes the balance from 100 kg to 160 kg and retains its source reference.

## 5. Phase 3 - BOM production, variance, and costing

**Estimated duration:** Days 7-10

This is the highest-value phase in the evaluation.

A production run should:

1. Snapshot the selected BOM.
2. Calculate expected material consumption and expected output.
3. Let the supervisor enter actual issues, good output, wastage, damaged packaging, and cartons used.
4. Post raw-material and packaging reductions plus finished-goods additions in one database transaction.
5. Calculate consumption and yield variances.
6. Flag variances above tolerance.
7. Calculate material cost, allocated overhead, cost per good packet, and margin.

For the benchmark, it must produce:

- 188 good Murukku packets
- -6% yield variance
- +5% oil-consumption variance
- Updated flour, oil, pouch, carton, and finished-goods balances

**Done when:** Automated tests pass the complete production benchmark.

## 6. Phase 4 - Sales, GST invoice, dispatch, and payments

**Estimated duration:** Days 11-14

Build the salesman-facing responsive order flow first:

- Select customer
- Add products and quantities
- Submit order
- View own order status and customer-wise sales

Then build the admin workflow:

- Approve, reject, or edit an order
- Check finished-goods availability before approval
- Generate GST invoice
- Use CGST/SGST for Tamil Nadu and IGST for interstate supply
- Generate a ReportLab PDF invoice
- Record dispatch and reduce finished-goods stock
- Record payments against invoices
- Calculate customer outstanding balance

**Done when:** Retailer A gets the INR 7,875 invoice, dispatch reduces stock from 238 to 88, a payment of INR 4,000 leaves INR 3,875 outstanding, and Distributor B's 120-packet order flags a shortage of 32.

## 7. Phase 5 - Reports, exports, and dashboard

**Estimated duration:** Days 15-17

Create filterable reports with date ranges and CSV/Excel export:

- Sales register by customer and product
- GST outward-supply summary
- Purchase register
- Stock summary
- Full stock ledger
- Production planned-versus-actual report
- Variance alerts
- Payments, outstanding, and ageing
- Cost per packet and margin

Keep the owner dashboard small: today's orders, critical stock, production variance alerts, receivables, and recent activity.

**Done when:** All mandatory monthly reports can be generated from the benchmark seed data.

## 8. Phase 6 - PWA, audit trail, tests, and deployment

**Estimated duration:** Days 18-21

Add these after the core benchmark works:

- PWA manifest and installable mobile experience
- Service worker caching
- Offline order outbox and sync, if time permits
- Audit log for invoice and production-run edits and cancellations
- Permission tests
- Stock, tax, unit-conversion, and variance tests
- Seed-data management command
- Docker Compose for local use
- Render deployment with managed PostgreSQL
- Demo accounts and reset instructions

**Done when:** An evaluator can clone, run, seed, log in under each role, and repeat the benchmark without manual database work.

## 9. Interface delivery scope

Phases 0-6 establish the business services, ledger, reports, and basic web pages. Phase 7 adds the shared light workspace and role home screens. Purchases, production, master data, and audit access still rely on Django Admin. Phases 8-12 complete the daily product interface.

Keep Django templates and the existing application structure. Reuse the posting, invoicing, valuation, permission, and audit services from the earlier phases. Before connecting a new screen, check that its service applies the required validation and transaction boundaries. Visual previews must reconcile with server calculations.

An evaluator should ultimately be able to sign in under each role and complete all daily work through the product screens. Terminal commands remain part of installation and local demo preparation. Django Admin remains available for system administration.

### Phase 7 - Application layout, navigation, and role home screens

**Status:** Implemented.

**Estimated duration:** 2-3 working days

Build the shared interface before converting individual workflows.

- Define consistent typography, colours, spacing, buttons, status indicators, form fields, tables, and feedback messages in the existing static assets and templates.
- Create a desktop application layout with clear navigation and a mobile layout with accessible navigation and touch targets.
- Make sign-in, sign-out, session expiry, permission errors, missing pages, and validation errors understandable.
- Route users to a useful home screen after login and from the installed PWA.
- Give sales staff their orders and a create-order action; factory admins their order queue, receipts, and collection tasks; supervisors their draft runs and material availability; auditors their report catalogue and audit history; owners their summary dashboard.
- Show navigation and actions according to role, with matching server-side permission checks for every destination.
- Add breadcrumbs, descriptive page titles, empty states, keyboard focus, and persistent success or error feedback.

**Done when:** Every demo account reaches its own useful starting screen, can navigate to its permitted tasks, and can sign out on both mobile and desktop. A restricted page or action also rejects direct URL and POST access.

### Phase 8 - Purchases, opening balances, and inventory workspace

**Status:** Implemented

Build receipt and inventory screens using the Phase 2 services.

- Add searchable, paginated receipt lists with supplier, date, reference, and status filters.
- Add draft receipt creation and editing with material selection, quantities, units, unit costs, line values, and a total.
- Provide a receipt detail page with posting preview, validation feedback, posted-by details, timestamps, and a clear post action.
- Give admins an opening-balance workflow that respects the existing one-opening-per-item rule.
- Add inventory filtering by item category, item, and date, with quantity, base unit, value, and low-stock status.
- Link item ledger movements back to their purchase, production, invoice, or reversal document where the user has access.
- Make posted documents read-only and show how corrections can be recorded through the supported workflow.
- Preserve entered form values on validation failure. Prevent accidental duplicate posting with server-side transaction and state checks.

**Done when:** A supervisor records and posts 60 kg flour at INR 45/kg through the product interface. Its stock changes from 100 kg to 160 kg, and the ledger opens the source receipt. Retrying the post action adds no duplicate movement.

### Phase 9 - Production workspace, variance review, and costing

**Estimated duration:** 3-4 working days

Build the production workflow around the saved BOM snapshot.

- Add searchable, paginated production lists with product, date, draft, posted, reversed, and variance filters.
- Add a new-run screen with product, active BOM version, planned output, and expected material consumption in explicit base units.
- Save the BOM snapshot with the draft, then provide a single draft workspace for actual material consumption, good output, waste, damaged packaging, carton usage, and run overhead.
- Explain packaging damage next to its field and include it once in actual consumption.
- Show planned versus actual quantities, stock sufficiency, consumption variance, yield variance, tolerance, and costing preview.
- Show recorded material cost, allocated overhead, cost per good unit, ledger effects, and audit history on the posted run.
- Offer authorised reversals with a reason and a preview of their stock effect. Preserve the source run and its original movements.
- Recheck state, stock, and values during posting and reversal. Surface a useful error if a concurrent transaction changes availability.

**Done when:** The supervisor completes the Murukku run entirely through the production workspace. It records 188 good packets, 194 pouches including 6 damaged, 9 cartons, -6% yield variance, +5% oil variance, and INR 31.1436 cost per good packet. Finished stock becomes 238 packets before sales dispatch.

### Phase 10 - Master data and team administration screens

**Estimated duration:** 3-4 working days

Provide the setup and maintenance screens that support normal operation.

- Add lists, search, create, edit, and detail screens for customers, suppliers, materials, finished products, units, price lists, and BOM versions.
- Group master data under a clear setup area with links from relevant product workflows.
- Use dynamic line forms for price lists and BOMs, with field-level errors and explicit units, dates, prices, and tax rates.
- Support active and inactive master records, protect referenced records, and explain why a historical record cannot be removed.
- Preserve historical document snapshots when master data changes. Provide a deliberate new-version workflow for changed BOMs.
- Let authorised admins manage team accounts, activate or deactivate users, and assign supported roles. Prevent privilege escalation through crafted form submissions.
- Define role permissions for each master screen and action. Suppliers, customer information, and costing must remain scoped to the roles that need them.
- Preserve the factory identity configuration and provide a visible summary of the issuer used for new invoices, with the configuration method documented.

**Done when:** An authorised admin can create a new product, BOM, customer, supplier, and effective price list through the product screens, then use them in a receipt, production run, and sales order. A master edit does not change an existing posted invoice or run.

### Phase 11 - Complete sales, billing, collections, and audit experience

**Estimated duration:** 3-4 working days

Refine the existing sales and reporting pages into a connected user workflow.

- Give mobile sales staff customer and product search, add/remove line actions, a price and quantity summary, validation feedback, order submission, and their own order history.
- Present order status consistently, including submitted, rejected, invoiced, dispatched, and cancelled states.
- Give admins a filterable incoming-order queue and a detail workspace for price overrides, quantity edits, stock review, approval, and rejection.
- Make invoice, dispatch, payment, outstanding balance, and credit-note history accessible from the same order or customer workspace.
- Confirm consequential actions with their actual quantities, values, and effects. Keep authorisation and repeat-submission protection on the server.
- Provide invoice and credit-note downloads and a usable share action where the browser supports it, with a download fallback.
- Improve report selection, filter controls, empty states, pagination, and export feedback while preserving the same filtered results in all formats.
- Add a read-only audit screen with date, actor, reference, entity, and action filters and links to permitted documents.
- Connect dashboard summaries to relevant detail pages where the role permits access.

**Done when:** A salesperson submits Retailer A's order in under one minute on a mobile viewport. The admin verifies stock and price, invoices INR 7,875, dispatches 150 packets, and collects INR 4,000 through the product interface. The auditor can trace the transaction and export the report, and Distributor B's shortage is visible before approval.

### Phase 12 - Integrated acceptance, accessibility, and performance verification

**Estimated duration:** 2-3 working days

Verify the complete interface using a fresh PostgreSQL demo database.

- Walk through setup, opening balances, purchase receipt, production, order, approval, invoice, dispatch, collection, reports, and audit history using the actual product screens and separate role accounts.
- Verify both the exact Murukku benchmark and representative local/interstate tax, validation, empty-data, long-document, and reversal cases.
- Check phone, tablet, and desktop layouts, keyboard-only operation, visible focus, labels, contrast, inline errors, table overflow, and touch targets.
- Check login redirects, expired sessions, CSRF rejection, role restrictions, duplicate submissions, and changes to stock between preview and posting.
- Check database query counts on list, detail, and stock-preview screens. Use pagination, batched aggregates, and related-record prefetching to address measured bottlenecks.
- Confirm query counts do not grow per displayed row for common list and detail pages. Profile representative data volumes and record hardware, dataset size, timings, and export memory behaviour with the result.
- Check rendering and totals in invoice PDFs and filtered CSV, Excel, and PDF reports.
- Verify service worker behaviour after a frontend update and useful offline feedback. Check that authenticated records are not cached by the service worker.
- Update setup instructions, known limits, the design note, and demo recording to match the final interface.

**Done when:** All mandatory benchmark steps work through the product interface, the reported figures reconcile, role and transaction checks pass, and there are no known blocking UI defects. Record the tested browsers, viewports, data volumes, and any remaining limitations before declaring the interface ready.

### Interface phase order and optional work

Implement Phases 7-12 in order. Each workflow phase must include its own form validation, permission checks, and proportionate regression verification before the next phase starts. Phase 12 verifies the connected product.

The additional interface work is estimated at 15-21 working days. Re-estimate after the shared layout and first transaction workspace are complete.

Offline order capture and sync remain optional work after the connected interface is verified. If undertaken, plan local draft ownership, idempotent submission, retry feedback, stale-price handling, session expiry, and logout cleanup before implementation.

## 10. Scalable architecture choices

Keep the first version simple, but design it so growth does not require a rewrite:

- Start with Django templates; add APIs only where PWA sync or external integrations need them.
- Use PostgreSQL constraints, transactions, and indexes on dates, document IDs, item IDs, and customer IDs.
- Snapshot BOM, price, tax, and valuation details on posted documents so historical reports never change after master-data edits.
- Use soft cancellation and reversal records instead of deletes.
- Store generated invoices and exports in object storage when deployed.
- Add Celery and Redis later only for slow jobs such as bulk report generation, emails, invoice rendering, or sync retries.
- Keep Tally export and e-invoice integration behind service interfaces so they remain optional.

## 11. Critical data model

The core entities should be:

```text
User / Role
Customer / Supplier
Item / Unit / UnitConversion
Product / PriceList
BOM / BOMLine
PurchaseReceipt / PurchaseReceiptLine
ProductionRun / ProductionConsumption / ProductionOutput
SalesOrder / SalesOrderLine
Invoice / InvoiceLine / Payment / CreditNote
StockMovement
AuditLog
```

Every posted purchase, production run, dispatch, return, or stock adjustment must link to one or more `StockMovement` records.

## 12. Priority rule

Do not build stretch features until this chain is flawless:

```text
Purchase -> production run -> ledger balances -> mobile order -> approval -> GST invoice -> dispatch -> payment -> reports
```

Phases 0-6 describe the original business-function milestone. Phases 7-12 complete the product interface and acceptance checks. Finish the connected benchmark before adding offline sync, GPS, expiry tracking, or Tally integration.
