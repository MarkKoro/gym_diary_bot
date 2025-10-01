from __future__ import annotations

import re


WHITESPACE_RE = re.compile(r"\s+")


def normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace and trim the string."""

    value = value.strip()
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", value)
