"""Small, reusable role checks for role-specific views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.contrib.auth.decorators import user_passes_test

from .roles import Role


def role_required(*roles: Role | str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Require an authenticated user to belong to at least one supplied role."""
    allowed_names = {role.value if isinstance(role, Role) else role for role in roles}

    def has_role(user: Any) -> bool:
        return user.is_authenticated and (
            user.is_superuser or user.groups.filter(name__in=allowed_names).exists()
        )

    return user_passes_test(has_role)
