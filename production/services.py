from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import MovementType, StockMovement, stock_balance
from masters.models import ItemCategory
from production.models import ProductionConsumption, ProductionRun, RunStatus

QTY = Decimal("0.001")
MONEY = Decimal("0.0001")


@transaction.atomic
def create_production_run(*, reference, bom, planned_output, user, allocated_overhead=Decimal("0")):
    """Create a run with a base-unit snapshot of its current BOM."""
    bom = type(bom).objects.select_related("product").get(pk=bom.pk)
    if not bom.is_active:
        raise ValidationError("Only an active BOM can be used for a production run.")
    planned_output = Decimal(planned_output)
    if planned_output <= 0:
        raise ValidationError("Planned output must be positive.")
    run = ProductionRun.objects.create(
        reference=reference, bom=bom, planned_output=planned_output,
        allocated_overhead=allocated_overhead,
    )
    ratio = planned_output / bom.expected_output_quantity
    for line in bom.lines.select_related("item__base_unit", "unit"):
        expected = (line.quantity * line.unit.conversion_to_base * ratio / line.item.base_unit.conversion_to_base).quantize(QTY, rounding=ROUND_HALF_UP)
        ProductionConsumption.objects.create(
            run=run, item=line.item, expected_quantity=expected,
            actual_quantity=expected,
        )
    return run


@transaction.atomic
def post_production_run(run, user):
    run = ProductionRun.objects.select_for_update().select_related("bom__product__item").get(pk=run.pk)
    if run.status != RunStatus.DRAFT:
        raise ValidationError("Production run has already been posted.")
    if run.good_output <= 0:
        raise ValidationError("Good output must be positive before posting.")
    lines = list(run.consumptions.select_related("item__base_unit").order_by("item_id"))
    if not lines:
        raise ValidationError("The production run has no snapshotted BOM lines.")
    # Lock stock rows in deterministic order so purchases and other runs cannot race balances.
    list(StockMovement.objects.select_for_update().filter(item_id__in=[x.item_id for x in lines] + [run.bom.product.item_id]).order_by("item_id", "pk"))
    material_cost = Decimal("0")
    alerts = []
    for line in lines:
        line.full_clean()
        qty, value = stock_balance(line.item)
        if qty < line.actual_quantity:
            raise ValidationError(f"Insufficient stock for {line.item.sku}: {qty} available, {line.actual_quantity} required.")
        cost = value / qty if qty else Decimal("0")
        line.unit_cost = cost.quantize(MONEY, rounding=ROUND_HALF_UP)
        line.variance_percent = ((line.actual_quantity - line.expected_quantity) / line.expected_quantity * 100).quantize(Decimal("0.001")) if line.expected_quantity else None
        material_cost += line.actual_quantity * cost
        if line.variance_percent is not None and abs(line.variance_percent) > run.variance_tolerance_percent:
            alerts.append(True)
        line.save(update_fields=("unit_cost", "variance_percent"))
        StockMovement.objects.create(
            item=line.item, item_category=line.item.category, quantity=-line.actual_quantity,
            unit=line.item.base_unit, movement_type=MovementType.PRODUCTION_ISSUE,
            source_reference=run.reference, unit_cost=line.unit_cost,
            value=-(line.actual_quantity * cost).quantize(MONEY, rounding=ROUND_HALF_UP), created_by=user,
        )

    expected_yield = run.planned_output
    yield_variance = ((run.good_output - expected_yield) / expected_yield * 100).quantize(Decimal("0.001"))
    if abs(yield_variance) > run.variance_tolerance_percent:
        alerts.append(True)
    total_cost = (material_cost + run.allocated_overhead).quantize(MONEY, rounding=ROUND_HALF_UP)
    unit_cost = (total_cost / run.good_output).quantize(MONEY, rounding=ROUND_HALF_UP)
    output_item = run.bom.product.item
    StockMovement.objects.create(
        item=output_item, item_category=ItemCategory.FINISHED_GOOD, quantity=run.good_output,
        unit=output_item.base_unit, movement_type=MovementType.PRODUCTION_OUTPUT,
        source_reference=run.reference, unit_cost=unit_cost,
        value=(unit_cost * run.good_output).quantize(MONEY, rounding=ROUND_HALF_UP), created_by=user,
    )
    run.status = RunStatus.POSTED
    run.posted_at = timezone.now()
    run.posted_by = user
    run.material_cost = material_cost.quantize(MONEY, rounding=ROUND_HALF_UP)
    run.total_cost = total_cost
    run.cost_per_good_unit = unit_cost
    run.yield_variance_percent = yield_variance
    run.has_variance_alert = bool(alerts)
    run.save(update_fields=("status", "posted_at", "posted_by", "material_cost", "total_cost", "cost_per_good_unit", "yield_variance_percent", "has_variance_alert"))
    return run
