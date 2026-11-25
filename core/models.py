from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Posted records cannot be updated.")

    def delete(self):
        raise ValidationError("Posted records cannot be deleted.")


class AppendOnlyRecord(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None:
            raise ValidationError("Posted records cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Posted records cannot be deleted.")


class AuditEvent(AppendOnlyRecord):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    entity = models.CharField(max_length=24)
    object_id = models.PositiveBigIntegerField()
    reference = models.CharField(max_length=80)
    action = models.CharField(max_length=24)
    details = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("entity", "object_id", "created_at"))]


def record_event(actor, document, action, *, reference, **details):
    return AuditEvent.objects.create(
        actor=actor, entity=document._meta.model_name, object_id=document.pk,
        reference=str(reference), action=action, details=details,
    )
