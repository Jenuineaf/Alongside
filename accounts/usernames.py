"""Turning arbitrary text into an Alongside username.

`data-model.md` §10 flags this as the Accounts seat's problem, and it is a real
one rather than a tidiness concern:

> allauth's username generation derives a username from the email address on
> Google sign-in, which can produce values that fail our `[a-z0-9_]{3,30}`
> validator (dots, plus signs, uppercase, length).

Concretely, `Jeni.Verse+dev@gmail.com` yields a candidate with two illegal
characters and two capitals. allauth's own `generate_unique_username` tries a
handful of candidates and then raises `NotImplementedError` — so without this
module a Google sign-up dies with a 500 on a screen the user never chose to be
on, and there is nothing they can do about it.

`normalise_username` is pure and gets the exhaustive table-driven test that
`testing.md` §2.1 asks for. `generate_unique_username` is the thin
database-touching wrapper around it, and is what the adapter calls.
"""

import re
import secrets
import unicodedata

from django.contrib.auth import get_user_model

from accounts.validators import (
    RESERVED_USERNAME_PREFIXES,
    RESERVED_USERNAMES,
    USERNAME_REGEX,
)

MIN_LENGTH = 3
MAX_LENGTH = 30

# Used when nothing usable survives normalisation — a name written entirely in
# Devanagari or emoji, say. "user1" would be a worse answer than it looks: this
# is the handle that shows up at /u/<username> and on every card the person
# posts, and the seed data explicitly bans `^(test|user|asdf)\d*$`-shaped names
# (testing.md §7.6). "builder" is at least a word from the product.
FALLBACK_STEM = "builder"

# Anything outside the allowed set collapses to a single underscore, so
# "Jeni.Verse+dev" reads as "jeni_verse_dev" rather than "jeniversedev".
_ILLEGAL = re.compile(r"[^a-z0-9_]+")
_UNDERSCORE_RUNS = re.compile(r"_{2,}")

# Enough sequential attempts to cover any realistic collision on a real name,
# after which a random suffix is both likelier to succeed and less silly than
# `ananya_iyer_147`.
_SEQUENTIAL_ATTEMPTS = 30
_RANDOM_ATTEMPTS = 10


def normalise_username(raw: str | None) -> str:
    """Best-effort conversion of arbitrary text into our username shape.

    Pure, no database. May return `""` (nothing usable survived) or a string
    shorter than `MIN_LENGTH` — this normalises, it does not validate. Callers
    that need a usable username go through `generate_unique_username`.
    """
    if not raw:
        return ""

    value = str(raw).strip()

    # An email address contributes its local part only. Without this,
    # "jeni@gmail.com" becomes "jeni_gmail_com".
    value = value.split("@", 1)[0]

    # Decompose, then drop the combining marks: "José" → "jose", not "jos".
    # Doing this before casefold also flattens homoglyph-ish forms such as "İ".
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()

    value = _ILLEGAL.sub("_", value)
    value = _UNDERSCORE_RUNS.sub("_", value).strip("_")

    # Truncating can strand a trailing underscore, which is legal but ugly.
    return value[:MAX_LENGTH].rstrip("_")


def is_allowed(username: str) -> bool:
    """Is this username structurally usable, ignoring whether anyone has it?

    Pure, no database. Separated from `is_available` because the two failures
    need different responses: a *taken* name can be fixed with a numeric suffix,
    a *disallowed* one cannot — `deleted_1`, `deleted_2`, `deleted_3` are all
    equally forbidden, so suffixing a reserved stem loops until it gives up.
    """
    if not MIN_LENGTH <= len(username) <= MAX_LENGTH:
        return False
    if not re.fullmatch(USERNAME_REGEX, username):
        return False
    return not (username in RESERVED_USERNAMES or username.startswith(RESERVED_USERNAME_PREFIXES))


def is_available(username: str) -> bool:
    """Is this username well-formed, unreserved, and unused?

    Touches the database — but only after the free checks have passed, so the
    common rejections cost no query.
    """
    if not is_allowed(username):
        return False
    return not get_user_model().objects.filter(username=username).exists()


def generate_unique_username(*candidates: str | None) -> str:
    """Derive a free, valid username from whatever the caller has to hand.

    Candidates are tried in order — for Google sign-in that is display name,
    then email — and the first that normalises to something long enough wins the
    stem. Collisions get `_2`, `_3`, … appended, with the stem trimmed so the
    result still fits `CharField(30)`.
    """
    stem = next(
        (
            normalised
            for normalised in (normalise_username(candidate) for candidate in candidates)
            if len(normalised) >= MIN_LENGTH
        ),
        FALLBACK_STEM,
    )

    # A reserved *prefix* cannot be escaped by suffixing: `deleted_1`,
    # `deleted_2` and `deleted_ab12cd` are all equally forbidden, so a Google
    # account called "Deleted 1" would burn every attempt below and then raise.
    # Reserved whole words are different — `admin` is taken but `admin_2` is
    # free — so those are left to the loop.
    if stem.startswith(RESERVED_USERNAME_PREFIXES):
        stem = FALLBACK_STEM

    if is_available(stem):
        return stem

    for suffix in range(2, _SEQUENTIAL_ATTEMPTS + 2):
        attempt = _with_suffix(stem, str(suffix))
        if is_available(attempt):
            return attempt

    for _ in range(_RANDOM_ATTEMPTS):
        attempt = _with_suffix(stem, secrets.token_hex(3))
        if is_available(attempt):
            return attempt

    # 40 collisions on one stem, six of them against a 16-million-value random
    # space. Something is wrong with the database, not with the name — fail
    # loudly rather than hand allauth an invalid username to choke on later.
    raise RuntimeError(f"Could not derive a free username from {stem!r}")


def _with_suffix(stem: str, suffix: str) -> str:
    """`stem` + `_` + `suffix`, trimmed to fit, without a doubled underscore."""
    room = MAX_LENGTH - len(suffix) - 1
    return f"{stem[:room].rstrip('_') or FALLBACK_STEM[:room]}_{suffix}"
