"""The message composer. One field, because a chat box is one field.

`MAX_MESSAGE_LENGTH` lives on the model module (§0 — `TextField(N)` is not a
database limit, so the number has to be enforced somewhere), and it is generous:
4,000 characters is a long message, and the people this product is for are
explaining ideas to strangers.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from messaging.models import MAX_MESSAGE_LENGTH


class MessageForm(forms.Form):
    body = forms.CharField(
        label=_("Message"),
        max_length=MAX_MESSAGE_LENGTH,
        # CharField strips, so a box containing only newlines is empty and
        # fails `required` — which is what stops an accidental Enter sending a
        # blank line into somebody's thread.
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": _("Say hello…")}),
        error_messages={"required": _("Type something first.")},
    )
