from django.contrib.auth.models import Group
from django.test import TestCase

from accounts.models import User
from accounts.roles import Role, provision_role_groups


class RoleProvisioningTests(TestCase):
    def test_provisioning_creates_every_required_role(self) -> None:
        provision_role_groups()

        self.assertEqual(
            set(Group.objects.values_list("name", flat=True)),
            {role.value for role in Role},
        )

    def test_user_role_is_represented_by_group_membership(self) -> None:
        provision_role_groups()
        user = User.objects.create_user(username="salesman-a", password="test-password")
        user.groups.add(Group.objects.get(name=Role.SALESMAN.value))

        self.assertTrue(user.groups.filter(name=Role.SALESMAN.value).exists())
