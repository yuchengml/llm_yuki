"""Default natural-paragraph passage splitter (D11) — domain-agnostic, deterministic, no I/O.

Proposal decision D11: extraction granularity uses the document's natural paragraph/concept units, not
fixed-length chunk splitting. The actual per-corpus splitting rule is delegated to a future domain skill
(D3) — this is the core pipeline's own baseline default, used until a skill overrides it. It only ever needs
to guarantee each passage is a semantically complete natural unit; it does not need to understand any
corpus-specific structure.
"""

from __future__ import annotations

import re

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def split_into_natural_paragraphs(text: str) -> list[str]:
    """Split ``text`` into natural paragraphs: blank-line-separated, non-empty, whitespace-trimmed chunks.

    Not a fixed-length chunker (D11's explicit exclusion) — a document with no blank-line breaks at all
    becomes exactly one passage (the whole document), which still satisfies D11: a single semantically
    complete natural unit, just a large one.
    """
    paragraphs = (paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(text))
    return [paragraph for paragraph in paragraphs if paragraph]
