# Passage Splitting (D11)

Module: `domain/passage_splitter.py`. One function, no class, no I/O:

```python
def split_into_natural_paragraphs(text: str) -> list[str]:
    paragraphs = (paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(text))
    return [paragraph for paragraph in paragraphs if paragraph]
```

Where `_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")`.

## What it does

Splits on one-or-more blank lines (any run of whitespace containing at least two newlines), trims surrounding
whitespace from each resulting chunk, and drops any chunk that's empty after trimming. That's the entire
algorithm — no sentence segmentation, no semantic clustering, no length-based splitting.

| Input | Output |
|---|---|
| `"First.\n\nSecond."` | `["First.", "Second."]` |
| `"First.\n\n\n\nSecond."` (multiple blank lines) | `["First.", "Second."]` (collapsed to one break) |
| `"Just one paragraph,\nno blank line."` | `["Just one paragraph,\nno blank line."]` — the whole text, one entry |
| `"  Trim me.  \n\n  Me too.  "` | `["Trim me.", "Me too."]` |
| `""` or `"   \n\n   "` | `[]` |

## Why this is the extraction unit, not a fixed-length chunk

D11 decided extraction granularity should be natural paragraph/concept units, explicitly *not* fixed-length
chunking — the proposal's reasoning is that chunk boundaries cut across semantic units, which damages both
`Claim.source_ref` provenance (D9's MUST 3: every Claim needs traceable provenance, and the provenance is only
as meaningful as the unit it points at) and contradiction detection. A natural paragraph is assumed to be a
semantically complete unit; a fixed 500-character chunk is not.

This function is the **default** implementation of that idea, not the only possible one. The proposal
explicitly delegates the actual per-corpus splitting rule to a future domain skill (D3) — "段落的實際切法交
給各自的 skill 決定,core pipeline 只保證抽取單位是語意完整的自然單位" (the actual paragraph-splitting method
is delegated to each domain's skill; the core pipeline only guarantees the extraction unit is a semantically
complete natural unit). Since the skill-extension mechanism (`deepagents`) is not yet built or verified
(`TODO.md` B-1), this blank-line splitter is what the core pipeline falls back to — a reasonable, corpus-agnostic
baseline that at least satisfies "not a fixed-length chunker," even if it isn't as smart as a domain-aware
splitter could eventually be.

## Where it's called

Only from `Orchestrator._collect_passages` (`domain/pipeline.py`):

```python
def _collect_passages(self) -> list[_Passage]:
    passages: list[_Passage] = []
    for ref in self._connector.list_sources():
        document = self._connector.read_source(ref)
        for index, text in enumerate(split_into_natural_paragraphs(document.text)):
            passages.append(_Passage(document_slug=ref.id, index=index, text=text))
    return passages
```

Each resulting passage carries `document_slug` (the owning source's id) and `index` (its position among that
source's paragraphs, `0`-based) — both are needed later to anchor `Claim.source_ref` deterministically (see
`pipeline-overview.md`'s "Deterministic overrides LLM" section) and to route the passage through D12's Phase
1/Phase 2 split correctly.

`Connector.read_source` itself does no splitting — `TxtFileConnector` (`adapters/connectors/txt_file_connector.py`)
reads a document's entire `.txt` body as one `Document.text` string; the splitting happens one layer up, in
the `Orchestrator`, so any future `Connector` implementation (a different file format, a network source) gets
the same paragraph-splitting behavior for free without having to implement it itself.

## Backward compatibility with single-passage documents

Because a document with no blank-line breaks becomes exactly one passage (the whole text), every pre-existing
test fixture and Raw Source written before this splitter existed continues to behave identically — this is
not a coincidence, it's why the fallback case (`len(paragraphs) == 0` never happens for non-empty input;
`len(paragraphs) == 1` for single-paragraph input) was chosen deliberately when this was implemented.
