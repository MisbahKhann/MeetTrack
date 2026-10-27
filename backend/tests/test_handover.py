"""Tests for HANDOVER.md completeness and security.

Verifies that the handover document:
- exists at the repo root
- contains all eight required section headings
- lists all 13 project steps
- contains no strings that look like real API keys
"""

import re
from pathlib import Path

import pytest

# HANDOVER.md lives at the repo root, two levels above meettrack/backend/
REPO_ROOT = Path(__file__).parent.parent.parent.parent
HANDOVER_PATH = REPO_ROOT / "HANDOVER.md"

REQUIRED_HEADINGS = [
    "Project",  # section 1
    "Status",  # section 2
    "Resume",  # section 3
    "Repository",  # section 4 (map)
    "Decisions",  # section 5
    "Known issues",  # section 6  (case-insensitive match)
    "Next step",  # section 7
    "Resume prompt",  # section 8
]

STEP_NAMES = [
    "scaffold",
    "CI",
    "database",
    "config",
    "input tools",
    "action_store",
    "orchestrator",
    "endpoint",
    "export",
    "frontend",
    "safety",
    "Docker",
    "demo",
]

# Patterns that look like real API keys -- must not appear in the file
API_KEY_PATTERNS = [
    r"AIza[0-9A-Za-z_\-]{35}",  # Google API key prefix
    r"gsk_[0-9A-Za-z]{40,}",  # Groq API key prefix
    r"sk-[0-9A-Za-z]{40,}",  # OpenAI-style key prefix
]


def test_handover_exists() -> None:
    assert HANDOVER_PATH.exists(), f"HANDOVER.md not found at {HANDOVER_PATH}"


@pytest.fixture()
def handover_text() -> str:
    return HANDOVER_PATH.read_text(encoding="utf-8")


def test_handover_has_all_section_headings(handover_text: str) -> None:
    lower = handover_text.lower()
    for heading in REQUIRED_HEADINGS:
        assert heading.lower() in lower, f"HANDOVER.md is missing a section containing {heading!r}"


def test_handover_lists_all_13_steps(handover_text: str) -> None:
    lower = handover_text.lower()
    for step in STEP_NAMES:
        assert step.lower() in lower, f"HANDOVER.md does not mention step keyword {step!r}"


def test_handover_no_api_keys(handover_text: str) -> None:
    for pattern in API_KEY_PATTERNS:
        match = re.search(pattern, handover_text)
        assert match is None, (
            f"HANDOVER.md appears to contain an API key matching /{pattern}/: "
            f"{match.group()[:10]}..."
        )
