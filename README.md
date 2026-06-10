# Fuel Route Optimizer

Django API that calculates optimal fuel stops along a driving route between two USA locations.

## What It Does

- Takes `start` and `finish` locations (e.g., "New York, NY" → "Los Angeles, CA")
- Geocodes addresses using Google Geocoding API
- Calculates driving route via OSRM
- Finds truck stops along the route using geohash spatial indexing
- Optimizes fuel purchases with a greedy look-ahead algorithm
- Returns GeoJSON route + fuel stops with gallons to buy, cost, and milestone distances

## Tech Stack

- Django + GeoDjango + DRF
- PostgreSQL + PostGIS
- Google Geocoding API
- OSRM (Open Source Routing Machine)
- pygeohash for spatial indexing

## Quick Start

1. **Start PostgreSQL with PostGIS:**
```bash
cd fuelroute && docker-compose up -d db
```

2. **Set environment variables:**
```bash
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

3. **Install dependencies and run migrations:**
```bash
pip install -r requirements.txt
python3 manage.py migrate
```

4. **Load fuel stations (optional — provides real pricing data):**
```bash
python3 manage.py import_stations fuel-prices.csv
```

5. **Run the server:**
```bash
python3 manage.py runserver
```

## API Usage

```bash
curl -X POST http://localhost:8000/api/route-fuel/ \
  -H "Content-Type: application/json" \
  -d '{"start":"New York, NY", "finish":"Los Angeles, CA"}'
```

**Response:**
```json
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
        "address": "I-76, EXIT 29",
        "price": 3.499,
        "gallons": 45.0,
        "cost": 157.46,
        "milestone": 450.0
      }
    }
  ],
  "total_fuel_cost": 892.45,
  "total_distance_miles": 2784.5,
  "total_gallons": 278.45
}
```

## Vehicle Assumptions

- Tank capacity: 50 gallons
- MPG: 10
- Range: 500 miles
- Destination buffer: 50 miles

## Project Structure

```
routing/
  services/
    geocoding_service.py    # Google Geocoding
    osrm_service.py         # Route calculation
    optimize_fuel_stops.py  # Corridor scan + greedy optimizer
  views.py                  # POST /api/route-fuel/
  serializers.py            # GeoJSON response serialization
stations/
  models.py                 # TruckStop (PostGIS PointField + geohash)
  management/commands/
    import_stations.py      # CSV import with parallel geocoding
```

## Requirements

- Python 3.12+
- GDAL + GEOS libraries (for GeoDjango)
- Google Geocoding API key
