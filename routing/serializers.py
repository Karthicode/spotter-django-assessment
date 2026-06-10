from rest_framework import serializers


class GeoJSONGeometrySerializer(serializers.Serializer):
    type = serializers.CharField()
    coordinates = serializers.ListField()


class RoutePropertiesSerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()


class FuelStopPropertiesSerializer(serializers.Serializer):
    name = serializers.CharField()
    price = serializers.FloatField()
    gallons = serializers.FloatField(source="gallons_to_buy")
    cost = serializers.FloatField(source="expected_cost")
    milestone = serializers.FloatField()


class GeoJSONFeatureSerializer(serializers.Serializer):
    type = serializers.CharField(default="Feature")
    geometry = GeoJSONGeometrySerializer()
    properties = serializers.DictField()


class RouteFuelResponseSerializer(serializers.Serializer):
    route = GeoJSONFeatureSerializer()
    fuel_stops = GeoJSONFeatureSerializer(many=True)
    total_fuel_cost = serializers.FloatField()
    total_distance_miles = serializers.FloatField()
    total_gallons = serializers.FloatField()
