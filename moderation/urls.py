"""Reporting URLs, mounted at `/report/`.

Three targets, keyed the way each one is addressed everywhere else in the app:
a post by its slug, a comment by its pk, a person by their username.
"""

from django.urls import path

from moderation import views

app_name = "moderation"

urlpatterns = [
    path("idea/<slug:slug>/", views.report_post, name="report_post"),
    path("comment/<int:pk>/", views.report_comment, name="report_comment"),
    path("user/<str:username>/", views.report_user, name="report_user"),
]
