from django.urls import path

from .views import route_fuel

urlpatterns = [
    path("api/route-fuel/", route_fuel, name="route_fuel"),
]
