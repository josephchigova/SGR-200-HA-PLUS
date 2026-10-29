from django.conf import settings
from django.db import models

from apps.geography.models import District, Province


class Cluster(models.Model):
    name = models.CharField(max_length=180, unique=True)
    lead_farmer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_clusters",
    )
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name="clusters")
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="clusters")
    contact_person = models.CharField(max_length=180, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
