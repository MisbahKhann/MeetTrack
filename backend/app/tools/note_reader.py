"""Note reader tool.

Parses plain-text meeting notes into a structured NoteDocument.
All note content is treated as untrusted input; nothing inside the notes can
alter parsing rules, permissions, or tool behaviour.

Public API:
    parse_notes(content, file_name, *, auto_number) -> NoteDocument
    read_notes_file(path) -> NoteDocument
    render_for_prompt(doc) -> str
    verify_quote(doc, quote, line) -> bool
    get_line(doc, number) -> NoteLine | None
    line_numbers(doc) -> frozenset[int]
"""

import hashlib
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.logging_setup import log_event

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 200 * 1024  # 200 KB
MAX_LINES = 500
MIN_QUOTE_LENGTH = 8

# Header pattern: "Meeting 1 | Team A | 2026-10-05"
_HEADER_RE = re.compile(
    r"^(?P<meeting_label>[^|]+)\|(?P<team_label>[^|]+)\|(?P<meeting_date>[^|]+)$"
)

# Body line pattern: "3. Some text"
_LINE_RE = re.compile(r"^(?P<number>\d+)\.\s+(?P<text>.+)$")

# Delimiter neutralisation patterns
_OPEN_DELIM = "<<<NOTES"
_CLOSE_DELIM = "NOTES>>>"
_OPEN_REPLACE = "< < <NOTES"
_CLOSE_REPLACE = "NOTES> > >"
# Also neutralise bare <<< and >>> inside note text
_RAW_OPEN_RE = re.compile(r"<<<")
_RAW_CLOSE_RE = re.compile(r">>>")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NoteFormatError(ValueError):
    """Raised when note content cannot be parsed."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NoteHeader(BaseModel, frozen=True, extra="forbid"):
    """Parsed meeting header line."""

    meeting_label: str
    team_label: str
    meeting_date: date


class NoteLine(BaseModel, frozen=True, extra="forbid"):
    """A single numbered body line from the notes."""

    number: int = Field(ge=1)
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("NoteLine text must not be empty or whitespace")
        return v


class NoteDocument(BaseModel, frozen=True, extra="forbid"):
    """Fully parsed meeting notes document."""

    file_name: str
    sha256: str
    header: NoteHeader | None
    lines: list[NoteLine]
    char_count: int

    @model_validator(mode="after")
    def lines_strictly_increasing(self) -> "NoteDocument":
        seen: set[int] = set()
        prev = 0
        for line in self.lines:
            if line.number in seen:
                raise ValueError(f"Duplicate line number {line.number}")
            if line.number <= prev:
                raise ValueError(
                    f"Line numbers must be strictly increasing; "
                    f"got {line.number} after {prev}"
                )
            seen.add(line.number)
            prev = line.number
        return self


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalise(raw: str) -> str:
    """Normalise to LF, strip trailing whitespace per line, remove trailing blanks."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [ln.rstrip() for ln in lines]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _decode(content: bytes | str) -> str:
    """Decode bytes to str, stripping a UTF-8 BOM if present."""
    if isinstance(content, bytes):
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NoteFormatError(f"File is not valid UTF-8: {exc}") from exc
    return content


