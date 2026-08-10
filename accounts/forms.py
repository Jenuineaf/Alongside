"""Signup forms.

allauth's own forms handle email, username and password. These add the one field
Alongside wants at sign-up and nothing else — everything about the person
(occupation, interests, skills, links) belongs to onboarding and the profile,
both of which are skippable. A long sign-up form is the fastest way to lose the
user before they have seen anything.
"""

from allauth.account.forms import SignupForm as AllauthSignupForm
from allauth.socialaccount.forms import SignupForm as AllauthSocialSignupForm
from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.adapters import DISPLAY_NAME_MAX_LENGTH


class DisplayNameMixin(forms.Form):
    """Adds `display_name` to whichever signup form it is mixed into.

    Optional: `User.name` falls back to the username (`accounts/models.py`), so
    a blank one renders correctly on every card and comment. Asking for it is
    worth one field — "Ananya Iyer" reads as a person in a comment thread and
    "ananya_iyer_2" reads as a handle.
    """

    display_name = forms.CharField(
        label=_("Your name"),
        max_length=DISPLAY_NAME_MAX_LENGTH,
        required=False,
        help_text=_("Shown on your posts and comments. You can change it later."),
    )

    # Name first: it is the easiest question on the page and the only one that
    # is about them rather than about the account.
    field_order = ["display_name", "email", "username", "password1", "password2"]


class SignupForm(DisplayNameMixin, AllauthSignupForm):
    """Email + password sign-up. Wired in via `ACCOUNT_FORMS["signup"]`."""


class SocialSignupForm(DisplayNameMixin, AllauthSocialSignupForm):
    """The confirm-your-details step after Google.

    `SocialAccountAdapter.populate_user` has already derived a valid username
    and pulled the name across from Google, so this form arrives filled in and
    the person only has to press the button — but every field stays editable,
    because a Google display name is not always what someone wants on a public
    profile.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # allauth seeds `initial` from email/username only, so the name Google
        # gave us has to be put back here or the field renders empty next to a
        # prefilled username, which looks like a bug.
        if not self.initial.get("display_name"):
            self.initial["display_name"] = self.sociallogin.user.display_name
