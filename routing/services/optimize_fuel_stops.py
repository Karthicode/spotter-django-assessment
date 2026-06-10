import hashlib
import math

import pygeohash
from django.core.cache import cache

from stations.models import TruckStop

# Vehicle constants
TANK_CAPACITY_GALLONS = 50.0
MILES_PER_GALLON = 10.0
MAX_RANGE_MILES = TANK_CAPACITY_GALLONS * MILES_PER_GALLON
DESTINATION_BUFFER_MILES = 50.0
MIN_HOP_MILES = 400.0  # Prefer not to stop for tiny hops
CLOSE_STOP_PENALTY_DOLLARS = 0.50  # Max price penalty (linear) for close stops

# Performance constants
CORRIDOR_CACHE_TTL = 3600  # 1 hour
GEOHASH_PRECISION = 5  # ~5km x 5km cells
ROUTE_SAMPLE_INTERVAL_MILES = 5.0


def _route_geometry_hash(route_geometry):
    """Create a deterministic hash for route geometry caching."""
    coords = route_geometry.get("coordinates", [])
    # Use a subset of coordinates for hashing (every 10th point)
    # to keep the hash stable while reducing size
    sample = coords[::10] if len(coords) > 20 else coords
    return hashlib.md5(str(sample).encode()).hexdigest()


def _sample_route_points(coordinates, interval_miles=5.0):
    """Sample route points at regular intervals for geohash indexing."""
    if len(coordinates) < 2:
        return coordinates

    sampled = [coordinates[0]]
    cumulative = 0.0

    for i in range(1, len(coordinates)):
        lon1, lat1 = coordinates[i - 1]
        lon2, lat2 = coordinates[i]
        # Haversine distance in miles
        segment = _haversine_distance(lon1, lat1, lon2, lat2)
        cumulative += segment

        if cumulative >= interval_miles:
            sampled.append((lon2, lat2))
            cumulative = 0.0

    # Always include the last point
    if coordinates[-1] not in sampled:
        sampled.append(coordinates[-1])

    return sampled


def _haversine_distance(lon1, lat1, lon2, lat2):
    """Calculate distance between two points in miles using Haversine formula."""
    R = 3959.0  # Earth's radius in miles
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _get_route_geohashes(coordinates):
    """Get all unique geohash cells (and neighbors) that the route passes through."""
    sampled = _sample_route_points(coordinates, ROUTE_SAMPLE_INTERVAL_MILES)
    geohashes = set()

    for lon, lat in sampled:
        # Encode the point to geohash
        h = pygeohash.encode(lat, lon, precision=GEOHASH_PRECISION)
        geohashes.add(h)
        # Include neighbors to cover the corridor width
        for direction in ("top", "bottom", "left", "right"):
            try:
                neighbor = pygeohash.get_adjacent(h, direction)  # type: ignore[arg-type]
                geohashes.add(neighbor)
            except Exception:
                pass

    return geohashes


def _calculate_cumulative_distances(coordinates):
    """Calculate cumulative distances along the route in miles."""
    distances = [0.0]
    for i in range(1, len(coordinates)):
        lon1, lat1 = coordinates[i - 1]
        lon2, lat2 = coordinates[i]
        segment = _haversine_distance(lon1, lat1, lon2, lat2)
        distances.append(distances[-1] + segment)
    return distances


