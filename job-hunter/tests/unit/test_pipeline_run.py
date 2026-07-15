"""T003 [Foundational] — `PipelineSummary` shape (data-model.md).

Written first (Constitution VII) — expected to fail until T004 implements
`jobhunter.pipeline.run.PipelineSummary`. Asserts the aggregate merely composes
the two existing stage summaries under one shared run id: its `run_id` equals
both nested summaries' `run_id`, and its `discovery`/`scoring` slots hold the
exact `RunSummary`/`ScoreRunSummary` objects handed in — never recomputed or
copied field by field (data-model.md "Composition rule").
"""

from __future__ import annotations

import logging

from jobhunter.discovery.run import RunSummary
from jobhunter.pipeline.run import PipelineSummary, format_pipeline_summary
from jobhunter.scoring.run import ScoreRunSummary


def test_pipeline_summary_composes_both_stages_under_one_run_id():
    discovery = RunSummary(fetched=5, new=3, seen=1, skipped=1, run_id="run-abc")
    scoring = ScoreRunSummary(filtered_out=1, scored=2, alerted=1, run_id="run-abc")

    summary = PipelineSummary(run_id="run-abc", discovery=discovery, scoring=scoring)

    # Composed, not recomputed: the exact stage objects are held as-is.
    assert summary.discovery is discovery
    assert summary.scoring is scoring
    # One shared correlation id across the aggregate and both nested summaries.
    assert summary.run_id == "run-abc"
    assert summary.run_id == summary.discovery.run_id == summary.scoring.run_id


def test_pipeline_summary_reads_through_nested_counts_unmutated():
    discovery = RunSummary(fetched=5, new=3, seen=1, skipped=1, run_id="run-xyz")
    scoring = ScoreRunSummary(filtered_out=1, scored=2, alerted=1, run_id="run-xyz")

    summary = PipelineSummary(run_id="run-xyz", discovery=discovery, scoring=scoring)

    # Nested fields are visible unchanged through the aggregate.
    assert summary.discovery.new == 3
    assert summary.discovery.fetched == 5
    assert summary.scoring.scored == 2
    assert summary.scoring.alerted == 1


# --------------------------------------------------------------------------- #
# T005 / T006 [US1] — composition contract for `run_pipeline`.
#
# Both stub the two stage runners at their import site in `pipeline.run`
# (`jobhunter.pipeline.run.run_discovery` / `.run_scoring`) so no live
# network/LLM/store is touched (contracts/pipeline.md). Written first — they
# fail on the missing `run_pipeline` import until T008. `run_pipeline` is
# imported locally so this module's T003 tests still collect and pass.
# --------------------------------------------------------------------------- #

# Opaque sentinels: `run_pipeline` only forwards these to the stubbed stages,
# so their concrete type is irrelevant to the composition contract.
_PROFILE = object()
_PREFS = object()


def test_calls_discovery_before_scoring_and_scores_even_when_empty(monkeypatch):
    """C1 + C4: discovery runs before scoring, and scoring runs unconditionally
    — even when discovery returned zero new jobs (pre-existing `state='new'`
    jobs must still be scored)."""
    from jobhunter.pipeline.run import run_pipeline

    calls: list[str] = []

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        calls.append("discovery")
        return RunSummary(new=0, run_id="-")  # zero new jobs this run

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        calls.append("scoring")
        return ScoreRunSummary(run_id="-")

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    summary = run_pipeline([], _PROFILE, _PREFS)

    assert calls == ["discovery", "scoring"]  # order + scoring ran despite new=0
    assert isinstance(summary, PipelineSummary)


def test_forwards_sources_flags_and_shared_profile_prefs(monkeypatch):
    """C1: `sources` reach discovery; `rerank`/`provider` reach scoring; both
    stages receive the *same* `profile`/`prefs` objects."""
    from jobhunter.pipeline.run import run_pipeline

    seen: dict[str, dict] = {}

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        seen["discovery"] = {"sources": sources, "profile": profile, "prefs": prefs}
        return RunSummary(run_id="-")

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        seen["scoring"] = {
            "profile": profile,
            "prefs": prefs,
            "rerank": rerank,
            "provider": provider,
        }
        return ScoreRunSummary(run_id="-")

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    sources = [object(), object()]
    provider = object()

    run_pipeline(sources, _PROFILE, _PREFS, rerank=True, provider=provider)

    # sources go to discovery only; rerank/provider go to scoring only.
    assert seen["discovery"]["sources"] is sources
    assert seen["scoring"]["rerank"] is True
    assert seen["scoring"]["provider"] is provider
    # both stages get the identical profile/prefs objects.
    assert seen["discovery"]["profile"] is _PROFILE is seen["scoring"]["profile"]
    assert seen["discovery"]["prefs"] is _PREFS is seen["scoring"]["prefs"]


