# Hand-written by the Architect, 3 Oct 2026, for Django 5.2.17.
#
# Not generated: there is no Python, Django or Postgres on the authoring machine,
# so `makemigrations` could not be run. The shape below was derived field by field
# from `notifications/models.py` and matched against the generated output style of
# `posts` 0004 and `accounts` 0003 (field ordering: non-relational in declaration
# order, then related fields alphabetically; kwargs alphabetically; indexes before
# constraints, each in Meta declaration order).
#
# **Unapplied and unverified.** The first `migrate` against a real database — and
# CI's `makemigrations --check` drift gate — are what confirm it.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    # Both of these are inferrable from the FKs — nothing here is a hand-added
    # dependency in the sense `data-model.md` §10 means (no extension, no graph
    # ordering Django cannot see).
    #
    # `posts` 0004 rather than 0003: `Comment` is created in 0004, and 0004 already
    # depends on 0003, so `Post` comes along transitively. There is deliberately no
    # `messaging` dependency — the `conversation` FK, the `new_message` kind and the
    # S4 unread-DM unique constraint all land in `notifications` 0002 alongside
    # `messaging` 0001, which cannot be finalised while decision E is open (§12.4).
    dependencies = [
        ('posts', '0004_comments_sparks_saves'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                # `new_message` is absent on purpose until 0002 — see the model's
                # `NotificationKind` docstring.
                ('kind', models.CharField(choices=[('new_comment', 'New comment'), ('new_follower', 'New follower')], max_length=20, verbose_name='kind')),
                ('is_read', models.BooleanField(default=False, verbose_name='read')),
                # `db_index=True` is not redundant with either index below: both lead
                # with `recipient`, and the 90-day prune job (§8) scans by age.
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications_sent', to=settings.AUTH_USER_MODEL)),
                ('comment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='posts.comment')),
                ('post', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='posts.post')),
                # `db_index=False` is deliberate: `notification_recipient_idx` below
                # leads with `recipient`, so Django's own FK index would be a strict
                # prefix of an index we already build — write amplification on the
                # app's highest-insert table. Mirror case of ACC-4.
                ('recipient', models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'notification',
                'verbose_name_plural': 'notifications',
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', '-created_at'], name='notification_recipient_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(condition=models.Q(('is_read', False)), fields=['recipient'], name='notification_unread_idx'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(('recipient', models.F('actor')), _negated=True), name='notification_not_self'),
        ),
        # S7. Also the gate that keeps `new_message` rows out of the table until
        # 0002: the branches are exhaustive by construction, so any unlisted `kind`
        # fails the whole condition.
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('actor__isnull', False), ('comment__isnull', False), ('kind', 'new_comment'), ('post__isnull', False)), models.Q(('actor__isnull', False), ('comment__isnull', True), ('kind', 'new_follower'), ('post__isnull', True)), _connector='OR'), name='notification_kind_targets'),
        ),
        # S5, ruled yes by Jeni 3 Oct 2026: collapse repeat follow notifications.
        # Partial, so it constrains only unread `new_follower` rows.
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.UniqueConstraint(condition=models.Q(('is_read', False), ('kind', 'new_follower')), fields=('recipient', 'actor'), name='uniq_unread_follow_notification_per_actor'),
        ),
    ]