def _find_closest_route_point(
    station_lon, station_lat, coordinates, cumulative_distances
):
    """Find the closest route point to a station and its distance from start."""
    # Use a coarse search first to narrow down the range
    # Sample every 100 points for coarse search
    sample_step = max(1, len(coordinates) // 100)
    min_dist = float("inf")
    closest_idx = 0

    # Coarse search
    for i in range(0, len(coordinates), sample_step):
        lon, lat = coordinates[i]
        d = _haversine_distance(station_lon, station_lat, lon, lat)
        if d < min_dist:
            min_dist = d
            closest_idx = i

    # Fine search around the closest coarse point
    start = max(0, closest_idx - sample_step)
    end = min(len(coordinates), closest_idx + sample_step + 1)
    for i in range(start, end):
        lon, lat = coordinates[i]
        d = _haversine_distance(station_lon, station_lat, lon, lat)
        if d < min_dist:
            min_dist = d
            closest_idx = i

    return closest_idx, cumulative_distances[closest_idx]


def get_stations_along_route(route_geometry, buffer_miles=5.0):
    """
    Corridor scan: find all truck stops within a buffer of the route,
    project them onto the route line, and return them sorted by distance
    from the route origin.

    Uses geohash prefix matching (B-tree index) for fast spatial filtering,
    then PostGIS for precise distance computation.

    Args:
        route_geometry: GeoJSON dict with a 'coordinates' list of [lon, lat]
        buffer_miles: spatial buffer around the route (default 5.0)

    Returns:
        list of dicts: [{"id": int, "name": str, "price": Decimal,
                         "dist_from_start": float}, ...]
    """
    coordinates = route_geometry.get("coordinates", [])
    if not coordinates or len(coordinates) < 2:
        return []

    # Check cache first
    cache_key = f"corridor_{_route_geometry_hash(route_geometry)}_{buffer_miles}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Step 1: Find all geohash cells the route passes through
    route_geohashes = _get_route_geohashes(coordinates)

    # Step 2: Query stations by geohash prefix (B-tree index, very fast)
    # Build a Q query for OR-ing all geohash prefixes
    from django.db.models import Q

    q = Q()
    for h in route_geohashes:
        q |= Q(geohash__startswith=h)

    stations_qs = TruckStop.objects.filter(q)

    # Step 3: Compute route length and cumulative distances in Python
    # (avoids expensive PostGIS Length() on 34K-point LineString)
    cumulative_distances = _calculate_cumulative_distances(coordinates)

    # Step 4: Convert to list of dicts
    # Compute snapped points and distances in Python instead of PostGIS
    results = []
    for station in stations_qs:
        station_lon, station_lat = station.location.coords
        # Find closest route point and its distance
        closest_idx, dist_from_start = _find_closest_route_point(
            station_lon, station_lat, coordinates, cumulative_distances
        )
        # Snap to the closest route point
        snapped_lon, snapped_lat = coordinates[closest_idx]

        results.append(
            {
                "id": station.id,
                "opis_id": station.opis_id,
                "name": station.name,
                "address": station.address,
                "price": station.median_price,
                "dist_from_start": dist_from_start,
                "snapped_lon": snapped_lon,
                "snapped_lat": snapped_lat,
            }
        )

    # Sort by distance from origin
    results.sort(key=lambda s: s["dist_from_start"])

    # Cache the results
    cache.set(cache_key, results, CORRIDOR_CACHE_TTL)
    return results


def find_optimal_stops(stations, total_distance, tank_capacity, current_fuel, mpg):
    """
    Greedy look-ahead fuel stop optimizer.

    Algorithm:
    1. Start with current fuel.
    2. While not at destination:
       a. Find the farthest station reachable with current fuel.
       b. If destination is reachable, done.
       c. Find the cheapest station among all reachable stations.
       d. Stop at that cheapest station.
       e. Look ahead from that station within max_range.
       f. If a cheaper station exists ahead, buy only enough to reach it (Bridge).
       g. If no cheaper station ahead, fill to capacity (Fill).
    3. Return list of stops.

    Args:
        stations: sorted list of dicts from get_stations_along_route
        total_distance: total route distance in miles
        tank_capacity: fuel tank capacity in gallons
        current_fuel: current fuel level in gallons
        mpg: miles per gallon

    Returns:
        list of dicts: [{"station_id": int, "name": str, "price": Decimal,
                         "dist_from_start": float, "gallons_to_buy": float,
                         "expected_cost": float}, ...]
    """
    max_range = tank_capacity * mpg
    current_position = 0.0
    fuel_remaining = current_fuel * mpg  # convert to miles
    stops = []

    while current_position < total_distance:
        # Find all stations strictly ahead that are reachable with current fuel
        reachable = [
            s
            for s in stations
            if s["dist_from_start"] > current_position
            and s["dist_from_start"] <= current_position + fuel_remaining
        ]

        # If destination is reachable with current fuel, we're done
        if current_position + fuel_remaining >= total_distance:
            break

        if not reachable:
            # Can't reach destination or any station — impossible
            return []

        # Find the cheapest station among all reachable.
        # When we have plenty of fuel to go further, penalize close stops
        # so that we don't make unnecessary tiny hops just to save a few cents.
        def _station_score(s):
            price = float(s["price"])
            distance = s["dist_from_start"] - current_position
            if (
                distance < MIN_HOP_MILES
                and fuel_remaining > distance + DESTINATION_BUFFER_MILES
            ):
                # Linear penalty: max at distance 0, zero at MIN_HOP_MILES
                penalty = (
                    (MIN_HOP_MILES - distance)
                    / MIN_HOP_MILES
                    * CLOSE_STOP_PENALTY_DOLLARS
                )
                price += penalty
            return price

        cheapest = min(reachable, key=_station_score)
        cheapest_dist = cheapest["dist_from_start"]
        cheapest_price = float(cheapest["price"])

        # Fuel consumed to get to this station
        fuel_used = cheapest_dist - current_position
        fuel_after_arrival = fuel_remaining - fuel_used

        # Look ahead from this station within max_range
        next_reachable = [
            s
            for s in stations
            if s["dist_from_start"] > cheapest_dist
            and s["dist_from_start"] <= cheapest_dist + max_range
        ]

        # Also check if destination is reachable from this station
        destination_reachable = total_distance <= cheapest_dist + max_range

        # Find cheapest station ahead with a strictly lower price
        cheaper_ahead = None
        for s in next_reachable:
            if float(s["price"]) < cheapest_price:
                if cheaper_ahead is None or float(s["price"]) < float(
                    cheaper_ahead["price"]
                ):
                    cheaper_ahead = s

        if cheaper_ahead:
            # Case A (Bridge): buy only enough to reach the cheaper station
            distance_to_cheaper = cheaper_ahead["dist_from_start"] - cheapest_dist
            fuel_needed = distance_to_cheaper

            if fuel_after_arrival < fuel_needed:
                buy_miles = fuel_needed - fuel_after_arrival
            else:
                buy_miles = 0.0

            gallons_to_buy = buy_miles / mpg
            cost = gallons_to_buy * cheapest_price

            stops.append(
                {
                    "station_id": cheapest["id"],
                    "opis_id": cheapest["opis_id"],
                    "name": cheapest["name"],
                    "price": cheapest["price"],
                    "dist_from_start": cheapest_dist,
                    "gallons_to_buy": round(gallons_to_buy, 2),
                    "expected_cost": round(cost, 2),
                }
            )

            current_position = cheapest_dist
            fuel_remaining = fuel_after_arrival + buy_miles

        else:
            # Case B (Fill or Destination)
            if destination_reachable:
                # Destination is reachable; buy only enough to reach it with buffer
                distance_to_dest = total_distance - cheapest_dist
                fuel_needed = distance_to_dest + DESTINATION_BUFFER_MILES

                if fuel_after_arrival < fuel_needed:
                    buy_miles = fuel_needed - fuel_after_arrival
                else:
                    buy_miles = 0.0

                gallons_to_buy = buy_miles / mpg
                cost = gallons_to_buy * cheapest_price

                stops.append(
                    {
                        "station_id": cheapest["id"],
                        "opis_id": cheapest["opis_id"],
                        "name": cheapest["name"],
                        "price": cheapest["price"],
                        "dist_from_start": cheapest_dist,
                        "gallons_to_buy": round(gallons_to_buy, 2),
                        "expected_cost": round(cost, 2),
                    }
                )

                break
            else:
                # Fill to capacity
                buy_miles = max_range - fuel_after_arrival
                gallons_to_buy = buy_miles / mpg
                cost = gallons_to_buy * cheapest_price

                stops.append(
                    {
                        "station_id": cheapest["id"],
                        "opis_id": cheapest["opis_id"],
                        "name": cheapest["name"],
                        "price": cheapest["price"],
                        "dist_from_start": cheapest_dist,
                        "gallons_to_buy": round(gallons_to_buy, 2),
                        "expected_cost": round(cost, 2),
                    }
                )

                current_position = cheapest_dist
                fuel_remaining = max_range

    return stops
