from django.db import models

from model_utils.fields import AutoCreatedField


class Visit(models.Model):
    created = AutoCreatedField(db_index=True)
    image = models.ImageField()

    class Meta:
        indexes = [models.Index(fields=["-created"])]
