from django.db import models

from model_utils.fields import AutoCreatedField, AutoLastModifiedField
from uuid import uuid4


class Visit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    modified = AutoLastModifiedField()
    created = AutoCreatedField(db_index=True)

    image = models.ImageField()
    confidence = models.FloatField(default=0.0)

    class Meta:
        indexes = [models.Index(fields=["-created"])]

    def __repr__(self):
        return f"<Visit - {self.id}>"
