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
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from accounts.adapters import DISPLAY_NAME_MAX_LENGTH
from accounts.models import Profile
from posts.models import Role


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


MAX_CUSTOM_SKILLS = 3


class FollowNoteForm(forms.Form):
    """The optional note that rides along with a follow (spec §4.4).

    `CharField(200)` on the model is a real database limit, so the form limit
    matches it exactly rather than being merely advisory.
    """

    note = forms.CharField(
        label=_("Say why, if you like"),
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_(
            "This goes in their notification. It's the difference between a number "
            "going up and a conversation starting."
        ),
    )


class ProfileForm(forms.ModelForm):
    """Everything on the profile that the owner can change.

    `display_name` lives on `User`, not `Profile`, so it is declared here and
    written by `save()`. Putting it on this form anyway is deliberate — it is
    the first field on the screen the Designer drew, and splitting one screen
    across two forms to mirror a table split nobody outside the schema can see
    would be the tail wagging the dog.
    """

    display_name = forms.CharField(
        label=_("Your name"),
        max_length=DISPLAY_NAME_MAX_LENGTH,
        required=False,
        help_text=_("Shown on your posts and comments."),
    )

    skills = forms.ModelMultipleChoiceField(
        label=_("Roles you can fill"),
        queryset=Role.objects.filter(is_curated=True).order_by("category", "name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("What you could do on someone else's idea. Pick as many as fit."),
    )

    custom_skills = forms.CharField(
        label=_("Anything else you do"),
        required=False,
        help_text=_("Comma-separated, up to three. Searchable, but not in the role filter."),
    )

    class Meta:
        model = Profile
        fields = [
            "avatar",
            "headline",
            "occupation",
            "bio",
            "work_done",
            "city",
            "is_remote_friendly",
            "github_url",
            "portfolio_url",
            "website_url",
        ]
        labels = {
            "headline": _("One-liner"),
            "occupation": _("What you do"),
            "bio": _("About you"),
            "work_done": _("What you've built so far"),
            "city": _("City"),
            "is_remote_friendly": _("Happy to work remotely"),
        }
        help_texts = {
            "headline": _("Sits under your name on every card."),
            "bio": _("Up to 500 characters."),
            "city": _("Free text — whatever you'd actually say."),
        }
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
            "work_done": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["skills"].initial = self.instance.skills.all()
            self.fields["custom_skills"].initial = ", ".join(self.instance.custom_skills)

    def clean_bio(self):
        # TextField(500) is enforced in forms only — it is not a database limit
        # (data-model.md §0). If this method goes, the limit goes with it.
        bio = self.cleaned_data.get("bio", "")
        if len(bio) > 500:
            raise forms.ValidationError(_("Keep this under 500 characters."))
        return bio

    def clean_work_done(self):
        work_done = self.cleaned_data.get("work_done", "")
        if len(work_done) > 1000:
            raise forms.ValidationError(_("Keep this under 1000 characters."))
        return work_done

    def clean_custom_skills(self):
        raw = self.cleaned_data.get("custom_skills", "")
        entries = [part.strip() for part in raw.split(",") if part.strip()]

        # Deduplicate case-insensitively while keeping what the person typed.
        seen, unique = set(), []
        for entry in entries:
            if entry.casefold() not in seen:
                seen.add(entry.casefold())
                unique.append(entry)

        if len(unique) > MAX_CUSTOM_SKILLS:
            raise forms.ValidationError(
                _("Up to %(limit)s, so pick the three that matter most.")
                % {"limit": MAX_CUSTOM_SKILLS}
            )
        if any(len(entry) > 50 for entry in unique):
            raise forms.ValidationError(_("Keep each one under 50 characters."))
        return unique

    def save(self, user=None, commit=True):
        profile = super().save(commit=False)
        profile.custom_skills = self.cleaned_data["custom_skills"]
        # Derived, never typed — the filterable form of a free-text city
        # (data-model.md §9 Q6). Recomputed on every save so it cannot drift
        # away from the city it is supposed to describe.
        profile.city_slug = slugify(profile.city)[:80]

        if commit:
            profile.save()
            # `.set()` works through `ProfileSkill` because its only extra field
            # has a default. It writes the rows, so `PROTECT` on `role` still
            # applies (ACC-3).
            profile.skills.set(self.cleaned_data["skills"])

            if user is not None:
                user.display_name = self.cleaned_data.get("display_name", "").strip()
                user.save(update_fields=["display_name"])

        return profile
