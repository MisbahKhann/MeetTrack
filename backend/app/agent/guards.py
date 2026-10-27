"""Injection guards and grounding checks.

These guards are defence in depth. They filter and validate LLM input and
output at the Python layer, but the approval gate (the user deciding on
proposals) is the real control. No guard here is a security boundary on its
own; together they reduce the attack surface and catch common errors.

All functions are pure: no I/O, no LLM calls, no side effects.
"""

import re

from app.tools.note_reader import NoteDocument, NoteLine

# ---------------------------------------------------------------------------
# Suspicious line patterns
# ---------------------------------------------------------------------------

SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
    ("ignore_rules", r"ignore\s+(all|any|the|previous|prior|above|\s)*\s*(rules|instructions)"),
    ("disregard", r"disregard\s+(the|all|previous)\s*(rules|instructions)?"),
    ("mark_all", r"mark\s+(every|all|each)"),
    ("system_prompt", r"system\s*prompt"),
    ("you_are_now", r"you\s+are\s+now"),
    ("as_an_ai", r"as\s+an\s+ai"),
    ("override", r"override\s+(instructions|rules|prompt|system|constraints|directives|the\s+rules)"),
    ("new_instructions", r"new\s+instructions"),
    ("reveal_prompt", r"reveal\s+(the\s+)?(prompt|key)"),
]

_COMPILED = [(name, re.compile(p, re.IGNORECASE)) for name, p in SUSPICIOUS_PATTERNS]


def is_suspicious_line(text: str) -> bool:
    """True if the text matches any instruction-injection pattern."""
    for _name, pattern in _COMPILED:
        if pattern.search(text):
            return True
    return False


def find_suspicious_lines(doc: NoteDocument) -> dict[int, str]:
    """Return a mapping of line_number -> pattern_name for suspicious lines."""
    result: dict[int, str] = {}
    for line in doc.lines:
        for name, pattern in _COMPILED:
            if pattern.search(line.text):
                result[line.number] = name
                break
    return result


def withhold_lines(doc: NoteDocument, line_numbers: set[int]) -> NoteDocument:
    """Return a copy where suspicious lines have their text replaced.

    The line numbers stay the same so evidence references still line up.
    The ORIGINAL doc should still be used for verify_quote.
    """
    withheld_text = "[line withheld: instruction-like text]"
    new_lines: list[NoteLine] = []
    for line in doc.lines:
        if line.number in line_numbers:
            new_lines.append(NoteLine(number=line.number, text=withheld_text))
        else:
            new_lines.append(NoteLine(number=line.number, text=line.text))
    return NoteDocument(
        file_name=doc.file_name,
        sha256=doc.sha256,
        header=doc.header,
        lines=new_lines,
        char_count=doc.char_count,
    )


# ---------------------------------------------------------------------------
# Grounding and relevance
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    {
        "the",
        "this",
        "that",
        "will",
        "with",
        "from",
        "have",
        "they",
        "were",
        "been",
        "into",
        "your",
        "their",
        "what",
        "when",
        "then",
        "than",
        "them",
        "some",
        "such",
        "also",
        "only",
        "just",
        "like",
    }
)


def _content_words(text: str, min_len: int = 4) -> set[str]:
    """Extract content words of at least min_len letters, lowercased."""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) >= min_len and w not in _STOPWORDS}


def is_grounded(description: str, source_line_text: str) -> bool:
    """True if at least one content word from the description appears in the source line."""
    desc_words = _content_words(description)
    if not desc_words:
        return False
    source_text = source_line_text.lower()
    return any(w in source_text for w in desc_words)


def evidence_is_relevant(action_description: str, line_text: str, owner: str | None = None) -> bool:
    """True if the evidence line shares a content word with the action or contains the owner's name."""  # noqa: E501
    action_words = _content_words(action_description)
    line_lower = line_text.lower()
    for w in action_words:
        if w in line_lower:
            return True
    if owner and owner.lower() in line_lower:
        return True
    return False
