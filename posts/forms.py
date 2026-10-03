"""The create / edit form for an idea. Screen 7.

This is the form the whole product depends on, and the one place where losing
the user costs the most — so every field that can be optional is optional, and
there is exactly one required answer beyond the idea itself.

**Decision F (Jeni, 3 Oct 2026): a post must name at least one role it needs.**
Tags stay optional. The reasoning is that a joiner scanning the feed is looking
for one thing — a role they can fill — so an idea with no roles cannot be
matched, filtered, or recommended; it just sits there. The escape hatch for
somebody who genuinely does not know is the seeded **"Open to anyone / not sure
yet"** role, which is why requiring an answer is not the same as demanding one.

Caps come from `posts/models.py`, not from here: the DRF serializer and the seed
command have to read the same numbers (PF-5 — "enforced in the form" stops being
sufficient the moment an API exists).

There are **no drafts** (§2.3.1), so there is no "save draft" control. The
Designer drew one and removed it in the v6 sweep (GAP 6) — if it had shipped,
somebody would have built a draft state to satisfy the button.
"""

from django import forms
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from posts.models import (
    MAX_BODY_LENGTH,
    MAX_CURATED_ROLES_PER_POST,
    MAX_CUSTOM_ROLES_PER_POST,
    MAX_TAGS_PER_POST,
    Commitment,
    Post,
    PostStatus,
    Role,
    Stage,
)

CUSTOM_ROLE_MAX_LENGTH = 50
TAG_MAX_LENGTH = 40


