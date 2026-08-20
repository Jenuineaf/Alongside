"""Discovery URLconf — stubs until the Discovery seat wires search + Home."""

from django.urls import path

from discovery import views

app_name = "discovery"

urlpatterns = [
    path("", views.home, name="home"),
    path("explore/", views.explore, name="explore"),
    path("search/", views.search, name="search"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("onboarding/<int:step>/", views.onboarding, name="onboarding_step"),
]
