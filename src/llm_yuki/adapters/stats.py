"""Compilation statistics: entities/concepts/sources/links + cost/timing rollup, rendered as a report (D24).

Extends the D19 ``cost_ledger.jsonl`` (token/wall-clock cost only) with the rest of what one compile run
produces: how many ``Claim``/``Concept``/``Source`` pages exist and how many are new this run, how the six
link-bearing frontmatter fields (proposal ARCHITECTURE.md §5.1) grew, how many LLM calls were made and what
they cost per component, and — cross-referenced from the ``ErrorBook`` (§4.4) — how many lint findings this
run discovered/closed. ``compute_run_stats`` produces a :class:`RunStats` snapshot; ``write_stats_report``
renders it to ``pipeline-state/stat_<timestamp>.md``, one file per ``compile`` invocation (the CLI's
``--batch-id`` is the natural "one run" unit — see ``cli.py``).

Read-only with respect to the bundle and ``cost_ledger.jsonl``: this module never writes to ``bundle/`` (that
stays the ``Writer``'s exclusive job, AGENTS.md §4) and never appends to the cost ledger. It reads pages back
through the ``Writer`` port (``read_claim``/``read_concept``/``read_source``), but must glob the bundle
directory directly to discover *which* slugs belong to which core type — ``Writer.list_pages()`` returns all
three types flattened together, with no way to tell them apart, and the port has no typed-listing method.
The three subdirectory names below are the stable D23 bundle layout (also hardcoded in
``adapters/writers/markdown_writer.py``, the only ``Writer`` implementation this POC validates, D16) — not a
private implementation detail reached into, but a documented on-disk contract (proposal ARCHITECTURE.md §4.4).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from llm_yuki.adapters.cost_ledger import CostEvent, JsonlCostLedger
from llm_yuki.domain.error_book import ErrorBook
from llm_yuki.ports.writer import Writer

_CLAIMS_DIR = "claims"
_CONCEPTS_DIR = "concepts"
_SOURCES_DIR = "sources"

_LINK_FIELDS: tuple[str, ...] = (
    "Claim.related_concepts",
    "Claim.contradicted_by",
    "Claim.source_ref",
    "Concept.key_facts",
    "Concept.related_pages",
    "Concept.related_sources",
    "Source.produced_claims",
    "Source.produced_concepts",
    "Source.related_pages",
)
"""Every link-bearing frontmatter field across the three core types (proposal ARCHITECTURE.md §1.2/§1.3/§1.5,
§5.1). ``Claim.source_ref`` counts as present/absent (it is a single pointer, not a list) — every other field
counts its list length. Deliberately excludes body-only wikilinks and ``index.md`` entries: both are
deterministically re-derived by the ``Writer`` from these same frontmatter fields (§2.3.1/§5.4), so counting
them separately would double-count the same underlying edges, not surface new information.
"""

_PHASE_BY_COMPONENT: dict[str, str] = {
    "Extractor": "Phase 1 (parallel — SelectPages/CompileWikiPages, D12)",
    "Merger": "Phase 2 (sequential)",
    "Validator": "Phase 2 (sequential)",
    "Fixer": "Periodic (every N batches, §4.3)",
}
"""Which Algorithm 1 phase each component's cost-ledger calls belong to — inferred from where
``domain/pipeline.py``'s ``Orchestrator`` actually calls each one (``Extractor`` only inside
``_run_phase1``'s ``ThreadPoolExecutor``; ``Merger``/``Validator`` only inside the sequential ``_run_phase2``;
``Fixer.llm_periodic_fix`` only from the periodic-fix branch at the end of ``run_batch``), not a separate
instrumentation point — nothing new to keep in sync with the pipeline's actual control flow.
"""


@dataclass
class BundleSnapshot:
    """A point-in-time read of ``bundle_dir``'s page slugs and link-field totals.

    Two snapshots (before/after one ``compile`` invocation) are diffed by :func:`compute_run_stats` to tell
    "created/added in this run" apart from "already existed". Cheap enough to take before *and* after every
    run (POC scale, per §6.1's Minimal Scope) — no incremental tracking needed.
    """

    claim_slugs: frozenset[str] = field(default_factory=frozenset)
    concept_slugs: frozenset[str] = field(default_factory=frozenset)
    source_slugs: frozenset[str] = field(default_factory=frozenset)
    link_field_totals: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_LINK_FIELDS, 0))


class PageStats(BaseModel):
    """Page counts for one core type, as of the *end* of one run."""

    total: int
    new_this_run: int


class LinkFieldStats(BaseModel):
    """One link-bearing frontmatter field's total and this-run growth."""

    field: str
    total: int
    added_this_run: int


class ComponentStats(BaseModel):
    """Cost-ledger events for this run, grouped by component (the ``stage`` string's dotted prefix)."""

    component: str
    phase_label: str
    call_count: int
    tokens_in: int
    tokens_out: int
    wall_clock_ms: float
    pct_of_e2e: float | None = None


class ErrorTypeRunStats(BaseModel):
    """One §4.1 error type's Error Book activity, cross-referenced against this run's ``batch_id``."""

    error_type: str
    discovered_this_run: int
    closed_this_run: int
    open_total: int


class RunStats(BaseModel):
    """Everything one ``compile`` invocation produced — the input to :func:`render_stats_report`."""

    batch_id: int
    generated_at: str
    e2e_wall_clock_ms: float
    claims: PageStats
    concepts: PageStats
    sources: PageStats
    link_fields: list[LinkFieldStats]
    components: list[ComponentStats]
    llm_call_count: int
    tokens_in_total: int
    tokens_out_total: int
    errors: list[ErrorTypeRunStats]

    @property
    def total_links(self) -> int:
        """Sum of every link field's current total — one number for the executive summary."""
        return sum(f.total for f in self.link_fields)


def snapshot_bundle(bundle_dir: Path, writer: Writer) -> BundleSnapshot:
    """Read ``bundle_dir``'s current page slugs and link-field totals through ``writer``'s read-back methods.

    Call once before and once after ``Orchestrator.run_batch`` — see module docstring. Missing pages
    (``read_*`` returning ``None`` for a slug found on disk — a race is not expected within one single-
    threaded CLI invocation, but a partially-written page from a crashed prior run is plausible) are silently
    skipped rather than raising: a stats snapshot must never be able to abort a compile run.
    """
    claim_slugs = _slugs_in(bundle_dir, _CLAIMS_DIR)
    concept_slugs = _slugs_in(bundle_dir, _CONCEPTS_DIR)
    source_slugs = _slugs_in(bundle_dir, _SOURCES_DIR)

    totals = dict.fromkeys(_LINK_FIELDS, 0)
    for slug in claim_slugs:
        claim = writer.read_claim(slug)
        if claim is None:
            continue
        totals["Claim.related_concepts"] += len(claim.related_concepts)
        totals["Claim.contradicted_by"] += len(claim.contradicted_by)
        totals["Claim.source_ref"] += 1 if claim.source_ref else 0
    for slug in concept_slugs:
        concept = writer.read_concept(slug)
        if concept is None:
            continue
        totals["Concept.key_facts"] += len(concept.key_facts)
        totals["Concept.related_pages"] += len(concept.related_pages)
        totals["Concept.related_sources"] += len(concept.related_sources)
    for slug in source_slugs:
        source = writer.read_source(slug)
        if source is None:
            continue
        totals["Source.produced_claims"] += len(source.produced_claims)
        totals["Source.produced_concepts"] += len(source.produced_concepts)
        totals["Source.related_pages"] += len(source.related_pages)

    return BundleSnapshot(
        claim_slugs=frozenset(claim_slugs),
        concept_slugs=frozenset(concept_slugs),
        source_slugs=frozenset(source_slugs),
        link_field_totals=totals,
    )


def _slugs_in(bundle_dir: Path, type_dir: str) -> set[str]:
    directory = bundle_dir / type_dir
    if not directory.exists():
        return set()
    return {p.stem for p in directory.glob("*.md") if p.stem != "index"}


def compute_run_stats(
    *,
    batch_id: int,
    bundle_dir: Path,
    writer: Writer,
    cost_ledger: JsonlCostLedger,
    error_book: ErrorBook,
    e2e_wall_clock_ms: float,
    before: BundleSnapshot,
) -> RunStats:
    """Aggregate one run's statistics: bundle growth (``before`` vs. a fresh snapshot) + this ``batch_id``'s
    cost-ledger events + this ``batch_id``'s Error Book activity.

    ``before`` must be a :func:`snapshot_bundle` taken immediately before ``Orchestrator.run_batch`` — the
    caller (``cli.py``) owns that timing since this function only knows how to diff two snapshots, not when
    a run started. ``e2e_wall_clock_ms`` is likewise the caller's stopwatch around the whole
    ``run_batch`` call, not reconstructed from ``cost_ledger`` timestamps (Phase 1 runs several stage calls
    concurrently, so their timestamps overlap — summing durations is meaningful, but subtracting min/max
    timestamps is not).
    """
    after = snapshot_bundle(bundle_dir, writer)

    claims = PageStats(total=len(after.claim_slugs), new_this_run=len(after.claim_slugs - before.claim_slugs))
    concepts = PageStats(total=len(after.concept_slugs), new_this_run=len(after.concept_slugs - before.concept_slugs))
    sources = PageStats(total=len(after.source_slugs), new_this_run=len(after.source_slugs - before.source_slugs))
    link_fields = [
        LinkFieldStats(
            field=name,
            total=after.link_field_totals[name],
            added_this_run=after.link_field_totals[name] - before.link_field_totals.get(name, 0),
        )
        for name in _LINK_FIELDS
    ]

    events = [e for e in cost_ledger.read_events() if e.batch_id == batch_id]
    components = _component_stats(events, e2e_wall_clock_ms)
    llm_events = [e for e in events if e.tokens_in > 0 or e.tokens_out > 0]

    return RunStats(
        batch_id=batch_id,
        generated_at=datetime.now(UTC).isoformat(),
        e2e_wall_clock_ms=e2e_wall_clock_ms,
        claims=claims,
        concepts=concepts,
        sources=sources,
        link_fields=link_fields,
        components=components,
        llm_call_count=len(llm_events),
        tokens_in_total=sum(e.tokens_in for e in events),
        tokens_out_total=sum(e.tokens_out for e in events),
        errors=_error_stats(error_book, batch_id),
    )


def _component_stats(events: list[CostEvent], e2e_wall_clock_ms: float) -> list[ComponentStats]:
    grouped: dict[str, list[CostEvent]] = defaultdict(list)
    for event in events:
        grouped[event.stage.split(".", 1)[0]].append(event)

    stats = [
        ComponentStats(
            component=component,
            phase_label=_PHASE_BY_COMPONENT.get(component, "unknown"),
            call_count=len(group),
            tokens_in=sum(e.tokens_in for e in group),
            tokens_out=sum(e.tokens_out for e in group),
            wall_clock_ms=sum(e.wall_clock_ms for e in group),
            pct_of_e2e=(sum(e.wall_clock_ms for e in group) / e2e_wall_clock_ms * 100) if e2e_wall_clock_ms else None,
        )
        for component, group in grouped.items()
    ]
    stats.sort(key=lambda s: s.wall_clock_ms, reverse=True)
    return stats


def _error_stats(error_book: ErrorBook, batch_id: int) -> list[ErrorTypeRunStats]:
    by_type: dict[str, ErrorTypeRunStats] = {}
    for entry in error_book.entries:
        stat = by_type.setdefault(
            entry.error_type,
            ErrorTypeRunStats(error_type=entry.error_type, discovered_this_run=0, closed_this_run=0, open_total=0),
        )
        if entry.discovered_at_batch == batch_id:
            stat.discovered_this_run += 1
        if entry.closed_at_batch == batch_id:
            stat.closed_this_run += 1
        if entry.status == "open":
            stat.open_total += 1
    return sorted(by_type.values(), key=lambda s: s.error_type)


# -- Report rendering (§7.5) --------------------------------------------------------------------------------


def _fmt_ms(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.2f} s"


def _fmt_pct(pct: float | None) -> str:
    return "N/A" if pct is None else f"{pct:.1f}%"


def render_stats_report(stats: RunStats) -> str:
    """Render a :class:`RunStats` snapshot into the ``stat_<timestamp>.md`` Markdown report (§7.5)."""
    lines: list[str] = []
    w = lines.append

    w(f"# Compilation Statistics — batch {stats.batch_id}")
    w("")
    w(f"- **Batch ID**: {stats.batch_id}")
    w(f"- **E2E compile time**: {_fmt_ms(stats.e2e_wall_clock_ms)}")
    w(f"- **Report generated**: {stats.generated_at}")
    w("")

    w("## 1. Summary")
    w("")
    w(
        f"This run produced **{stats.claims.new_this_run}** new claim(s) "
        f"(of {stats.claims.total} total), **{stats.concepts.new_this_run}** new concept(s) "
        f"(of {stats.concepts.total} total), and **{stats.sources.new_this_run}** new source(s) "
        f"(of {stats.sources.total} total), adding **{sum(f.added_this_run for f in stats.link_fields)}** "
        f"link(s) (of {stats.total_links} total). It made **{stats.llm_call_count}** LLM call(s), "
        f"consuming **{stats.tokens_in_total + stats.tokens_out_total:,}** tokens "
        f"(in: {stats.tokens_in_total:,} / out: {stats.tokens_out_total:,}), "
        f"in {_fmt_ms(stats.e2e_wall_clock_ms)} end-to-end."
    )
    w("")

    w("## 2. Knowledge Graph Growth")
    w("")
    w("| Type | Total | New this run |")
    w("|---|---:|---:|")
    w(f"| Claims (entities) | {stats.claims.total} | {stats.claims.new_this_run} |")
    w(f"| Concepts | {stats.concepts.total} | {stats.concepts.new_this_run} |")
    w(f"| Sources | {stats.sources.total} | {stats.sources.new_this_run} |")
    w("")
    w(
        '> "Total" is the bundle\'s current page count for that type (this run plus every prior run '
        'against this `bundle_dir`); "New this run" is this run\'s contribution only.'
    )
    w("")

    w("## 3. Links (proposal ARCHITECTURE.md §5.1 frontmatter fields)")
    w("")
    w("| Field | Total | Added this run |")
    w("|---|---:|---:|")
    for f in stats.link_fields:
        w(f"| `{f.field}` | {f.total} | {f.added_this_run} |")
    w(f"| | **{stats.total_links}** | **{sum(f.added_this_run for f in stats.link_fields)}** |")
    w("")
    w(
        "> Body wikilinks and `index.md` entries are not counted separately — the `Writer` renders both "
        "deterministically from these same frontmatter fields (§2.3.1/§5.4), so they carry no additional "
        "information."
    )
    w("")

    w("## 4. LLM Usage")
    w("")
    w(
        f"**{stats.llm_call_count}** LLM call(s), tokens in **{stats.tokens_in_total:,}** / "
        f"out **{stats.tokens_out_total:,}** / total **{stats.tokens_in_total + stats.tokens_out_total:,}**"
        + (
            f" (avg {round((stats.tokens_in_total + stats.tokens_out_total) / stats.llm_call_count):,} tokens/call)"
            if stats.llm_call_count
            else ""
        )
        + "."
    )
    w("")
    w("## 5. Timing by Component")
    w("")
    if stats.components:
        w("| Component | Phase | Calls | Tokens in | Tokens out | Wall-clock | % of E2E |")
        w("|---|---|---:|---:|---:|---:|---:|")
        for c in stats.components:
            w(
                f"| {c.component} | {c.phase_label} | {c.call_count} | {c.tokens_in:,} | {c.tokens_out:,} "
                f"| {_fmt_ms(c.wall_clock_ms)} | {_fmt_pct(c.pct_of_e2e)} |"
            )
        w("")
        if any(c.component == "Extractor" for c in stats.components):
            w(
                "> `Extractor` runs in Phase 1, in parallel across passages (D12) — its cumulative wall-clock "
                "and % of E2E can legitimately exceed 100%, reflecting concurrency, not an error."
            )
            w("")
    else:
        w("_No cost-ledger events recorded for this batch._")
        w("")

    if stats.errors:
        w("## 6. Error Book Cross-Reference (§4.1)")
        w("")
        w("| Error type | Discovered this run | Closed this run | Currently open |")
        w("|---|---:|---:|---:|")
        for e in stats.errors:
            w(f"| {e.error_type} | {e.discovered_this_run} | {e.closed_this_run} | {e.open_total} |")
        w("")

    return "\n".join(lines)


def report_filename(stats: RunStats) -> str:
    """``stat_<timestamp>_batch<N>.md`` — ``<timestamp>`` from ``generated_at``, UTC, filename-safe."""
    dt = datetime.fromisoformat(stats.generated_at)
    return f"stat_{dt.strftime('%Y%m%dT%H%M%SZ')}_batch{stats.batch_id}.md"


def write_stats_report(stats: RunStats, pipeline_state_root: Path | str) -> Path:
    """Render and write ``stats`` to ``<pipeline_state_root>/stat_<timestamp>.md``. Returns the path written.

    Lives alongside ``error_book.yaml``/``cost_ledger.jsonl`` — pipeline meta-state, not OKF bundle content
    (same reasoning as §7.1/§4.4), so it is not subject to D6's conformance validation.
    """
    root = Path(pipeline_state_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / report_filename(stats)
    path.write_text(render_stats_report(stats), encoding="utf-8")
    return path
