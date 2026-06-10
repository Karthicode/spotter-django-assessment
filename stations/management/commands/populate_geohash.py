from django.core.management.base import BaseCommand

from stations.models import TruckStop


class Command(BaseCommand):
    help = "Populate geohash field for all existing TruckStop records"

    def handle(self, *args, **options):
        updated = 0
        for station in TruckStop.objects.filter(geohash=""):
            station.save()  # triggers geohash computation in model.save()
            updated += 1
            if updated % 100 == 0:
                self.stdout.write(f"Updated {updated} stations...")

        self.stdout.write(
            self.style.SUCCESS(f"Populated geohash for {updated} stations")
        )
