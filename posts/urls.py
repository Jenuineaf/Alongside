"""Posts & Feed URLconf."""

from django.urls import path

from posts import views

app_name = "posts"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("home/", views.feed, name="home"),  # personalised Home replaces this later
    path("feed/", views.feed, name="feed"),
    # `ideas/new/` MUST precede `ideas/<slug:slug>/`. Django matches in order, so
    # with the slug pattern first "new" is captured as a slug and the create page
    # is a permanent 404 — which is what it was until this line moved.
    path("ideas/new/", views.create, name="create"),
    # Literal suffixes on a slug route are safe in either order — `<slug:slug>`
    # cannot match two path segments — but they are grouped here so the set of
    # author-only actions reads as one thing.
    path("ideas/<slug:slug>/edit/", views.edit, name="edit"),
    path("ideas/<slug:slug>/delete/", views.delete, name="delete"),
    path("ideas/<slug:slug>/status/", views.set_status, name="set_status"),
    path("ideas/<slug:slug>/", views.detail, name="detail"),
]
