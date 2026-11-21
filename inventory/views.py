from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render

from inventory.models import StockMovement
from masters.models import Item


@login_required
@permission_required("inventory.view_stockmovement", raise_exception=True)
def stock_summary(request):
    items = Item.objects.annotate(stock_quantity=Sum("stock_movements__quantity"), stock_value=Sum("stock_movements__value"))
    return render(request, "inventory/stock_summary.html", {"items": items})


@login_required
@permission_required("inventory.view_stockmovement", raise_exception=True)
def item_ledger(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    movements = StockMovement.objects.filter(item=item).select_related("created_by", "opening_line__document", "receipt_line__document")
    return render(request, "inventory/item_ledger.html", {"item": item, "movements": movements})
