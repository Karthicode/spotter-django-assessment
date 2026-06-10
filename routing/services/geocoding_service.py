import time

import requests
from django.conf import settings
from django.core.cache import cache


class GeocodingService:
    """Service for geocoding locations using Google Geocoding API."""

    GOOGLE_BASE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    _last_request_time = 0

    @classmethod
    def geocode_location(cls, location_string):
        """
        Geocode a location string to coordinates using Google Geocoding API.

        Args:
            location_string: e.g., "New York, NY" or "123 Main St, New York, NY"

        Returns:
            tuple of (lat, lon) or (None, None) if not found
        """
        cache_key = f"geocode_{location_string.replace(' ', '_')}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

        api_key = getattr(settings, "GOOGLE_API_KEY", None)
        if api_key:
            result = cls._geocode_google(location_string, api_key)
            if result:
                cache.set(cache_key, result, 3600)
                return result

        return None, None

    @classmethod
    def _geocode_google(cls, location_string, api_key):
        """Geocode using Google Maps API."""
        current_time = time.time()
        time_since_last_request = current_time - cls._last_request_time
        if time_since_last_request < 0.005:
            time.sleep(0.005 - time_since_last_request)

        try:
            params = {
                "address": location_string,
                "key": api_key,
                "region": "us",
            }
            response = requests.get(cls.GOOGLE_BASE_URL, params=params, timeout=10)
            cls._last_request_time = time.time()
            data = response.json()

            if data["status"] == "OK" and data["results"]:
                location = data["results"][0]["geometry"]["location"]
                return (location["lat"], location["lng"])
            elif data["status"] == "OVER_QUERY_LIMIT":
                print(f"Google API quota exceeded for {location_string}")
            elif data["status"] == "REQUEST_DENIED":
                print("Google API request denied. Check API key.")
            return (None, None)

        except requests.RequestException as e:
            print(f"Google Geocoding request failed: {e}")
            return (None, None)
