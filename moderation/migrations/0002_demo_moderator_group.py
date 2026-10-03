"""Seed the `demo_moderator` Group.

**Decision I (Jeni, 3 Oct 2026):** yes, a `demo_moderator` Group, with the
permissions needed to work the report queue in Django admin and nothing more.
Resolves `data-model.md` §12.4 Decision I and QA finding 6 (`docs/review/qa.md`).

The problem it closes: `testing.md` §7.5 publishes a staff account's credentials on
the login screen so the moderation queue is demonstrable in a portfolio piece. The
write restriction that protects the other public demo accounts is
`User.is_public_demo`, which is an **application-layer permission check that Django
admin never consults**. As specified, anyone reading the login screen could open
`/admin/`, delete every row in the database, and reset other users' passwords. The
Group is what makes the published account safe to publish: `is_staff=True` (so the
admin door opens) plus `view_report` and `change_report` and nothing else.

Two permissions, deliberately:

- `moderation.view_report` — see the queue and open a report.
- `moderation.change_report` — set `status`, write `resolution_note`, and run the
  three queue actions, which is the entire job (§6.1: no `ModerationAction` model).

Not granted, each for a reason:

- **no `add_report`** — reports come from the report form, not from admin.
- **no `delete_report`** — the report is the evidence that justifies the action
  taken on it, and `django.contrib.admin.models.LogEntry` is the audit trail that
  stands in for a `ModerationAction` model. Deleting reports erases both.
- **no permission on `Post`, `Comment` or `User`** — the reported content is
  rendered read-only on the report page itself (see `ModerationReportAdmin`'s
  `target_preview`), so the queue is fully workable without them. A moderator who
  needs to remove a post asks Jeni, who is a superuser. This is also what QA's
  "no `delete_*` on any installed model, iterated not hand-listed" assertion is
  asserting against.

**A data migration rather than a management command or a fixture**, same reasoning as
`posts` 0002: it must exist identically in dev, CI and production, exactly once, with
no extra step anybody can forget. The seed command puts `demo.mod@` in the Group; it
does not create it.

### Why this creates the Permission rows itself

Django creates `Permission` rows in a **`post_migrate` signal**, which runs *after*
the whole migration plan. So at the moment this migration runs, on a fresh database,
`moderation.view_report` **does not exist yet** — a plain `Permission.objects.get()`
here raises `DoesNotExist` and takes the first deploy down with it. This is the
standard trap with permission data migrations and the reason this file looks longer
than it should.

So it `get_or_create`s the `ContentType` and the two `Permission` rows itself. That is
safe rather than duplicative: `django.contrib.auth`'s own `create_permissions()`
keys on `(content_type, codename)` with `get_or_create`, so when `post_migrate` runs
a few seconds later it finds these rows and leaves them alone. The `name` values
match what Django would have generated from `Meta.verbose_name = "report"`, so the
admin UI reads identically either way.
"""

from django.db import migrations

from moderation.models import DEMO_MODERATOR_GROUP

# (codename, name) — `name` matches what `create_permissions()` generates from
# `Report.Meta.verbose_name`, so whichever of the two runs first, the row is the same.
QUEUE_PERMISSIONS = [
    ("view_report", "Can view report"),
    ("change_report", "Can change report"),
]


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _created = ContentType.objects.get_or_create(
        app_label="moderation",
        model="report",
    )

    permissions = []
    for codename, name in QUEUE_PERMISSIONS:
        permission, _created = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions.append(permission)

    group, _created = Group.objects.get_or_create(name=DEMO_MODERATOR_GROUP)
    # `set()` rather than `add()`, so re-running against a database where someone has
    # widened this Group by hand brings it back to exactly these two permissions.
    # Over-permission is the failure mode this Group exists to prevent, so the
    # idempotent form is the restrictive one.
    group.permissions.set(permissions)


def delete_group(apps, schema_editor):
    """Remove the Group, and only the Group.

    The two `Permission` rows are left alone: they belong to the `Report` model, not
    to this Group, and `post_migrate` would recreate them anyway. Users lose their
    membership with the Group row — M2M rows go with it.
    """
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=DEMO_MODERATOR_GROUP).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("moderation", "0001_initial"),
        # Both are needed and neither is inferable: this migration writes `auth` and
        # `contenttypes` tables, so they must already exist.
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
