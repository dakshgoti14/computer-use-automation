# Computer-Use Automation

A reusable backend integration layer for AI agents that operate applications
which don't expose reliable APIs. An LLM discovers how to do something once,
by actually driving a browser; that discovery is recorded as a typed,
versioned, parameterized **capability artifact**; every subsequent execution
of that capability replays deterministically, with **zero LLM calls**.

```
Natural-language goal
  -> Target application (local demo bank back office)
  -> LLM-driven observe -> decide -> act loop        (DISCOVERY, uses an LLM)
  -> Live UI interaction
  -> Successful execution
  -> Structured, reusable capability artifact
  -> Deterministic replay                            (REPLAY, never touches an LLM)
  -> Typed output + verified checkpoints
```

## 1. Overview

This repository demonstrates the full lifecycle above against a purpose-built
local banking back-office application. The flagship capability is:

> "Look up member 12345 and read their current savings balance."

Discovery is genuinely LLM-driven (Google Gemini, via a pluggable provider
interface). Replay is a completely separate, deterministic engine that
reads the artifact and drives the same browser surface with no model in the
loop - this is proven mechanically, not just asserted (see
["Replay zero-LLM guarantee"](#15-replay-zero-llm-guarantee)).

## Live demo (hosted, optional)

There is a public, hosted deployment for reviewers who want to trigger a
real replay from a browser without cloning the repo: **[link to be filled
in after deployment - see below]**.

The page (`/demo`) is not a JSON console - it's built to actually show the
system working:

* **A discovery filmstrip, server-rendered from real evidence.** The top of
  the page reads `evidence/discovery/*/run.jsonl` and its screenshots at
  request time and renders every step of the genuine Gemini-driven
  discovery run: the actual screen the model saw, the action it chose, and
  its own reasoning text - not a description of it, and not hardcoded HTML
  (`tests/integration/test_api.py::test_public_demo_page_renders_real_discovery_evidence`
  proves the page fails closed with a clear message if that evidence is
  ever missing, rather than silently rendering nothing).
* **A live, real replay.** Picking a member ID and clicking "Run live
  replay" launches an actual headless-Chromium session in the deployed
  container, against the actual demo bank app also running there, through
  the actual `ReplayEngine` - and now takes a real screenshot after every
  step (`ReplayEngine(capture_screenshots=True)`, opt-in and off by default
  elsewhere so an ordinary replay/benchmark run doesn't grow 8 unwanted
  PNGs), rendered as a second filmstrip next to the raw JSON result.
* **It does not run live discovery.** `PUBLIC_DEMO_MODE=true` disables
  `/runs/discover` outright (see `app/api/routes.py`) and the deployment
  has no `GEMINI_API_KEY` configured at all - a public endpoint that spends
  real LLM budget per click is not something to expose.
* **It's rate-limited and resource-capped.** The free hosting tier this
  targets caps the container at 512MB RAM; replay is capped per client
  (`PUBLIC_DEMO_RATE_LIMIT`, default 6 per 10 minutes) to keep the shared
  instance responsive. A 429 means "wait a few minutes" or "clone the repo
  and run `make replay` locally," not a bug.
* **First request after idle may be slow.** Free-tier web services on most
  hosts sleep after ~15 minutes of no traffic; the first request after that
  wakes the container and can take 30-60 seconds.

### Deploying it yourself

This targets [Render](https://render.com) (Docker-based, free web-service
tier, no credit card required for that tier):

1. Push this repository to GitHub (already done if you're reading this
   from the pushed repo).
2. On Render: **New +** -> **Blueprint** -> connect this GitHub repo.
   Render reads `render.yaml` at the repo root and provisions the service
   automatically - no manual environment variable entry needed, and
   critically, no `GEMINI_API_KEY` is set (see above for why that's
   deliberate, not an oversight).
3. Click **Apply**. The first build takes a few minutes (installing
   Playwright's Chromium is the slow part). This was tested locally with
   `docker build . && docker run` end to end, including a real replay
   inside a 512MB-capped container, before being documented here as
   working - see `Dockerfile` and `docker/start.sh`.
4. Once deployed, visit `https://<your-service-name>.onrender.com/demo`.

If you'd rather not use the Blueprint: **New +** -> **Web Service** ->
connect the repo -> Environment: **Docker** -> add the three env vars from
`render.yaml`'s `envVars` list manually, leaving `GEMINI_API_KEY` unset.

To run the same image locally instead of deploying it:

```bash
docker build -t cua-demo .
docker run -p 8000:8000 cua-demo
# then open http://127.0.0.1:8000/demo
```

## 2. Architecture

```
                     ┌────────────────────┐
   goal, params  --> │   DiscoveryEngine   │ --calls--> LLMProvider (Gemini)
                     │  (app/agent/loop.py)│
                     └─────────┬──────────┘
                               │ produces
                               v
                   CapabilityArtifact (JSON, versioned, typed)
                               │
                               │ loaded + validated by
                               v
                     ┌────────────────────┐
  artifact + params->│    ReplayEngine     │  <-- NEVER imports app.providers
                     │(app/replay/executor)│      or app.agent.loop/planner
                     └─────────┬──────────┘
                               │ drives
                               v
                     ┌────────────────────┐
                     │   SurfaceAdapter    │  <-- protocol; agent & replay
                     │     (protocol)      │      depend on this, not Playwright
                     └─────────┬──────────┘
                               │ implemented by
                               v
                     PlaywrightSurface (Chromium)
                               │
                               v
                     Local demo bank back office (demo_app/)
```

Cross-cutting layers used by both engines:

* **Safety policy** (`app/safety/`) - evaluated before every action, in
  both discovery and replay. Cannot be bypassed by the LLM or by an
  artifact.
* **Evidence / observability** (`app/observability/`) - structured JSONL
  events, screenshots, observation snapshots, all redacted before being
  written.
* **Escalation** (`app/escalation/`) - a state machine that pauses
  automation and hands the *same live browser session* to a human operator.

### Why this design

* **The LLM only discovers; it never operates.** Once a capability exists,
  running it again is a deterministic, auditable, replayable operation with
  no model variance, no token cost, and no risk of the model "deciding
  differently" on a production action. This is the single most important
  property this system is built to guarantee.
* **The artifact is the contract**, not the transcript. A human can read
  `capabilities/*.json` and know exactly what will happen, in what order,
  and what would make each step fail - independent of which LLM (or which
  prompt) discovered it.
* **A protocol between the engines and the browser** (`SurfaceAdapter`)
  means neither the agent loop nor the replay engine import Playwright.
  Swapping in a different UI-automation backend later is a new class, not a
  rewrite.

See `REPORT.md` for the full design rationale and tradeoffs.

## 3. Repository structure

```
app/
  api/            FastAPI routes + schemas + a tiny SQLite run registry
  agent/          Discovery loop, planner, prompts, typed action vocabulary
  browser/        SurfaceAdapter protocol, Playwright implementation,
                  locator strategies, the observation model
  artifacts/      Capability artifact schema, recorder, validator, store
  replay/         Deterministic ReplayEngine, checkpoints, typed results
  safety/         Policy, risk classifier, redaction
  escalation/     Human handoff state machine + session ownership
  observability/  Structured events, JSON logging, evidence writer
  providers/      LLMProvider protocol; Gemini + mock/test implementations
  config.py       Environment-driven settings (pydantic-settings)
  main.py         FastAPI app assembly

demo_app/         The target surface: a synthetic banking back office
capabilities/     Generated capability artifacts (committed: one genuine
                  discovery run's output - see capabilities/README.md)
evidence/         Generated run evidence (JSONL events, screenshots, etc.)
scripts/          CLI entrypoints: run_demo, discover_capability,
                  replay_capability, benchmark_replay, demo_escalation_handoff
tests/
  unit/           Fast, no browser, no network
  integration/    Real Chromium + real demo app (Playwright), no LLM
  e2e/            Full discover -> artifact -> replay round trip
```

## 4. Prerequisites

* Python 3.11+
* macOS/Linux/WSL (Playwright's bundled Chromium is downloaded automatically)
* A Gemini API key ([Google AI Studio](https://aistudio.google.com/app/apikey))
  **only** if you want to run genuine discovery. Everything else (demo app,
  replay, benchmarks, tests, API) works without one.

## 5. Installation

```bash
git clone <this-repo>
cd computer-use-automation
make install        # creates .venv, installs deps, installs Chromium
```

Equivalent manual steps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## 6. Environment setup

```bash
cp .env.example .env
```

`.env` is git-ignored; never commit it. Relevant variables (see
`.env.example` for the full, commented list):

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
DEMO_APP_BASE_URL=http://127.0.0.1:8001
EVIDENCE_DIR=evidence
CAPABILITIES_DIR=capabilities
HEADLESS_BROWSER=true
AGENT_MAX_STEPS=20
REPLAY_MAX_RETRIES=2
```

## 7. Gemini configuration

Set `GEMINI_API_KEY` in `.env`. The key is read once, held only in memory by
the `google-genai` SDK client, and is **never logged or written to
evidence** (see `app/safety/redaction.py` and `app/config.py`). If the key
is missing when a discovery run is attempted, the system fails immediately
with a clear, typed configuration error - it does not fall back to a fake
response.

`LLMProvider` (`app/providers/base.py`) is a protocol; `GeminiProvider` is
one implementation. Adding Anthropic/OpenAI/a new test double means writing
one new class, not touching the agent loop, planner, or prompts.

## 8. Running the local demo application

```bash
make demo
# or: python scripts/run_demo.py
```

Opens on `http://127.0.0.1:8001`. Sign in with anything (it's synthetic -
any non-empty username/password works), then try:

* Member `12345` / `67890` / `24680` - normal members with distinct balances.
* Member `99999` (or anything unmatched) - "no members found" business
  outcome.
* Member `40404` - simulated unexpected server error (HTTP 500).
* Member `50000` - forces a session-timeout redirect the first time you view
  its detail page in a given browser session (re-login and it works
  normally the second time).
* `/members/<id>?variant=b` - an alternate UI layout for the same data (no
  `data-testid` on the balance figures, different labels), used to
  demonstrate locator-profile-based heterogeneity.
* Any member's "Account Actions" page has a real "Transfer Funds" action -
  the safety policy blocks automation from ever clicking it (see
  [Safety model](#12-safety-model)).

The scripts below start this server for you automatically if it isn't
already running.

## 9. Running genuine discovery

```bash
make discover
# or:
python scripts/discover_capability.py \
    --goal "Look up member 12345 and read their current savings balance" \
    --member-id 12345
```

This performs a **real** Gemini-driven OBSERVE -> DECIDE -> VALIDATE -> ACT
loop against a live Chromium browser and the local demo app: it opens the
login page, sends the (bounded, structured) page observation to Gemini,
gets back one structured `AgentDecision` (never free text), validates it
against the safety policy, executes it, observes again, and repeats until
the model calls `finish`. On success it writes
`capabilities/member_savings_lookup.json` and full discovery evidence under
`evidence/discovery/<run_id>/` (events, screenshots, observation snapshots).

If `GEMINI_API_KEY` is not configured, this fails immediately with:

```
CONFIGURATION ERROR: GEMINI_API_KEY is not configured. ...
```

This is intentional - see `app/config.py::require_gemini_api_key`. Nothing
in this codebase fabricates an LLM response.

## 10. Inspecting the generated artifact

```bash
cat capabilities/member_savings_lookup.json | python -m json.tool
```

Look for:

* `inputs` / `outputs` - the capability's typed parameters, e.g.
  `member_id: string -> savings_balance: money`.
* `steps` - executable intent (`fill member-search-input with ${member_id}`),
  never a quote of the LLM's reasoning.
* `checkpoints` - explicit, executable assertions (URL changed, element
  visible, extracted value matches a money-shaped pattern).
* `error_mapping` - how observable page conditions (a banner containing
  "no members found") map to stable error codes.
* `safety.allowed_domains` - the domain allowlist replay is bound to.

The artifact is independent of the discovery transcript: nothing in it is a
stored prompt or LLM message. The raw discovery run's evidence is kept
separately under `evidence/discovery/`, purely for audit purposes.

## 11. Running deterministic replay

```bash
make replay
# or:
python scripts/replay_capability.py \
    --capability capabilities/member_savings_lookup.json \
    --member-id 12345
```

Prints a full `ReplayResult` as JSON: status, typed outputs (money as
`{"amount": "4231.55", "currency": "USD"}`, never a float), per-step
checkpoint results, timing, and retry counts. Replay evidence is written to
`evidence/replay/<run_id>/`.

Reuse the **same artifact, unmodified** with a different parameter:

```bash
python scripts/replay_capability.py \
    --capability capabilities/member_savings_lookup.json --member-id 67890
```

## 12. Running failure scenarios

```bash
make replay-not-found   # member 99999 -> status=business_outcome, code=MEMBER_NOT_FOUND
make replay-error       # member 40404 -> status=hard_failure, code=UNEXPECTED_APPLICATION_ERROR
make handoff            # risky action -> escalated, then a real human takeover + resume
```

A member-not-found result is not a crash - it is a clean, typed
`business_outcome`. A session timeout (member `50000`) is recoverable: the
engine restarts the capability from step one after re-navigating to the
login page, bounded by `REPLAY_MAX_RETRIES` (default 2) - see
`tests/integration/test_replay_error_scenarios.py` for both the "recovers
within budget" and "exhausts the budget and hard-fails" cases, run for
real.

## 13. Testing

```bash
make test              # everything
make test-unit         # fast, no browser
make test-integration  # real Chromium + real demo app
```

93 tests across three tiers:

* `tests/unit/` - artifact schema/versioning, parameter resolution, locator
  resolution and fallback, checkpoint model validation, the error taxonomy,
  retry policy, safety policy, redaction, session ownership, typed output
  parsing. No browser, no network, sub-second.
* `tests/integration/` - real Playwright against the real local demo app:
  successful replay, business outcomes, hard failures, recoverable
  session-timeout retries, the zero-LLM-calls proof, a scripted discovery
  run that DOES call an LLM provider, the escalation/handoff lifecycle, the
  locator-profile heterogeneity demo, and the HTTP API.
* `tests/e2e/` - chains discovery's own output (not a hand-built fixture)
  into the replay engine and back, including replaying with a *different*
  parameter than was used during discovery. This test is what caught two
  real bugs during development - see `REPORT.md` "Cuts" for what they were
  and how they were fixed.

## 14. Genuine LLM discovery evidence

CI and the test suite never require a real `GEMINI_API_KEY` (see
`.github/workflows/ci.yml` - `LLM_PROVIDER=mock`). The one-time genuine
Gemini run is the explicit, local `make discover` command described above.

This repository includes the evidence from an actual such run:
`evidence/discovery/60f6d565df0e4296bac97242222da5d9/` (Gemini
`gemini-3.5-flash`, 9 live agent steps, including two transient `503`s that
were retried automatically), which produced the
`capabilities/member_savings_lookup.json` that every other evidence
directory in this repository was subsequently replayed against. See
`evidence/README.md` for the full provenance chain, including the one
genuine bug this real run surfaced and how it was fixed without touching
the LLM-derived parts of the artifact.

## 15. Replay zero-LLM guarantee

This is structurally enforced, not just tested:

* `app/replay/executor.py` imports nothing from `app.providers` or
  `app.agent.loop`/`app.agent.planner` - only the pure, LLM-free
  `ActionType` enum from `app.agent.models`.
* `ReplayEngine.__init__` has no parameter through which an `LLMProvider`
  could even be passed in.
* `tests/integration/test_zero_llm_replay.py` proves both of the above by
  (a) statically parsing the executor module's imports via `ast`, and (b)
  wiring a `CountingLLMProvider(forbid_calls=True)` alongside a real replay
  run and asserting `call_count == 0` across success and business-outcome
  paths.
* `tests/integration/test_discovery_scripted.py` proves the mirror image:
  discovery genuinely calls the provider once per step.

Run just this proof:

```bash
.venv/bin/pytest tests/integration/test_zero_llm_replay.py -v
```

## 16. Human escalation demo

```bash
make handoff
```

Scripts a run toward a deliberately risky goal ("transfer funds"). The
safety policy blocks the "Transfer Funds" click before it ever reaches the
browser and the run stops with `status=escalated` - **the browser session
is not closed**. An `InterventionManager` then walks the real state machine
on that same session:

```
AUTOMATION -> ESCALATION_REQUESTED -> HUMAN_CONTROL -> RESUME_REQUESTED -> AUTOMATION
```

A simulated operator takes control, clicks "Transfer Funds" directly on the
still-open page (completing the real, synthetic transfer - see
`demo_app/app.py::transfer_funds`), and hands control back. Evidence for
every transition is written to `evidence/handoff/<intervention_id>/`.
`app/escalation/session_control.py::SessionRegistry` enforces that
automation cannot act again while a human holds control, and that a session
cannot be claimed by two actors at once.

## 17. Safety model

Every action - from the live LLM during discovery, or replayed from an
artifact - passes through `SafetyPolicy.evaluate()` (`app/safety/policy.py`)
before it reaches the browser. It is deterministic and keyword/action-type
based, deliberately **not** another LLM call:

* `app/safety/classifier.py` flags an action `BLOCKED` if its target's
  visible text/label/name matches a restricted-keyword pattern (transfer,
  delete, approve, withdraw, close account, change password, ...) -
  regardless of which action type it is.
* `navigate` is checked against an explicit domain allowlist
  (`safety.allowed_domains` on the artifact, or `--allowed-domains` for
  discovery); out-of-domain navigation is blocked and escalated.
* A blocked action never executes silently - it returns
  `PolicyDecision(allowed=False, escalate=True, reason=...)`, which the
  agent loop turns into an escalation and the replay engine turns into a
  `status=escalated` result with code `ACTION_BLOCKED_BY_POLICY`.
* The policy decision is always logged as a structured event
  (`EventType.POLICY_DECISION`).

Redaction (`app/safety/redaction.py`) removes API keys, bearer/JWT tokens,
password field values (never even captured by the browser extraction layer
in the first place - see `app/browser/_extract.js`), session cookies, and
member/account-id-shaped digit sequences from every log line and evidence
file. This is explicitly **best-effort, not perfect** - see the module
docstring and `tests/unit/test_redaction.py` for exactly what is and is not
covered.

## 18. Evidence directory

See `evidence/README.md` for the full layout and provenance notes. Summary:

```
evidence/
  discovery/    genuine LLM-driven discovery runs
  replay/       successful deterministic replays + benchmark/ summaries
  errors/       member_not_found, unexpected_error, session_timeout_recovered
  handoff/      escalation / take-control / resume state transitions
```

## 19. Design tradeoffs

See `REPORT.md` for the full discussion. In short: SQLite is used only for
a lightweight run registry, not as a general-purpose datastore; there is no
authentication layer (explicitly out of scope per the assignment); only one
`SurfaceAdapter` (Playwright) is implemented, with the protocol boundary
proven by the fact that neither the agent loop nor the replay engine import
it; multi-tenant/vendor heterogeneity is demonstrated via a locator-profile
override on one capability rather than a second full surface.

## 20. Limitations

* **Discovery records the successful linear path only.** If the LLM
  backtracks (clicks something wrong, then corrects itself), the recorder
  does not currently prune the abandoned branch - it only records what
  `DiscoveryEngine` explicitly calls `recorder.record()` on, which happens
  only after a successful action. A wrong-then-corrected sequence would
  currently produce extra steps rather than a clean artifact. Not
  encountered in practice with a well-behaved model.
* **Variant-B replay is demonstrated at the locator-resolution level, not
  the full `ReplayEngine.run()` level** - see `REPORT.md` "Cuts" for why,
  and `tests/integration/test_locator_profile_variant.py` for the concrete
  proof that the override mechanism itself works against a genuinely
  different DOM.
* **Redaction is pattern-based and best-effort** (documented above and in
  `app/safety/redaction.py`), not a formal PII-detection system.
* **The demo application's "hostility"** (unstable wrapper class names,
  minimal semantic markup on Variant B) is deliberately modest - enough to
  make locator robustness meaningful without requiring an adversarial DOM
  fuzzer.
* **Login credentials are not modeled as declared capability parameters.**
  In the genuine discovery run checked into this repository, Gemini typed
  synthetic username/password values into the login form (this demo app
  explicitly accepts any non-empty credentials - "No real credentials are
  required" is stated on the page itself); those literal values were
  recorded into `capabilities/member_savings_lookup.json`'s first two steps
  as-is, because only `member_id` was declared as an input the recorder
  knows to parameterize. This is harmless here, but is exactly the kind of
  thing that must change before pointing this system at an application with
  real credentials: a login step's inputs should be declared parameters
  resolved from a secrets store at replay time, never committed to an
  artifact as a literal.

## 21. Future extensions

* A `LegacyWebSurface` (plain HTTP + HTML parsing, for apps too old/simple
  to need a full browser) or a `DesktopSurface` (OS-level UI automation) -
  the `SurfaceAdapter` protocol is the seam; neither the agent loop nor the
  replay engine would need to change.
* A second `LLMProvider` (Anthropic/OpenAI) - implement `app/providers/base.py`'s
  protocol; `app/providers/__init__.py::create_llm_provider` is the only
  factory that would need a new branch.
* Full per-tenant surface configuration (base URL + locator profile bundled
  together) rather than a locator-profile override demonstrated at the
  resolution layer.
* A background job queue for discovery/replay runs kicked off via the API,
  instead of the current synchronous-within-the-request model (deliberately
  out of scope: "no unnecessary infrastructure").

---

## Makefile reference

```
make install            create venv, install deps + Chromium
make lint               ruff check
make format             ruff check --fix
make typecheck          mypy
make test               full pytest suite
make test-unit          unit tests only
make test-integration   integration tests only
make demo               run the local demo app (foreground)
make discover           genuine Gemini discovery run (needs GEMINI_API_KEY)
make replay             deterministic replay, member 12345
make replay-not-found   deterministic replay, member 99999 (business outcome)
make replay-error       deterministic replay, member 40404 (hard failure)
make handoff            escalation / human takeover / resume demo
make benchmark          10-run replay stability benchmark
make run-api            run the integration layer's own FastAPI app
```
