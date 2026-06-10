import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from stations.models import TruckStop

from .serializers import RouteFuelResponseSerializer
from .services.geocoding_service import GeocodingService
from .services.optimize_fuel_stops import find_optimal_stops, get_stations_along_route
from .services.osrm_service import OSRMService

logger = logging.getLogger("routing")


@api_view(["POST"])
def route_fuel(request):
    """
    API endpoint to calculate optimal route and cost-effective fuel stops.

    Request body:
    {
        "start": "New York, NY",
        "finish": "Los Angeles, CA"
    }

    Response:
    {
        "route": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[lon, lat], ...]},
            "properties": {"distance_miles": 2784.5, "duration_hours": 40.2}
        },
        "fuel_stops": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": "Station Name",
                    "price": 3.39,
                    "gallons": 12.5,
                    "cost": 42.38,
                    "milestone": 50.5
                }
            }
        ],
        "total_fuel_cost": 892.45,
        "total_distance_miles": 2784.5,
        "total_gallons": 278.45
    }
    """
    data = request.data
    start_location = data.get("start")
    finish_location = data.get("finish")

    if not start_location or not finish_location:
        return Response(
            {"error": "Both start and finish locations are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if (
        not isinstance(start_location, str)
        or not isinstance(finish_location, str)
        or len(start_location) > 200
        or len(finish_location) > 200
    ):
        return Response(
            {"error": "Invalid location parameters"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Geocode start and finish locations
    start_lat, start_lon = GeocodingService.geocode_location(start_location)
    finish_lat, finish_lon = GeocodingService.geocode_location(finish_location)

    if not start_lat or not finish_lat:
        return Response(
            {"error": "Could not geocode one or both locations"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get route from OSRM
    route_data = OSRMService.get_route(start_lon, start_lat, finish_lon, finish_lat)

    if not route_data:
        return Response(
            {"error": "Could not calculate route"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Calculate total distance in miles
    total_distance_miles = route_data["distance"] / 1609.34
    duration_hours = route_data["duration"] / 3600.0

    # Corridor scan: find stations along the route
    corridor_stations = get_stations_along_route(route_data["geometry"])

    # Greedy fuel optimization
    fuel_stops = find_optimal_stops(
        stations=corridor_stations,
        total_distance=total_distance_miles,
        tank_capacity=50.0,
        current_fuel=50.0,
        mpg=10.0,
    )

    # Build GeoJSON features for fuel stops
    # Use snapped coordinates so markers sit exactly on the route line.
    station_lookup = {s["id"]: s for s in corridor_stations}
    fuel_stops_features = []
    for stop in fuel_stops:
        station_data = station_lookup.get(stop["station_id"], {})
        snapped_lon = station_data.get("snapped_lon")
        snapped_lat = station_data.get("snapped_lat")
        if snapped_lon is not None and snapped_lat is not None:
            coordinates = [snapped_lon, snapped_lat]
        else:
            try:
                station = TruckStop.objects.get(id=stop["station_id"])
                if station.location:
                    coordinates = [station.location.x, station.location.y]
                else:
                    coordinates = [0, 0]
            except TruckStop.DoesNotExist:
                coordinates = [0, 0]

        fuel_stops_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": coordinates,
                },
                "properties": {
                    "name": station_data.get("name", ""),
                    "address": station_data.get("address", ""),
                    "price": float(station_data.get("price", 0)),
                    "gallons": stop["gallons_to_buy"],
                    "cost": stop["expected_cost"],
                    "milestone": round(stop["dist_from_start"], 1),
                },
            }
        )

    total_fuel_cost = sum(stop["expected_cost"] for stop in fuel_stops)
    total_gallons = sum(stop["gallons_to_buy"] for stop in fuel_stops)

    response_data = {
        "route": {
            "type": "Feature",
            "geometry": route_data["geometry"],
            "properties": {
                "distance_miles": round(total_distance_miles, 1),
                "duration_hours": round(duration_hours, 1),
            },
        },
        "fuel_stops": fuel_stops_features,
        "total_fuel_cost": round(total_fuel_cost, 2),
        "total_distance_miles": round(total_distance_miles, 1),
        "total_gallons": round(total_gallons, 2),
    }

    serializer = RouteFuelResponseSerializer(data=response_data)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.data)
