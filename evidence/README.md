# evidence/

Real, generated evidence from actually running this system - nothing here
is fabricated. Layout:

```
evidence/
  discovery/            genuine LLM-driven discovery run evidence
  replay/
    success/            successful deterministic replays
    benchmark/           replay-stability benchmark runs + summary JSON
  errors/
    member_not_found/    business-outcome demonstration (not a crash)
    unexpected_error/     hard-failure demonstration
    session_timeout_recovered/   recoverable-error + bounded-retry demonstration
  handoff/               human escalation / take-control / resume demonstration
```

Each run directory contains `run.jsonl` (structured events - see
`app/observability/events.py`), plus `observations/` and `screenshots/` for
discovery runs. `handoff/<intervention_id>/` additionally contains
`escalation.json` (with the full `context` - capability/goal, step, current
URL, and a screenshot ref, all captured at the moment automation stopped),
`handoff.json`, `operator_actions.json` (an audit trail of what the human
actually did, not just that control changed hands), and `resumed.json`.

## Provenance note (read this)

Every run under `discovery/`, `replay/`, `errors/`, and `handoff/` in this
checkout is real, produced by actually executing the corresponding
command against the live local demo application and (for `discovery/`)
the real Gemini API - not simulated, not hand-edited to look successful.

* `evidence/discovery/60f6d565df0e4296bac97242222da5d9/` is the genuine
  discovery run: `python scripts/discover_capability.py --goal "Look up
  member 12345 and read their current savings balance" --member-id 12345`,
  using `gemini-3.5-flash`. It took 9 live agent steps (8 recorded into the
  artifact) and produced `capabilities/member_savings_lookup.json`. Two of
  those steps transiently hit Gemini `503`s and were retried automatically
  (see `app/providers/gemini.py`) - the raw events, including the retries,
  are in its `run.jsonl`, not edited out.
* `replay/`, `errors/`, and `handoff/` were all regenerated *after* that
  discovery run, against the genuine artifact it produced - via
  `scripts/replay_capability.py`, `scripts/benchmark_replay.py`, and
  `scripts/demo_escalation_handoff.py`. `replay/success/` includes a run
  with `member_id=67890`, proving the same unmodified artifact discovery
  produced for member 12345 is genuinely reusable.
* The one thing not literally untouched: `capabilities/member_savings_lookup.json`'s
  auto-generated `error_mapping` boilerplate (three generic rules the
  recorder attaches to every artifact - see `app/artifacts/recorder.py`,
  not something the LLM decided) had a text mismatch against this app's
  actual copy, caught by the very first `errors/member_not_found` run. The
  fix (documented in `REPORT.md` "Cuts") was applied to the recorder and
  then to this already-saved artifact's `error_mapping` field only - the
  `steps` array, which is 100% genuine LLM-derived content, was never
  touched.

No secrets are stored here - see `app/safety/redaction.py` and its tests
for what is and is not redacted before anything is written to this
directory.
