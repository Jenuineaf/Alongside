"""Onboarding — three steps, every one of them skippable.

Spec §4.2 and the roadmap's screen 3. The promise made on the sign-up screen is
that none of this is mandatory and all of it is editable later in Settings, so
**every field here is `required=False`** and every step has a Skip control.

What the steps are for, in the order they are asked:

1. **Purpose** — why you're here. One tap, no typing, and it is the easiest
   question on the flow, which is why it goes first.
2. **Field + occupation** — `Profile.field_tag` is the entire input to Home
   tier 2 (ADR-0004). Skipping it costs the user a better feed and costs us
   nothing else.
3. **Interests** — `ProfileInterest` rows, which drive Home tier 1, plus the
   suggested follows that give a brand-new account something to see.

`onboarding_completed_at` means "reached the end of the flow by **any** path,
including skipping every step" — not "answered the questions" (§1.2). Whether
they answered is derivable from the fields themselves. That distinction is what
lets us re-prompt somebody who bounced halfway without nagging somebody who
deliberately skipped.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import Profile
from posts.models import Tag

# More than this and the step becomes a decision rather than a tap. The Home
# cascade only needs a couple of interests to beat tier 3.
MAX_INTERESTS = 8


class PurposeForm(forms.ModelForm):
    """Step 1. A single choice, rendered as cards."""

    class Meta:
        model = Profile
        fields = ["purpose"]
        labels = {"purpose": _("What brings you here?")}
        widgets = {"purpose": forms.RadioSelect(attrs={"class": "peer sr-only"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].required = False
        # A `blank=True` CharField with choices gets Django's empty "---------"
        # option, which on a radio group renders as a fourth, nameless card.
        self.fields["purpose"].choices = Profile.Purpose.choices


class FieldForm(forms.ModelForm):
    """Step 2. The one answer that unlocks Home tier 2.

    Only **curated** tags are offered here. That is what `Tag.is_curated` is
    for: it is a display concern, not the partition `Tag.kind` would have been
    (ADR-0004). Fifteen broad fields is a picker; the whole free-text tag table
    is not.
    """

    class Meta:
        model = Profile
        fields = ["field_tag", "occupation", "city"]
        labels = {
            "field_tag": _("What's your field?"),
            "occupation": _("What do you do?"),
            "city": _("Where are you?"),
        }
        help_texts = {
            "field_tag": _("We'll show you what's happening in it."),
            "occupation": _("e.g. Android developer, 2 yrs Kotlin"),
            "city": _("Leave blank if you'd rather not say."),
        }
        widgets = {"field_tag": forms.RadioSelect(attrs={"class": "peer sr-only"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
        self.fields["field_tag"].queryset = Tag.objects.filter(is_curated=True).order_by("name")
        self.fields["field_tag"].empty_label = None


class InterestsForm(forms.Form):
    """Step 3. Drives Home tier 1, and the suggested follows alongside it.

    Not a `ModelForm`: `ProfileInterest` is an explicit through-model, so the
    view writes the rows. Curated tags only, same reasoning as step 2 — this is
    a picker, and the free-text vocabulary is unbounded.
    """

    interests = forms.ModelMultipleChoiceField(
        label=_("What are you into?"),
        queryset=Tag.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "peer sr-only"}),
        required=False,
        help_text=_("Pick a few. Your Home feed fills up with these."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["interests"].queryset = Tag.objects.filter(is_curated=True).order_by("name")

    def clean_interests(self):
        interests = self.cleaned_data.get("interests")
        if interests is not None and len(interests) > MAX_INTERESTS:
            raise forms.ValidationError(
                _("Pick up to %(limit)s — you can add more later in Settings."),
                params={"limit": MAX_INTERESTS},
            )
        return interests
