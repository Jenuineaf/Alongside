"""Posts & Feed URLconf."""

from django.urls import path

from discovery import views as discovery_views
from posts import views

app_name = "posts"

urlpatterns = [
    path("", views.landing, name="landing"),
    # Home and the feed are Discovery's views at Posts' URLs. The names are what
    # matter: `components/_tab_bar.html` and `_app_bar.html` reverse
    # `posts:home` and `posts:feed` on every page, and those reverses predate
    # Phase 3 — so the personalised feed and the filtered feed land here rather
    # than at new paths that would orphan the navigation.
    path("home/", discovery_views.home, name="home"),
    path("feed/", discovery_views.explore, name="feed"),
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
