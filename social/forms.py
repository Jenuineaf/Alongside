"""The comment form. One field, because comments are one field.

Comments are first-class on Alongside, not a footer: "people who don't want to
join still add value by suggesting things" (spec §2.5), which is why the control
on post detail is a labelled textarea rather than a one-line reply box squeezed
under the sparks.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

# `Comment.body` is a `TextField` with no database limit, so this number is the
# only thing enforcing `data-model.md` §2.6's "TextField(2000)". Keeping it in
# the form rather than asking the Architect for a `max_length` is deliberate: a
# comment that is 2,001 characters is a product decision, not data corruption.
COMMENT_MAX_LENGTH = 2000


class CommentForm(forms.Form):
    body = forms.CharField(
        label=_("Add a comment"),
        max_length=COMMENT_MAX_LENGTH,
        # CharField strips whitespace, so a textarea containing three newlines
        # is empty and fails `required` — which is what we want.
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("A suggestion counts. You don't have to want to join."),
        error_messages={
            # "This field is required." tells the user about the form. This
            # tells them what to do (design-system.md §5).
            "required": _("Write something first."),
            "max_length": _("That's longer than 2,000 characters — trim it a little."),
        },
    )
