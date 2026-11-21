"""Role definitions and repeatable Django Group provisioning."""

from __future__ import annotations

from enum import Enum

from django.contrib.auth.models import Group, Permission
from django.db import models


class Role(str, Enum):
    SALESMAN = "Salesman"
    ADMIN = "Admin"
    PRODUCTION_SUPERVISOR = "Production Supervisor"
    AUDITOR = "Auditor"
    OWNER = "Owner"


MASTER_VIEW_PERMISSIONS = {
    "view_unit",
    "view_item",
    "view_product",
    "view_customer",
    "view_supplier",
    "view_pricelist",
    "view_pricelistitem",
    "view_bom",
    "view_bomline",
}

ROLE_PERMISSION_CODENAMES = {
    Role.SALESMAN: {
        "view_customer",
        "view_product",
        "view_pricelist",
        "view_pricelistitem",
    },
    Role.ADMIN: set(),  # Populated with all master-data permissions below.
    Role.PRODUCTION_SUPERVISOR: MASTER_VIEW_PERMISSIONS | {"change_bom", "change_bomline"},
    Role.AUDITOR: MASTER_VIEW_PERMISSIONS,
    Role.OWNER: MASTER_VIEW_PERMISSIONS,
}

INVENTORY_VIEW_PERMISSIONS = {"view_stockmovement", "view_openingbalance", "view_purchasereceipt"}


def role_names() -> tuple[str, ...]:
    return tuple(role.value for role in Role)


def provision_role_groups() -> dict[str, bool]:
    """Create all role groups and attach the currently available permissions.

    The function is idempotent and is intentionally callable after later phases
    introduce new models and permissions.
    """
    created: dict[str, bool] = {}
    all_master_permissions = Permission.objects.filter(content_type__app_label__in=("masters", "inventory"))

    for role in Role:
        group, was_created = Group.objects.get_or_create(name=role.value)
        created[role.value] = was_created
        if role is Role.ADMIN:
            group.permissions.add(*all_master_permissions)
            continue

        inventory_codes = INVENTORY_VIEW_PERMISSIONS if role is not Role.SALESMAN else set()
        permissions = Permission.objects.filter(
            models.Q(content_type__app_label="masters", codename__in=ROLE_PERMISSION_CODENAMES[role])
            | models.Q(content_type__app_label="inventory", codename__in=inventory_codes)
        )
        group.permissions.add(*permissions)

    return created
