"""M4 — the end-to-end pipeline orchestrator package.

A thin composition layer that runs the M2 discovery stage
(`discovery/run.py`) and the M3 scoring/alerting stage (`scoring/run.py`)
back to back under one run id. It owns no store writes, no LLM call, and no
ntfy call of its own — see `pipeline/run.py` and
`specs/004-orchestrator-run/contracts/pipeline.md`.
"""