def parse_notes(
    content: bytes | str,
    file_name: str,
    *,
    auto_number: bool = False,
) -> NoteDocument:
    """Parse meeting notes content into a NoteDocument.

    Args:
        content: Raw file bytes or already-decoded string.
        file_name: Original file name (used in the document, not for I/O).
        auto_number: When True, unnumbered non-empty body lines are numbered 1..n.

    Raises:
        NoteFormatError: On any format or encoding violation.
    """
    raw_str = _decode(content)

    if isinstance(content, bytes):
        byte_len = len(content)
    else:
        byte_len = len(content.encode("utf-8"))

    if byte_len == 0:
        raise NoteFormatError("File is empty")
    if byte_len > MAX_FILE_SIZE_BYTES:
        raise NoteFormatError(
            f"File is {byte_len} bytes; maximum allowed is {MAX_FILE_SIZE_BYTES} bytes (200 KB)"
        )

    normalised = _normalise(raw_str)
    raw_lines = normalised.split("\n") if normalised else []

    if len(raw_lines) > MAX_LINES:
        raise NoteFormatError(
            f"File has {len(raw_lines)} lines; maximum allowed is {MAX_LINES}"
        )

    sha256 = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    char_count = len(normalised)

    # Identify non-empty lines for header detection
    non_empty = [(i, ln) for i, ln in enumerate(raw_lines) if ln.strip()]

    header: NoteHeader | None = None
    body_start_idx = 0

    if non_empty:
        first_phys_idx, first_line = non_empty[0]
        m = _HEADER_RE.match(first_line)
        if m:
            meeting_label = m.group("meeting_label").strip()
            team_label = m.group("team_label").strip()
            date_str = m.group("meeting_date").strip()
            try:
                meeting_date = date.fromisoformat(date_str)
            except ValueError as exc:
                raise NoteFormatError(
                    f"Invalid date in header: {date_str!r}"
                ) from exc
            header = NoteHeader(
                meeting_label=meeting_label,
                team_label=team_label,
                meeting_date=meeting_date,
            )
            body_start_idx = first_phys_idx + 1

    # Parse body lines
    parsed_lines: list[NoteLine] = []
    bad_lines: list[int] = []
    auto_counter = 0

    for phys_idx, raw_line in enumerate(raw_lines):
        if phys_idx < body_start_idx:
            continue
        if not raw_line.strip():
            continue

        m = _LINE_RE.match(raw_line)
        if m:
            auto_counter += 1
            parsed_lines.append(
                NoteLine(number=int(m.group("number")), text=m.group("text").strip())
            )
        elif auto_number:
            auto_counter += 1
            parsed_lines.append(NoteLine(number=auto_counter, text=raw_line.strip()))
        else:
            bad_lines.append(phys_idx + 1)  # 1-based physical line number

    if bad_lines:
        raise NoteFormatError(
            f"Lines do not match '<number>. <text>' format "
            f"(physical line numbers: {bad_lines})"
        )

    # Validate strictly increasing numbers (also checked in model_validator but
    # we want a NoteFormatError, not a pydantic ValidationError)
    seen: set[int] = set()
    prev = 0
    for nl in parsed_lines:
        if nl.number in seen:
            raise NoteFormatError(f"Duplicate line number {nl.number}")
        if nl.number <= prev:
            raise NoteFormatError(
                f"Line numbers must be strictly increasing; got {nl.number} after {prev}"
            )
        seen.add(nl.number)
        prev = nl.number

    return NoteDocument(
        file_name=file_name,
        sha256=sha256,
        header=header,
        lines=parsed_lines,
        char_count=char_count,
    )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def read_notes_file(path: Path) -> NoteDocument:
    """Read a .txt notes file from disk and parse it.

    Logs a tool_call event with metadata only -- never the note text.

    Raises:
        NoteFormatError: If the file extension is not .txt or parsing fails.
        OSError: If the file cannot be read.
    """
    if path.suffix.lower() != ".txt":
        raise NoteFormatError(
            f"Only .txt files are accepted; got {path.suffix!r} ({path.name})"
        )

    content = path.read_bytes()
    doc = parse_notes(content, path.name)

    log_event(
        "tool_call",
        {
            "tool": "read_notes_file",
            "file_name": path.name,
            "sha256": doc.sha256,
            "line_count": len(doc.lines),
        },
    )
    return doc


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def render_for_prompt(doc: NoteDocument) -> str:
    """Render note lines wrapped in safe delimiters for LLM prompts.

    Delimiter breakout is neutralised: '<<<' becomes '< < <' and '>>>'
    becomes '> > >' inside note text, so note content can never close or
    reopen the block.
    """
    rendered_lines: list[str] = []
    for nl in doc.lines:
        safe_text = _RAW_CLOSE_RE.sub("> > >", _RAW_OPEN_RE.sub("< < <", nl.text))
        rendered_lines.append(f"{nl.number}. {safe_text}")
    body = "\n".join(rendered_lines)
    return f"<<<NOTES\n{body}\nNOTES>>>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def verify_quote(doc: NoteDocument, quote: str, line: int | None = None) -> bool:
    """Return True if quote appears in the document (or a specific line).

    Matching is whitespace-collapsed and case-insensitive.
    Quotes shorter than MIN_QUOTE_LENGTH characters are always False.
    """
    if len(quote.strip()) < MIN_QUOTE_LENGTH:
        return False

    def _collapse(s: str) -> str:
        return " ".join(s.lower().split())

    collapsed_quote = _collapse(quote)

    if line is not None:
        target = get_line(doc, line)
        if target is None:
            return False
        return collapsed_quote in _collapse(target.text)

    for nl in doc.lines:
        if collapsed_quote in _collapse(nl.text):
            return True
    return False


def get_line(doc: NoteDocument, number: int) -> NoteLine | None:
    """Return the NoteLine with the given number, or None."""
    for nl in doc.lines:
        if nl.number == number:
            return nl
    return None


def line_numbers(doc: NoteDocument) -> frozenset[int]:
    """Return the set of all line numbers present in the document."""
    return frozenset(nl.number for nl in doc.lines)
