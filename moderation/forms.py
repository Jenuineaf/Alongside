"""The report form.

One screen, three fields, and the only hard rule is that "Other" has to say
something — a queue full of reports reading only "other" is a queue a moderator
cannot work.

**Signing in is required** (Decision H, Jeni, 3 Oct 2026). Not to raise the
barrier to flagging real abuse, but because the anti-brigading constraint —
one open report per person per target — needs a reporter to key on. Without it
the queue can be flooded by one person with a script.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from moderation.models import MAX_DETAILS_LENGTH, ReportReason


class ReportForm(forms.Form):
    reason = forms.ChoiceField(
        label=_("What's wrong with it?"),
        choices=ReportReason.choices,
        widget=forms.RadioSelect(attrs={"class": "peer sr-only"}),
        error_messages={"required": _("Pick the closest one.")},
    )
    details = forms.CharField(
        label=_("Anything else we should know?"),
        required=False,
        max_length=MAX_DETAILS_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Optional, unless you picked Other."),
    )

    def clean(self):
        """"Other" without an explanation is not actionable.

        The only required-conditional rule on the form. Every other reason is
        self-describing — a moderator can look at a post reported as spam and
        agree or disagree — but "other" with no text tells them nothing at all,
        and they cannot ask the reporter.
        """
        cleaned = super().clean()

        if cleaned.get("reason") == ReportReason.OTHER and not cleaned.get("details"):
            self.add_error(
                "details",
                _("Tell us what's wrong — we can't act on 'other' by itself."),
            )

        return cleaned