def test_discovery_source_failure_does_not_stop_scoring(monkeypatch):
    """T011 [US2] — C3 + C4: a discovery summary carrying a `source_failures`
    entry does not abort the run. `run_pipeline` still invokes `run_scoring`
    and returns normally — the isolated failure is reported inside the nested
    summary, never re-raised."""
    from jobhunter.pipeline.run import run_pipeline

    scoring_calls: list[bool] = []

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        return RunSummary(
            new=0,
            attempted_sources=["jsearch", "adzuna"],
            source_failures={"adzuna": "HTTP 429 rate limited"},
            run_id="-",
        )

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        scoring_calls.append(True)
        return ScoreRunSummary(run_id="-")

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    summary = run_pipeline([], _PROFILE, _PREFS)  # must not raise

    assert scoring_calls == [True]  # scoring ran despite the source failure
    assert summary.discovery.source_failures == {"adzuna": "HTTP 429 rate limited"}


def test_run_id_is_reused_from_obs_not_minted(monkeypatch):
    """T014 [US3] — C2: `run_pipeline` mints no id. It reads
    `obs.current_run_id()` for `PipelineSummary.run_id`, which equals both
    nested summaries' `run_id` (both stages already reuse the same id)."""
    from jobhunter.pipeline.run import run_pipeline

    # Pin the shared correlation id at its single source of truth.
    monkeypatch.setattr("jobhunter.pipeline.run.obs.current_run_id", lambda: "sharedid42")

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        return RunSummary(run_id="sharedid42")

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        return ScoreRunSummary(run_id="sharedid42")

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    summary = run_pipeline([], _PROFILE, _PREFS)

    # The aggregate id is exactly the one obs handed out — not a fresh uuid.
    assert summary.run_id == "sharedid42"
    assert summary.run_id == summary.discovery.run_id == summary.scoring.run_id


def test_emits_one_combined_summary_log_line_counts_only(monkeypatch, caplog):
    """T015 [US3] — C6 + Constitution VIII: exactly one combined end-of-run
    summary line carrying both stages' headline counts under the run id, and
    logging counts/metadata only — never a job/profile/prefs payload."""
    from jobhunter.pipeline.run import run_pipeline

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        return RunSummary(
            fetched=42, new=18, seen=22, skipped=2,
            source_failures={"adzuna": "HTTP 429"}, run_id="-",
        )

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        # A payload that must NOT appear in the summary log line.
        return ScoreRunSummary(
            filtered_out=6, scored=12, alerted=2, reranked=0,
            top_job_title="Secret Staff Role at Acme", run_id="-",
        )

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    with caplog.at_level(logging.INFO, logger="jobhunter.pipeline"):
        run_pipeline([], _PROFILE, _PREFS)

    summary_lines = [
        r.getMessage() for r in caplog.records if "run complete" in r.getMessage()
    ]
    assert len(summary_lines) == 1  # exactly one combined line
    msg = summary_lines[0]
    # both stages' headline counts are present under the run id.
    for token in ("new=18", "seen=22", "skipped=2", "failures=1",
                  "filtered_out=6", "scored=12", "alerted=2", "reranked=0"):
        assert token in msg
    # counts/metadata only — no job payload leaked.
    assert "Secret Staff Role at Acme" not in msg


def test_dry_run_flag_reaches_both_stages(monkeypatch):
    """T018 [US4] — C8: `dry_run=True` propagates to both `run_discovery` and
    `run_scoring`."""
    from jobhunter.pipeline.run import run_pipeline

    seen: dict[str, bool] = {}

    def fake_discovery(sources, profile, prefs, *, dry_run=False):
        seen["discovery"] = dry_run
        return RunSummary(run_id="-")

    def fake_scoring(profile, prefs, *, dry_run=False, rerank=False, provider=None):
        seen["scoring"] = dry_run
        return ScoreRunSummary(run_id="-")

    monkeypatch.setattr("jobhunter.pipeline.run.run_discovery", fake_discovery)
    monkeypatch.setattr("jobhunter.pipeline.run.run_scoring", fake_scoring)

    run_pipeline([], _PROFILE, _PREFS, dry_run=True)

    assert seen["discovery"] is True
    assert seen["scoring"] is True


def test_dry_run_render_annotates_header_normal_run_does_not():
    """T020 [US4] — the combined summary is annotated under `dry_run` to make
    clear the run wrote nothing and alerted no one; a normal run is not."""
    summary = PipelineSummary(
        run_id="r1",
        discovery=RunSummary(fetched=1, new=1, run_id="r1"),
        scoring=ScoreRunSummary(scored=1, run_id="r1"),
    )

    dry = format_pipeline_summary(summary, dry_run=True)
    normal = format_pipeline_summary(summary)

    assert "dry run — no writes, no alerts" in dry.splitlines()[0]
    assert "dry run" not in normal
    # the counts block is identical either way — only the header differs.
    assert dry.splitlines()[1:] == normal.splitlines()[1:]
