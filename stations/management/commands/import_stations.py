import csv
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from routing.services.geocoding_service import GeocodingService
from stations.models import TruckStop


class Command(BaseCommand):
    help = (
        "Import fuel stations from CSV. "
        "Groups by OPIS ID, computes median price, "
        "geocodes each station by its full name + address + city + state, "
        "and stores the result as TruckStop records in PostGIS."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to the CSV file")
        parser.add_argument(
            "--workers",
            type=int,
            default=10,
            help="Number of parallel geocoding workers (default: 10)",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        workers = options["workers"]

        self.stdout.write(
            self.style.NOTICE(f"Reading fuel stations from {csv_file}...")
        )

        # Group rows by OPIS Truckstop ID
        groups = {}
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                opis_id = row["OPIS Truckstop ID"].strip()
                if not opis_id:
                    continue
                groups.setdefault(opis_id, []).append(row)

        self.stdout.write(
            self.style.NOTICE(f"Found {len(groups)} unique OPIS IDs after grouping")
        )

        # Prepare station data for parallel processing
        station_data_list = []
        for opis_id, rows in groups.items():
            prices = []
            for row in rows:
                try:
                    price = Decimal(row["Retail Price"].strip())
                    prices.append(float(price))
                except (ValueError, TypeError):
                    continue

            if not prices:
                continue

            median_price = Decimal(str(statistics.median(prices)))
            first_row = rows[0]
            name = first_row["Truckstop Name"].strip()
            address = first_row.get("Address", "").strip()
            city = first_row["City"].strip()
            state = first_row["State"].strip()
            location_string = f"{name}, {address}, {city}, {state}"

            station_data_list.append(
                {
                    "opis_id": opis_id,
                    "name": name,
                    "address": address,
                    "median_price": median_price,
                    "location_string": location_string,
                }
            )

        self.stdout.write(
            self.style.NOTICE(
                f"Processing {len(station_data_list)} stations "
                f"with {workers} workers..."
            )
        )

        # Parallel geocoding
        def geocode_station(data):
            lat, lon = GeocodingService.geocode_location(data["location_string"])
            data["lat"] = lat
            data["lon"] = lon
            return data

        geocoded_stations = []
        geocode_error_count = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_data = {
                executor.submit(geocode_station, data): data
                for data in station_data_list
            }

            processed = 0
            for future in as_completed(future_to_data):
                data = future_to_data[future]
                try:
                    result = future.result()
                    if result["lat"] and result["lon"]:
                        result["location"] = Point(
                            result["lon"], result["lat"], srid=4326
                        )
                    else:
                        result["location"] = None
                        geocode_error_count += 1
                    geocoded_stations.append(result)
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error geocoding station {data["opis_id"]}: {e}'
                        )
                    )
                    geocode_error_count += 1

                processed += 1
                if processed % 100 == 0:
                    self.stdout.write(
                        self.style.NOTICE(
                            f"Geocoded {processed}/{len(station_data_list)} stations..."
                        )
                    )

        # Bulk create all stations
        self.stdout.write(
            self.style.NOTICE(
                f"Creating {len(geocoded_stations)} stations in database..."
            )
        )

        truck_stops = [
            TruckStop(
                opis_id=data["opis_id"],
                name=data["name"],
                address=data["address"],
                median_price=data["median_price"],
                location=data["location"],
            )
            for data in geocoded_stations
        ]

        # Clear existing data and bulk create
        TruckStop.objects.all().delete()
        created = TruckStop.objects.bulk_create(truck_stops)

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {len(created)} stations created, "
                f"{geocode_error_count} geocode errors"
            )
        )
