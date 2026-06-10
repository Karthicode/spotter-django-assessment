from django.contrib.gis import admin

from .models import TruckStop


@admin.register(TruckStop)
class TruckStopAdmin(admin.ModelAdmin):
    list_display = ["name", "median_price", "opis_id"]
    search_fields = ["name", "opis_id"]
