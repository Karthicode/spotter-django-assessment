import pygeohash
from django.contrib.gis.db import models


class TruckStop(models.Model):
    id = models.AutoField(primary_key=True)  # type: ignore[var-annotated]
    opis_id = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    median_price = models.DecimalField(max_digits=5, decimal_places=3)
    location = models.PointField(geography=True, spatial_index=True)
    geohash = models.CharField(max_length=12, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["geohash"]),
        ]

    def save(self, *args, **kwargs):
        if self.location and not self.geohash:
            lon, lat = self.location.coords
            self.geohash = pygeohash.encode(lat, lon, precision=5)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.opis_id}) - ${self.median_price}"
