"""Keyword extraction — plain Python, no database, no Django.

`Post.keywords` exists so that searching "illustrator" finds the post where
somebody typed it into the "Other" box as well as the posts that selected the
curated Illustrator role. It is the free-text half of ADR-0004's bargain.

This module is deliberately dependency-free and side-effect-free: one list of
strings in, one list of strings out. That makes it the cheapest thing in the
project to test (`testing.md` §2.1 asks for a lot of these), and it means the
seed, the create form and the Celery refresh task all derive keywords the same
way.

It is **not** a search engine. Postgres full-text search does the ranking
(`search_vector`); this only decides which words are worth putting in front of
it.
"""

import re
import unicodedata

# Capped to match `Post.keywords`' element `max_length=40`. A longer token is
# almost always a URL or a mangled paste rather than a word anyone searches for.
MAX_KEYWORD_LENGTH = 40

# A keyword list is a search aid, not an index of the document. Twenty is far
# more than any real idea write-up needs, and it bounds the GIN index's row size.
MAX_KEYWORDS = 20

# Two characters is the floor: "AI", "UI" and "VR" are real search terms, while
# single letters never are.
MIN_KEYWORD_LENGTH = 2

# Deliberately short, and deliberately not a general English stopword list.
# Postgres' `english_unaccent` configuration already strips true stopwords when
# it builds the tsvector — this list exists for the words that are *specific to
# this product* and therefore useless as search terms precisely because every
# post contains them. "Idea", "project", "team" and "looking" are on every
# single post on Alongside; a keyword that matches everything matches nothing.
NOISE_WORDS = frozenset(
    {
        "a", "about", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by",
        "can", "could", "did", "do", "does", "for", "from", "get", "got", "had", "has",
        "have", "how", "i", "if", "in", "into", "is", "it", "its", "just", "like", "make",
        "me", "my", "need", "no", "not", "of", "on", "one", "or", "our", "out", "so",
        "some", "than", "that", "the", "their", "them", "then", "there", "these", "they",
        "this", "to", "up", "was", "we", "were", "what", "when", "which", "who", "will",
        "with", "would", "you", "your",
        # Product-specific noise — see above.
        "idea", "ideas", "project", "projects", "team", "teammate", "teammates",
        "looking", "build", "building", "help", "join", "want", "wants", "work",
        "working", "someone", "anyone", "people", "person",
    }
)

# Keeps intra-word hyphens and apostrophes ("bike-repair", "don't") and splits on
# everything else. `\w` under Unicode also keeps non-Latin scripts, which matters:
# the demo corpus is Indian and "ಕನ್ನಡ" must survive tokenisation.
_TOKEN = re.compile(r"[^\w'-]+", re.UNICODE)


def extract_keywords(*sources: str) -> list[str]:
    """Search keywords from any number of text fragments, best-effort and ordered.

    Order is first-appearance, not frequency. The caller passes the title first,
    so the words from the title lead the list — and when the cap truncates, it
    truncates the body rather than the title. Frequency ranking would be the
    obvious alternative and is wrong here: an idea write-up is a few hundred
    words, so term frequency is mostly noise, and the one thing we do know is
    which field a word came from.

    Case-folded and accent-stripped, so "Café" and "cafe" are one keyword —
    matching what `english_unaccent` does to the query side (D1).

    Duplicates are dropped while order is kept. Returns at most `MAX_KEYWORDS`.
    """
    keywords: list[str] = []
    seen: set[str] = set()

    for source in sources:
        if not source:
            continue
        for raw in _TOKEN.split(source):
            token = _normalise(raw)
            if not token or token in seen:
                continue
            if len(token) < MIN_KEYWORD_LENGTH or token in NOISE_WORDS:
                continue
            seen.add(token)
            keywords.append(token)
            if len(keywords) >= MAX_KEYWORDS:
                return keywords

    return keywords


def _normalise(token: str) -> str:
    """Case-fold, strip accents, trim punctuation, and cap the length.

    NFKD then dropping combining marks is the standard way to fold accents in
    Python, and it has to agree with the `english_unaccent` text search
    configuration — if the stored keyword keeps its accent and the query does
    not, the keyword never matches and the failure is silent.
    """
    folded = unicodedata.normalize("NFKD", token.casefold())
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    # Leading/trailing hyphens and apostrophes are punctuation the tokeniser
    # kept because they can also be intra-word.
    return stripped.strip("'-")[:MAX_KEYWORD_LENGTH]


def keywords_for_post(*, title: str, body: str, tags=(), roles=(), custom_roles=()) -> list[str]:
    """`Post.keywords` for one post. Field order here is the ranking.

    Title first, then the things the author explicitly chose (tags, roles, and
    the "Other" roles they typed), then the body. The curated role and tag
    **names** are included on purpose: without them, searching "illustrator"
    found the post where somebody typed it freehand and missed every post that
    correctly selected the Illustrator role — so the author who filled the form
    in properly became the unfindable one (§2.3).
    """
    return extract_keywords(
        title,
        " ".join(tags),
        " ".join(roles),
        " ".join(custom_roles),
        body,
    )
