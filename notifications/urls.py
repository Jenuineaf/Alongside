"""Notifications URLconf — the Alerts screen and its one control."""

from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.list_notifications, name="list"),
    path("read/", views.mark_all_read, name="mark_all_read"),
]
