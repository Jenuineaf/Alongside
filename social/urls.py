"""Social URLconf — spark, save and comments.

Mounted at `/s/`. Short prefix on purpose: these are the endpoints HTMX hits on
nearly every card in the feed, and they never appear in the address bar.

Two namespaces split the comment routes, and the split is load-bearing:
`post/<pk>/comment/` is keyed by the **post** (that is where a comment is
created), while `comment/<pk>/…` is keyed by the **comment**. Collapsing them
onto one `<int:pk>` would make "spark comment 7" and "comment on post 7"
indistinguishable from the URL.
"""

from django.urls import path

from social import views

app_name = "social"

urlpatterns = [
    path("spark/<int:pk>/", views.spark, name="spark"),
    path("save/<int:pk>/", views.save, name="save"),
    path("post/<int:pk>/comment/", views.comment_create, name="comment_create"),
    path("comment/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("comment/<int:pk>/spark/", views.comment_spark, name="comment_spark"),
]
