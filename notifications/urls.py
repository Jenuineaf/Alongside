"""Notifications URLconf — stubs until Social phase."""

from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.list_notifications, name="list"),
]
