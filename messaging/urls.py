"""Messaging URLs, mounted at `/messages/`."""

from django.urls import path

from messaging import views

app_name = "messaging"

urlpatterns = [
    path("", views.list_conversations, name="list"),
    path("<int:pk>/", views.thread, name="thread"),
    path("<int:pk>/send/", views.send, name="send"),
    # Keyed on the user, not the conversation: the caller is a Message button on
    # a card or a profile and does not know whether a thread exists yet.
    path("start/<int:user_pk>/", views.start, name="start"),
]
