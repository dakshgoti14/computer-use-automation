# capabilities/

This directory holds versioned, typed capability artifacts (see
`app/artifacts/schema.py`).

`member_savings_lookup.json` was produced by a genuine, LLM-driven
discovery session against the local demo application (Gemini
`gemini-3.5-flash`) - see `evidence/README.md` for the exact run and its
evidence. It is committed here so the repository is runnable end to end
without requiring every reviewer to hold a Gemini API key and re-run
discovery themselves; it is not a substitute for actually running discovery
yourself if you want to see the process live (`make discover` below), and a
fresh checkout is expected to be able to regenerate it identically in
spirit (not byte-for-byte, since the model's exact choices vary run to
run).

```bash
make demo        # in one terminal
make discover    # in another - requires GEMINI_API_KEY in .env
```

See the root `README.md` ("Running genuine discovery") for details.

Do not hand-author or commit a fabricated version of this file claiming it
came from discovery - see `REPORT.md` ("Cuts") and
`tests/conftest.py` (`build_gold_artifact`) for how the test suite instead
uses an explicitly-labeled hand-built fixture, kept out of this directory,
to exercise the replay engine without requiring network access or an API
key.

Once generated, replay it deterministically (no LLM calls) with:

```bash
make replay
make replay-not-found
make replay-error
make benchmark
```
