"""Line-preserving flat text record model shared by the .MSK and .sch readers.

Design rule for this whole project: a parser must never lose a byte it did not
understand.  So every fixture is split into *logical records* that each keep
their exact original text (`raw`), including the line terminator.  A writer that
changes nothing re-emits the same bytes; a writer that changes one record
regenerates only that record.

Logical records exist because DSCH splits records across physical lines:
`Clk24H00.sch` contains

    REC(40,-25,0,0,
    )

only the paren-balanced kinds are joined, so free text (`HELP ...`, `VLG ...`,
`#labels`) is never accidentally swallowed.
"""

from __future__ import annotations

import re

#: record kinds whose content is parenthesised and may wrap across lines
PAREN_KINDS = {
    "REC", "BB", "ZOOM", "LIG", "PIN", "CNC", "RLCR", "RLCL", "RLCC",
}
_KIND_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)")


def detect_eol(text: str) -> str:
    """Return the line ending used by `text` (defaults to ``\\r\\n``)."""
    i = text.find("\n")
    if i > 0 and text[i - 1] == "\r":
        return "\r\n"
    return "\n" if i >= 0 else "\r\n"


class Record:
    """One logical record: its keyword, its verbatim text, and parsed fields."""

    __slots__ = ("kind", "raw", "data")

    def __init__(self, kind: str, raw: str, data: dict | None = None):
        self.kind = kind
        self.raw = raw
        self.data = data or {}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Record({self.kind!r}, {self.body[:40]!r})"

    @property
    def body(self) -> str:
        """Record text without its trailing line terminator."""
        return self.raw.rstrip("\r\n")

    def __str__(self) -> str:
        return self.body


def split_records(text: str) -> list[Record]:
    """Split file text into logical records, preserving exact bytes in `raw`."""
    lines = text.splitlines(keepends=True)
    records: list[Record] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        i += 1
        body = raw.rstrip("\r\n")
        m = _KIND_RE.match(body.strip())
        kind = m.group(1).upper() if m else body.strip()[:1] or ""
        if kind in PAREN_KINDS:
            while raw.count("(") > raw.count(")") and i < n:
                raw += lines[i]
                i += 1
        records.append(Record(kind, raw))
    return records


def join_records(records: list[Record], eol: str = "\r\n", final_eol: bool = True) -> str:
    """Re-emit records, fixing up missing terminators so output is well formed."""
    out = []
    for idx, rec in enumerate(records):
        raw = rec.raw
        if not raw.endswith(("\n", "\r")):
            last = idx == len(records) - 1
            if not last or final_eol:
                raw = raw + eol
        out.append(raw)
    return "".join(out)


def paren_body(body: str) -> str | None:
    """Return the text inside the first ``( ... )`` of a record body, or None."""
    start = body.find("(")
    end = body.rfind(")")
    if start < 0 or end <= start:
        return None
    return body[start + 1:end]
