"""Username derivation — the pure half.

`testing.md` §2.1 puts "username validation + reserved blocklist" in this seat's
column and asks for exhaustive table-driven edges rather than one happy path.
These need no database, so they run before Postgres is reachable and in
milliseconds.

The database-touching half (`generate_unique_username`, `is_available`) is in
`test_username_allocation.py`.
"""

import pytest
from django.core.exceptions import ValidationError

from accounts.usernames import MAX_LENGTH, normalise_username
from accounts.validators import username_format_validator, validate_username_not_reserved


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The ordinary cases.
        ("jeni", "jeni"),
        ("Jeni", "jeni"),
        ("  jeni  ", "jeni"),
        ("Ananya Iyer", "ananya_iyer"),
        # The case data-model.md §10 names: an email address with the two
        # characters Gmail allows and our validator does not.
        ("Jeni.Verse+dev@gmail.com", "jeni_verse_dev"),
        ("jeni@gmail.com", "jeni"),
        # Accents are folded rather than dropped, so "José" is not "jos".
        ("José", "jose"),
        ("Zoë Ó Súilleabháin", "zoe_o_suilleabhain"),
        # Dotted capital I: NFKD splits it, the combining dot goes, "i" remains.
        ("İstanbul", "istanbul"),
        # Runs of illegal characters collapse to one underscore, not many.
        ("a...b", "a_b"),
        ("a   b", "a_b"),
        ("!!!jeni!!!", "jeni"),
        # Leading and trailing underscores are stripped — legal, but nobody
        # means to have them.
        ("_jeni_", "jeni"),
        ("__jeni__", "jeni"),
        # Nothing usable survives. The caller substitutes a stem; this function
        # does not pretend to have found one.
        ("", ""),
        (None, ""),
        ("...", ""),
        ("🚀🚀🚀", ""),
        ("अनन्या", ""),
        # Already-legal input is left exactly alone.
        ("a_b", "a_b"),
        ("user_123", "user_123"),
    ],
)
def test_normalise_username(raw, expected):
    assert normalise_username(raw) == expected


def test_normalise_username_truncates_to_the_column_width():
    assert normalise_username("a" * 50) == "a" * MAX_LENGTH


def test_normalise_username_never_leaves_a_trailing_underscore_after_truncation():
    """Truncation must not strand the separator it happened to cut at.

    30 characters of name followed by a space: naive truncation gives
    `...aaaaa_`, which is legal but reads as a bug.
    """
    result = normalise_username("a" * MAX_LENGTH + " iyer")
    assert not result.endswith("_")
    assert len(result) <= MAX_LENGTH


@pytest.mark.parametrize("raw", ["ab", "a", "_a_"])
def test_normalise_username_may_return_something_too_short(raw):
    """It normalises; it does not validate.

    Pinned deliberately: `generate_unique_username` relies on being handed the
    short string so it can decide between padding and falling back, and a future
    "helpful" change that returns "" here would silently swap real names for
    `builder`.
    """
    assert len(normalise_username(raw)) < 3


# ── The validator on the model field ────────────────────────────────────────


@pytest.mark.parametrize("username", ["jen", "jeni", "a_b", "user_123", "a" * 30])
def test_format_validator_accepts(username):
    username_format_validator(username)


@pytest.mark.parametrize(
    "username",
    [
        "ab",  # 2 chars
        "a" * 31,  # 31 chars
        "Jeni",  # uppercase
        "jeni.verse",  # dot
        "jeni-verse",  # hyphen
        "jeni verse",  # space
        "jeni+dev",  # plus
        "",  # empty
    ],
)
def test_format_validator_rejects(username):
    with pytest.raises(ValidationError):
        username_format_validator(username)


@pytest.mark.parametrize("username", ["admin", "API", "Admin", "feed", "settings", "deleted"])
def test_reserved_names_are_rejected_case_insensitively(username):
    with pytest.raises(ValidationError):
        validate_username_not_reserved(username)


@pytest.mark.parametrize("username", ["deleted_1", "deleted_ab12cd", "DELETED_x"])
def test_reserved_prefix_is_rejected(username):
    """ACC-11: `deleted` alone was blocked but `deleted_1` was not.

    Anonymisation rewrites handles to `deleted_<hex>`, so without the prefix
    rule a real person could register a convincing tombstone and sit next to
    genuinely anonymised accounts.
    """
    with pytest.raises(ValidationError):
        validate_username_not_reserved(username)


@pytest.mark.parametrize("username", ["jeni", "administrator", "undeleted", "team_alpha"])
def test_unreserved_names_pass(username):
    """Only exact matches and the declared prefixes are reserved.

    `administrator`, `undeleted` and `team_alpha` all contain a reserved string
    without being one. Over-reserving costs real people real usernames, so the
    blocklist stays a blocklist rather than becoming a substring search.
    """
    validate_username_not_reserved(username)
