"""Database-level Postgres setup: extensions and the text search configuration.

Lives in `accounts` 0002 — early, and before anything that needs it — because
extensions and text search configurations are **database-global**, not app-scoped.
The original plan (`data-model.md` §10) put them in a late `posts` migration, which
Discovery's review (D4) showed cannot work: an `AddIndex` on `accounts.User` using
`gin_trgm_ops` can't live in a `posts` migration, and §1.2 and §10 disagreed about
where `Profile`'s GIN index went. Creating the extensions first lets every index
live with its own model.

**`english_unaccent` (D1) is the important part of this file.**

Django's `SearchVector` with no `config=` falls back to the database's
`default_text_search_config`, which varies with the Postgres image's initdb locale.
So the same code can produce `english` stemming in Docker and `simple` — no stemming
at all — on Neon. A vector stored under one configuration and queried under another
silently drops matches and returns meaningless ranks: well-formed, indexed, quietly
wrong, exactly like the `Tag.kind` bug in §9.1.

Enabling `unaccent` alone buys nothing either. `unaccent(text)` is `STABLE`, not
`IMMUTABLE`, so it cannot appear in an indexed expression, and `SearchQuery` never
applies it — "sao paulo" still would not match "São Paulo". Folding it into a text
search configuration is what actually makes accent-insensitive search work.

Every `SearchVector` and `SearchQuery` in the codebase must therefore pin
`config="english_unaccent"`. Changing this later invalidates every stored vector in
the database, which is why it lands before the first one is written.

**Deploy note (DevOps, via Jeni):** `CREATE EXTENSION` needs elevated privileges.
The local Postgres container runs as superuser, and Neon permits both `pg_trgm` and
`unaccent` for the database owner — but if the production role is not the owner,
this migration is where the first deploy fails.
"""

from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations

# No IF NOT EXISTS for text search configurations, so the existence check is
# explicit. Keeps the migration safe to re-run against a database where an
# earlier partial attempt already created it.
CREATE_CONFIG = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'english_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION english_unaccent (COPY = english);
        ALTER TEXT SEARCH CONFIGURATION english_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, english_stem;
    END IF;
END
$$;
"""

DROP_CONFIG = "DROP TEXT SEARCH CONFIGURATION IF EXISTS english_unaccent;"


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        # pg_trgm: fuzzy/typo-tolerant matching (tech-stack.md §2).
        TrigramExtension(),
        # unaccent: on its own it does nothing for search — see the docstring.
        UnaccentExtension(),
        migrations.RunSQL(sql=CREATE_CONFIG, reverse_sql=DROP_CONFIG),
    ]
