"""allauth adapters — where Alongside's rules meet allauth's flows.

Two jobs, both flagged in `data-model.md` §10 as belonging to this seat:

1. Usernames derived from Google sign-in must satisfy `[a-z0-9_]{3,30}` and the
   reserved-name list, or the sign-up dies on a validation error the user cannot
   act on. See `accounts/usernames.py` for the derivation itself.
2. A person typing `Jeni` into the username box on sign-up should get `jeni`,
   not an error. The model lowercases on save either way; erroring first just
   makes them do it by hand.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_username
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from accounts import usernames

DISPLAY_NAME_MAX_LENGTH = 60


class AccountAdapter(DefaultAccountAdapter):
    """Email/password signup, login, and the shared username rules."""

    def clean_username(self, username: str, shallow: bool = False) -> str:
        """Fold case before validating.

        `User.save()` lowercases anyway (`accounts/models.py`), so rejecting
        `Jeni` would be an error message about a difference we are about to
        erase. Stripping matters too: a trailing space pasted from a password
        manager is otherwise an invalid-character error naming a character the
        user cannot see.
        """
        return super().clean_username((username or "").strip().lower(), shallow=shallow)

    def generate_unique_username(self, txts, regex=None) -> str:
        """Replace allauth's derivation with ours.

        allauth's own version builds candidates against a permissive regex and
        raises `NotImplementedError` when none of them pass — which, against our
        strict validator plus a reserved-name list, is a realistic outcome for an
        ordinary Google account rather than an edge case.
        """
        return usernames.generate_unique_username(*txts)

    def save_user(self, request, user, form, commit=True):
        """Carry `display_name` across from the signup form.

        Optional on purpose: `User.name` falls back to the username, so a person
        who leaves it blank still renders correctly everywhere.
        """
        user = super().save_user(request, user, form, commit=False)

        display_name = (form.cleaned_data.get("display_name") or "").strip()
        if display_name:
            user.display_name = display_name[:DISPLAY_NAME_MAX_LENGTH]

        if commit:
            user.save()
        return user


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google sign-in."""

    def populate_user(self, request, sociallogin, data):
        """Fill in a usable username and display name before the form renders.

        Deriving the username *here* rather than leaving it to `save_user` is
        the difference between the sign-up screen arriving with `ananya_iyer`
        already in the box and arriving with an empty required field the person
        has to invent an answer for, having just clicked a button that implied
        there was nothing left to do.
        """
        user = super().populate_user(request, sociallogin, data)

        if not user.display_name:
            full_name = (data.get("name") or "").strip()
            if not full_name:
                parts = [data.get("first_name"), data.get("last_name")]
                full_name = " ".join(part for part in parts if part).strip()
            user.display_name = full_name[:DISPLAY_NAME_MAX_LENGTH]

        if not user_username(user):
            user_username(
                user,
                usernames.generate_unique_username(
                    user.display_name,
                    data.get("username"),
                    data.get("email"),
                ),
            )

        return user
