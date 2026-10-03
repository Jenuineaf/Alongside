"""Discovery URLconf — Home, explore, search and onboarding.

Mounted at `/search/`, which is historical: the app owns more than search now,
but `discovery:search` is reversed from `components/_app_bar.html` on every
page and the public URL is the one thing here somebody might have bookmarked.

`posts:home` and `posts:feed` are the canonical paths for Home and the feed —
`components/_tab_bar.html` reverses those, and the views behind them live here.
"""

from django.urls import path

from discovery import views

app_name = "discovery"

urlpatterns = [
    path("", views.search, name="search"),
    path("home/", views.home, name="home"),
    path("explore/", views.explore, name="explore"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("onboarding/<int:step>/", views.onboarding, name="onboarding_step"),
]
