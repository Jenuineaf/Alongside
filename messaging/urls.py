"""Messaging URLconf — stubs until Phase 5."""

from django.urls import path

from messaging import views

app_name = "messaging"

urlpatterns = [
    path("", views.list_conversations, name="list"),
    path("<int:pk>/", views.thread, name="thread"),
    path("start/<int:user_pk>/", views.start, name="start"),
]
