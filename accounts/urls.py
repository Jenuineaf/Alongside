"""Accounts URLconf — profiles, settings, the social graph edges.

Mounted at `/u/`. **Literal paths come before `<str:username>/`** — Django
matches in order, so with the username pattern first, `/u/settings/` would
resolve to a profile lookup for a user called "settings". Those words are on the
reserved-username list so it would 404 rather than leak, but it would 404 the
*settings page*, which is a confusing bug to find.

`str`, not `slug`: usernames are `[a-z0-9_]{3,30}` and Django's `slug` converter
does not match underscores, so `slug` would 404 every username with one in it.
"""

from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("settings/", views.settings, name="settings"),
    path("settings/profile/", views.profile_edit, name="profile_edit"),
    path("settings/blocked/", views.blocked_list, name="blocked"),
    path("settings/delete/", views.delete_account, name="delete_account"),
    path("settings/delete/cancel/", views.cancel_deletion, name="cancel_deletion"),
    # Graph edges. All POST-only — see views.
    path("<str:username>/follow/", views.follow, name="follow"),
    path("<str:username>/unfollow/", views.unfollow, name="unfollow"),
    path("<str:username>/follow/note/", views.follow_note, name="follow_note"),
    path("<str:username>/block/", views.block, name="block"),
    path("<str:username>/unblock/", views.unblock, name="unblock"),
    path("<str:username>/followers/", views.followers, name="followers"),
    path("<str:username>/following/", views.following, name="following"),
    # Public profile. Last, so it cannot shadow anything above.
    path("<str:username>/", views.profile, name="profile"),
]