class PostForm(forms.ModelForm):
    """Create or edit. `status` only appears when editing (the wireframe's note).

    A `ModelForm` for the plain columns, with `roles`, `custom_roles` and `tags`
    added by hand: none of the three is a simple field on `Post`, and the two
    free-text ones are comma-separated strings on the way in and lists on the
    way out.
    """

    # `class="peer sr-only"` on every choice input is what lets the templates
    # draw these as chips and segmented controls: the real input stays in the
    # DOM for the keyboard and the screen reader, and the visible element is a
    # sibling styled with Tailwind's `peer-checked:`. Without the class the
    # control renders as a bare browser radio with an unstyled label beside it.
    CHOICE_ATTRS = {"class": "peer sr-only"}

    roles = forms.ModelMultipleChoiceField(
        label=_("What do you need?"),
        queryset=Role.objects.none(),  # set in __init__ — see the note there
        widget=forms.CheckboxSelectMultiple(attrs=CHOICE_ATTRS),
        required=False,  # enforced in clean(), together with custom_roles
        help_text=_("Pick the roles you're looking for. This is what people filter on."),
    )
    custom_roles = forms.CharField(
        label=_("Something else?"),
        required=False,
        help_text=_("Comma-separated, up to 3. Searchable, but people can't filter on these."),
    )
    tags = forms.CharField(
        label=_("Topics"),
        required=False,
        help_text=_("Comma-separated, up to 5. What the idea is about — food waste, kannada, ocr."),
    )

    class Meta:
        model = Post
        fields = [
            "title",
            "body",
            "stage",
            "commitment",
            "city",
            "is_remote_friendly",
        ]
        labels = {
            "title": _("Your idea, in one line"),
            "body": _("Tell people about it"),
            "stage": _("How far along is it?"),
            "commitment": _("How serious is this?"),
            "city": _("City"),
            "is_remote_friendly": _("Remote is fine"),
        }
        help_texts = {
            "title": _("A sentence works better than a name. People scan these."),
            "body": _("What it is, why it matters, what you've done so far."),
            "city": _("Leave blank if you're remote-only."),
        }
        widgets = {
            "body": forms.Textarea(attrs={"rows": 8}),
            "stage": forms.RadioSelect(attrs={"class": "peer sr-only"}),
            "commitment": forms.RadioSelect(attrs={"class": "peer sr-only"}),
        }

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)

        # Evaluated here rather than at class definition time: a module-level
        # queryset is built once per process, so a role added by a later data
        # migration would never appear in the picker on a long-running worker.
        self.fields["roles"].queryset = Role.objects.filter(is_curated=True).order_by(
            "category", "name"
        )

        # `stage` and `commitment` have no model default, so an unbound form
        # renders with Django's empty "---------" choice on a radio group, which
        # looks like a broken control. Removing the empty choice makes the radios
        # a genuine "pick one of three".
        self.fields["stage"].choices = Stage.choices
        self.fields["commitment"].choices = Commitment.choices
        self.fields["body"].max_length = MAX_BODY_LENGTH

        if instance is not None and instance.pk:
            # Edit mode: status becomes editable, and the three list fields are
            # pre-filled from the rows that exist.
            # `required=False`, and the fallback is the status it already has.
            # A rendered radio group always posts something, so this only
            # matters when a client omits it — an API call, a test, a partial
            # form submit — and in every one of those cases "leave the status
            # alone" is the right answer. Required, it made the whole edit form
            # unsubmittable for anyone who did not know to include a field they
            # were not changing.
            self.fields["status"] = forms.ChoiceField(
                label=_("Still looking?"),
                choices=PostStatus.choices,
                widget=forms.RadioSelect(attrs=self.CHOICE_ATTRS),
                required=False,
                help_text=_("Marking it team formed or closed takes it out of the feed."),
            )
            self.initial.setdefault("status", instance.status)
            self.initial.setdefault("roles", list(instance.roles_needed.values_list("pk", flat=True)))
            self.initial.setdefault("custom_roles", ", ".join(instance.custom_roles or []))
            self.initial.setdefault(
                "tags", ", ".join(instance.tags.values_list("name", flat=True))
            )

    # ── Cleaning ────────────────────────────────────────────────────────────

    def clean_roles(self):
        roles = self.cleaned_data.get("roles")
        if roles is not None and len(roles) > MAX_CURATED_ROLES_PER_POST:
            raise forms.ValidationError(
                _("Pick up to %(limit)s roles — a long list reads as "
                  "'anyone will do' and people stop scanning."),
                params={"limit": MAX_CURATED_ROLES_PER_POST},
            )
        return roles

    def clean_custom_roles(self):
        """Comma-separated free text → a list, capped, deduplicated."""
        entries = _split_list(self.cleaned_data.get("custom_roles", ""), CUSTOM_ROLE_MAX_LENGTH)

        if len(entries) > MAX_CUSTOM_ROLES_PER_POST:
            raise forms.ValidationError(
                _("Up to %(limit)s of your own. For anything more, pick from the list above."),
                params={"limit": MAX_CUSTOM_ROLES_PER_POST},
            )
        return entries

    def clean_tags(self):
        """Same shape, but deduplicated on **slug** rather than on the raw text.

        "Food Waste" and "food waste" are one tag (ADR-0004 keeps tags free text
        precisely so people can type what they mean), and letting both through
        would put two near-identical chips on the same card.
        """
        entries = _split_list(self.cleaned_data.get("tags", ""), TAG_MAX_LENGTH)

        seen: set[str] = set()
        unique: list[str] = []
        for entry in entries:
            slug = slugify(entry)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            unique.append(entry)

        if len(unique) > MAX_TAGS_PER_POST:
            raise forms.ValidationError(
                _("Up to %(limit)s topics."), params={"limit": MAX_TAGS_PER_POST}
            )
        return unique

    def clean(self):
        """Decision F, enforced across two fields rather than one.

        Either a curated role or an "Other" role satisfies it. Requiring a
        *curated* one specifically would reject the person who knows exactly
        what they need and finds it missing from our list — which is the one
        user the "Other" box exists for.
        """
        cleaned = super().clean()

        if not cleaned.get("roles") and not cleaned.get("custom_roles"):
            self.add_error(
                "roles",
                _(
                    "Say what you're looking for — it's the first thing people "
                    "scan for. If you're not sure yet, pick “Open to anyone / "
                    "not sure yet”."
                ),
            )

        return cleaned

    # ── Convenience for the view ────────────────────────────────────────────

    @property
    def service_kwargs(self) -> dict:
        """The three list fields, shaped for `posts.services`.

        Keeps the view from reaching into `cleaned_data` and getting the key
        names subtly wrong — the service's signature is `tags=`, `roles=`,
        `custom_roles=`, and everything else is a model field.
        """
        return {
            "tags": self.cleaned_data.get("tags", []),
            "roles": list(self.cleaned_data.get("roles") or []),
            "custom_roles": self.cleaned_data.get("custom_roles", []),
        }

    @property
    def field_kwargs(self) -> dict:
        """The plain model columns, plus `status` when editing and it was sent.

        A blank `status` is left out rather than written through: the field is
        optional, and `status=""` would fail the column's choices — or worse,
        silently take the post out of the feed.
        """
        fields = {name: self.cleaned_data[name] for name in self.Meta.fields}
        if self.cleaned_data.get("status"):
            fields["status"] = self.cleaned_data["status"]
        return fields


def _split_list(raw: str, max_length: int) -> list[str]:
    """Comma-separated input → a trimmed, de-duplicated, length-capped list.

    Collapses internal whitespace so "food   waste" is "food waste": people
    paste, and a tag with a double space in it never matches anything typed by
    hand.
    """
    entries: list[str] = []
    seen: set[str] = set()

    for chunk in (raw or "").split(","):
        cleaned = " ".join(chunk.split())[:max_length]
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        entries.append(cleaned)

    return entries
