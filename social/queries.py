"""Read helpers for the engagement layer.

Separate from `services.py` (which only writes) because two apps need the same
comment query and neither should hand-roll it: `posts.views.detail` renders the
thread with the page, and the three comment endpoints in this app re-render it
after a change. One function means the block filter and the per-viewer spark
annotation cannot drift apart between the two.
"""

from django.db.models import Exists, OuterRef

from posts.models import CommentSpark


def visible_comments(post, viewer):
    """The thread as this viewer may see it — oldest first, unpaginated.

    Three things this does that a plain `post.comments.all()` does not:

    1. **Block filter.** `Comment.block_filter_field` is `author` (ADR-0003), so
       `visible_to()` drops comments by anyone the viewer is block-related with.
       A soft-delete filter comes free from `Comment`'s default manager. Post
       detail previously prefetched `comments` unfiltered, which rendered a
       blocked person's comments on an otherwise correctly filtered page.
    2. **`is_sparked` per viewer**, as one `EXISTS` for the whole thread rather
       than one query per comment. Anonymous viewers skip it entirely — the
       attribute is then simply absent, which is falsy in a template, and the
       public page does no visibility work at all (`CLAUDE.md` rule 7).
    3. **Oldest first**, which matches `comment_post_idx` column for column, so
       the thread is an index scan with no sort — and reads correctly: a reply
       below the thing it replies to.

    **Deliberately unpaginated** (S13). ADR-0002 keeps counters global and
    resolves the blocked-comment discrepancy by having post detail render the
    length of the list it fetched. That only holds while the whole thread is on
    the page; paginate it and the heading says "8 comments" above 8 of 40. The
    ceiling is a 300-comment post rendering 300 rows on a phone — fine at seed
    scale, and the fix then is to count the total separately, not to make the
    counter viewer-relative.
    """
    queryset = (
        post.comments.visible_to(viewer)
        .select_related("author", "author__profile")
        .order_by("created_at")
    )

    if viewer is not None and getattr(viewer, "is_authenticated", False):
        queryset = queryset.annotate(
            is_sparked=Exists(CommentSpark.objects.filter(user=viewer, comment=OuterRef("pk")))
        )

    return queryset
