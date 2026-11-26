from django.urls import reverse
from django.utils.functional import cached_property

from accounts.roles import Role


class Workspace:
    def __init__(self, user):
        self.user = user
        self.signed_in = user.is_authenticated and user.is_active

    @cached_property
    def roles(self):
        if not self.signed_in:
            return set()
        if self.user.is_superuser:
            return {Role.ADMIN.value}
        return set(self.user.groups.values_list("name", flat=True))

    @cached_property
    def home_type(self):
        for role, name in (
            (Role.ADMIN, "operations"),
            (Role.PRODUCTION_SUPERVISOR, "production"),
            (Role.SALESMAN, "sales"),
            (Role.AUDITOR, "audit"),
            (Role.OWNER, "owner"),
        ):
            if role.value in self.roles:
                return name
        return "general"

    @cached_property
    def report_access(self):
        return {
            "can_view_reports": bool(self.roles & {Role.ADMIN.value, Role.AUDITOR.value}),
            "can_view_dashboard": bool(self.roles & {Role.ADMIN.value, Role.OWNER.value}),
        }

    def allows(self, permission, *, staff=False):
        return self.signed_in and (self.user.is_staff or not staff) and self.user.has_perm(permission)

    @cached_property
    def links(self):
        return {
            key: (label, name)
            for key, label, name, allowed in (
                ("orders", "Sales orders", "sales_orders",
                 self.allows("sales.add_salesorder") or self.allows("sales.change_salesorder")),
                ("stock", "Stock", "stock_summary", self.allows("inventory.view_stockmovement")),
                ("purchases", "Purchase receipts", "purchase_receipts", self.allows("inventory.view_purchasereceipt")),
                ("production", "Production runs", "admin:production_productionrun_changelist",
                 self.allows("production.view_productionrun", staff=True)),
                ("reports", "Reports", "reports", self.report_access["can_view_reports"]),
                ("audit", "Audit log", "admin:core_auditevent_changelist",
                 self.allows("core.view_auditevent", staff=True)),
                ("dashboard", "Owner dashboard", "owner_dashboard",
                 self.report_access["can_view_dashboard"] and self.home_type != "owner"),
                ("settings", "Administration", "admin:index",
                 self.signed_in and self.user.is_staff and Role.ADMIN.value in self.roles),
            )
            if allowed
        }


def workspace_for(request):
    workspace = getattr(request, "_quill_workspace", None)
    if workspace is None or workspace.user is not request.user:
        workspace = request._quill_workspace = Workspace(request.user)
    return workspace


def report_access(request):
    return workspace_for(request).report_access


def navigation(request):
    workspace = workspace_for(request)
    if not workspace.signed_in:
        return {}
    current = request.resolver_match.view_name if request.resolver_match else None
    routes = [("Home", "home", {"owner_dashboard"} if workspace.home_type == "owner" else set())]
    for key, (label, name) in workspace.links.items():
        related = {
            "orders": {"sales_order"},
            "stock": {"item_ledger"},
            "purchases": {"purchase_receipt", "purchase_receipt_new", "purchase_receipt_edit", "purchase_receipt_reverse"},
        }.get(key, set())
        routes.append((label, name, related))
    return {
        "workspace_links": [
            {"label": label, "url": reverse(name), "active": current == name or current in related}
            for label, name, related in routes
        ],
        "workspace_role": ", ".join(role.value for role in Role if role.value in workspace.roles),
    }
