import time

import requests
from django.core.cache import cache


class OSRMService:
    """Service for fetching routes from OSRM"""

    BASE_URL = "http://router.project-osrm.org/route/v1/driving"
    _last_request_time = 0

    @classmethod
    def get_route(cls, start_lon, start_lat, end_lon, end_lat):
        """Fetch route from OSRM"""
        cache_key = f"osrm_route_{start_lon}_{start_lat}_{end_lon}_{end_lat}"
        cached_route = cache.get(cache_key)

        if cached_route:
            return cached_route

        # Rate limiting: wait at least 1 second between requests
        current_time = time.time()
        time_since_last_request = current_time - cls._last_request_time
        if time_since_last_request < 1.0:
            time.sleep(1.0 - time_since_last_request)

        url = f"{cls.BASE_URL}/{start_lon},{start_lat};{end_lon},{end_lat}"
        params = {
            "geometries": "geojson",
            "overview": "full",
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            cls._last_request_time = time.time()

            if response.status_code == 429:
                print("Rate limited by OSRM")
                return None

            response.raise_for_status()
            data = response.json()

            if data["code"] == "Ok" and data["routes"]:
                route = data["routes"][0]
                result = {
                    "geometry": route["geometry"],
                    "distance": route["distance"],  # in meters
                    "duration": route["duration"],  # in seconds
                    "legs": route["legs"],
                }

                # Cache for 1 hour
                # Using local cache, ideally should be Redis/Memcached for scaling
                cache.set(cache_key, result, 3600)
                return result

            return None

        except requests.RequestException as e:
            print(f"OSRM request failed: {e}")
            return None
