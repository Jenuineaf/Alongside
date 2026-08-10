"""Seed the curated tag and role vocabulary.

A **data migration**, not a fixture or a management command, for one specific
reason (ADR-0004): `Profile.field_tag` is a foreign key, and Home tier 2 matches a
user's field tag against post tags. If these rows are created ad hoc, they get
different ids — or different slugs — in dev, CI, and production, and the tier-2
query silently returns nothing in exactly one environment. Data migrations run
everywhere, once, in order.

**Tags here are the ~15 broad *fields*** offered in the onboarding picker
(`is_curated=True`). They are ordinary tags: posts can and should carry them, which
is the whole point of ADR-0004. Users remain free to create their own topic tags —
those arrive with `is_curated=False` and never show up in the field picker.

**Roles are the full curated vocabulary.** Roles are exact-match filtered, so this
list *is* the filter. Adding to it later is a normal data migration; the cost of a
missing role is one person picking a near-neighbour, which is much cheaper than the
fragmentation free text would cause.

Idempotent by slug, so re-running against a database that already has some of these
is safe.
"""

from django.db import migrations
from django.utils.text import slugify

# ── Curated field tags ──────────────────────────────────────────────────────
# Chosen to cover the fields `product-spec.md` §1 and `testing.md` §7.1 name by
# hand — including craft & small business, which is the crochet-business case the
# spec calls out and the one most likely to be forgotten by a room of engineers.
CURATED_TAGS = [
    "Software",
    "AI & Data",
    "Hardware & IoT",
    "Games",
    "Design",
    "Fintech",
    "Edtech",
    "Climate",
    "Health & Fitness",
    "Food & Drink",
    "Craft & Small Business",
    "E-commerce",
    "Content & Media",
    "Campus & Civic",
    "Social Impact",
]

# ── Curated roles ───────────────────────────────────────────────────────────
CURATED_ROLES = [
    # engineering
    ("Backend Developer", "engineering"),
    ("Frontend Developer", "engineering"),
    ("Full-stack Developer", "engineering"),
    ("Android Developer", "engineering"),
    ("iOS Developer", "engineering"),
    ("Data Scientist", "engineering"),
    ("ML Engineer", "engineering"),
    ("DevOps Engineer", "engineering"),
    ("QA Engineer", "engineering"),
    ("Hardware Engineer", "engineering"),
    ("Embedded Engineer", "engineering"),
    # design
    ("UI Designer", "design"),
    ("UX Designer", "design"),
    ("Product Designer", "design"),
    ("Graphic Designer", "design"),
    ("Illustrator", "design"),
    ("Motion Designer", "design"),
    # product
    ("Product Manager", "product"),
    ("Project Manager", "product"),
    ("Business Analyst", "product"),
    ("User Researcher", "product"),
    # business
    ("Co-founder", "business"),
    ("Marketer", "business"),
    ("Growth Lead", "business"),
    ("Sales Lead", "business"),
    ("Operations Lead", "business"),
    ("Finance Lead", "business"),
    ("Legal Advisor", "business"),
    ("Partnerships Lead", "business"),
    # creative
    ("Writer", "creative"),
    ("Content Creator", "creative"),
    ("Video Editor", "creative"),
    ("Photographer", "creative"),
    ("Musician", "creative"),
    ("Animator", "creative"),
    ("Textile & Craft Maker", "creative"),
    ("Chef / Food Maker", "creative"),
    # other
    ("Mentor / Advisor", "other"),
    ("Community Manager", "other"),
    ("Translator", "other"),
    # PF-7's escape hatch. If posts must declare at least one role, "I'm open to
    # anything" needs to be a *filterable value* rather than a null hole — a post
    # with no roles can never appear in a role-filtered result, which is the
    # joiner's primary path (roadmap §1.3).
    ("Open to anyone / not sure yet", "other"),
]


def seed(apps, schema_editor):
    Tag = apps.get_model("posts", "Tag")
    Role = apps.get_model("posts", "Role")

    for name in CURATED_TAGS:
        Tag.objects.update_or_create(
            slug=slugify(name),
            defaults={"name": name, "is_curated": True},
        )

    for name, category in CURATED_ROLES:
        Role.objects.update_or_create(
            slug=slugify(name),
            defaults={"name": name, "category": category, "is_curated": True},
        )


def unseed(apps, schema_editor):
    """Remove only rows nothing points at.

    A blind delete would fail against `PROTECT` on `PostTag` / `PostRole` the moment
    any post uses one of these — which is the correct outcome, but a confusing way
    to discover it. Reversing this migration on a populated database is not a
    supported operation; this exists so the migration is reversible on a fresh one.
    """
    Tag = apps.get_model("posts", "Tag")
    Role = apps.get_model("posts", "Role")

    Tag.objects.filter(
        slug__in=[slugify(name) for name in CURATED_TAGS],
        post_tags__isnull=True,
    ).delete()
    Role.objects.filter(
        slug__in=[slugify(name) for name, _category in CURATED_ROLES],
        post_roles__isnull=True,
        profile_skills__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0001_vocabulary"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
