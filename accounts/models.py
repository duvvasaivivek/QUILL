from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with optional operational contact details.

    Authorisation is assigned through Django Groups, not a mutable free-text role.
    """

    phone_number = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ("username",)

    def __str__(self) -> str:
        return self.get_full_name() or self.username
