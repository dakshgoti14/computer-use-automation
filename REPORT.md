# Architecture

Three engines, three responsibilities, one boundary that must never blur:

```
DiscoveryEngine  -> LLMProvider          -> CapabilityArtifact
ReplayEngine     -> CapabilityArtifact   -> SurfaceAdapter -> deterministic result
```

`DiscoveryEngine` (`app/agent/loop.py`) runs OBSERVE -> DECIDE -> VALIDATE ->
ACT -> OBSERVE against a live browser. Every DECIDE step calls an
`LLMProvider` (`app/providers/base.py`, implemented by `GeminiProvider`) and
gets back exactly one `AgentDecision` - a fixed, schema-validated action
from a closed vocabulary (click/fill/select/extract/wait/navigate/finish/
escalate). The LLM never sees raw HTML (only a bounded `Observation`), never
generates code, and never picks an action outside that vocabulary; Gemini's
structured-output mode enforces the shape, and `Planner` (`app/agent/planner.py`)
re-validates it before anything executes. Every VALIDATE step runs the
*same* `SafetyPolicy` that replay uses - discovery gets no special
exemption.

`ReplayEngine` (`app/replay/executor.py`) never touches an LLM. It loads an
artifact, validates it, resolves `${param}` references through a
fail-closed template resolver, and drives the same `SurfaceAdapter`
protocol discovery used. The two engines share the browser abstraction and
the safety policy; they share nothing else. This is enforced structurally,
not just by convention - `app/replay/executor.py` has no import path to
`app.providers` or `app.agent.loop`/`planner`, and `ReplayEngine.__init__`
has no parameter an `LLMProvider` could be smuggled through. See
`tests/integration/test_zero_llm_replay.py`.

Why the LLM is discovery-only: an agent that re-decides every action on
every run is slow, costly, and non-deterministic - unacceptable for a
capability a production system might invoke thousands of times a day
against a bank. Discovery pays that cost once, on a human-supervised run,
and produces something a human can review and freeze.

# Artifact schema

`app/artifacts/schema.py::CapabilityArtifact` is the contract between
discovery and replay. Design choices:

* **Steps are executable intent, not transcript.** A step is
  `{action, target, value_template, checkpoint_ids}` - never a quote of
  what the model said. `app/artifacts/recorder.py::DiscoveryRecorder`
  builds it from typed `AgentAction` records, and never stores a prompt or
  a raw model message anywhere in the artifact. The discovery transcript
  lives separately, in evidence, purely for audit.
* **Locators are logical, not literal.** A target is
  `{strategy: role|label|test_id|text|css|xpath|coordinate, ...}` ranked in
  that stability order (`app/browser/locators.py`), with an optional
  ordered fallback chain. Replay resolves this into a concrete Playwright
  locator (`app/browser/playwright_surface.py::resolve_locator`); nothing
  in the artifact is Playwright-specific.
* **Parameters are references, resolved narrowly.** `${member_id}` inside a
  `value_template`, `url_template`, or a locator's own text field (e.g.
  `test_id="view-member-${member_id}"`) is resolved by
  `resolve_template()`, which fails closed (`KeyError` ->
  `PARAMETER_RESOLUTION_FAILED`) on any unresolved reference - never a
  blind string replace. The recorder performs the inverse substitution at
  discovery time: it replaces *exact* occurrences of the literal value used
  during that specific run with the `${param}` reference, across fill
  values, URLs, *and* locator fields - see "Cuts" below for a real bug this
  caught.
* **Checkpoints are executable assertions, not vibes.** Every step's
  `checkpoint_ids` point at `Checkpoint` objects with a concrete `kind`
  (`element_visible`, `url_matches`, `text_contains`,
  `value_matches_pattern`) evaluated by `app/replay/checkpoints.py`. A step
  only counts as successful once every attached checkpoint passes - "the
  click probably worked" is not a code path that exists.
* **Outputs are typed, and money is never a float.** `OutputSpec.type`
  drives `app/replay/result.py::parse_typed_output`, which parses extracted
  text into a `Decimal`-backed `MoneyValue` (or number/boolean/string) and
  raises `OUTPUT_CONVERSION_FAILED` on anything that doesn't match the
  expected shape - it never silently returns garbage.
* **Validation is a separate pass** (`app/artifacts/validator.py`), checked
  cross-field: every `checkpoint_ids` reference resolves, every template
  parameter reference is declared, every declared output has a producing
  step, `safety.allowed_domains` is non-empty. Run on load *and* defensively
  again at the start of every replay - an artifact is never trusted blindly.

# Determinism & error handling

Four categories, one taxonomy (`app/errors.py`), used everywhere - no
module raises a bare `Exception`:

* **`BUSINESS_OUTCOME`** (e.g. `MEMBER_NOT_FOUND`) - the application
  legitimately said no. Not a bug, not retried, reported cleanly as
  `status=business_outcome`.
* **`RECOVERABLE`** (e.g. `SESSION_TIMEOUT`, `LOCATOR_TIMEOUT_TRANSIENT`) -
  a bounded retry policy (`app/replay/errors.py::RetryPolicy`,
  `max_attempts` from config) may retry. Two distinct recovery shapes are
  implemented: an in-place retry of just the failed step (transient
  rendering delay), and a full capability restart from step one (session
  timeout - re-authenticating invalidates every assumption later steps
  made, so retrying only the failed step would be wrong; see
  `ReplayEngine._RestartCapability`). Retries are always bounded and always
  logged (`EventType.RETRY_ATTEMPTED`); never infinite, never applied to a
  risky action (those are blocked by the safety policy before a retry loop
  would ever see them).
* **`HARD_FAILURE`** (e.g. `CHECKPOINT_FAILED`, `UNEXPECTED_APPLICATION_ERROR`,
  `ARTIFACT_INVALID`) - automation cannot safely continue. Includes a
  last-resort `except Exception` boundary inside the replay step loop that
  converts *any* unclassified failure (a raw Playwright error, a defect in
  this engine) into a typed `INTERNAL_REPLAY_ERROR` rather than letting a
  bare traceback escape a deterministic engine.
* **`ESCALATED`** - automation deliberately stopped for a human. Used both
  when the LLM itself calls `escalate` and when the safety policy blocks an
  action outright.

`app/replay/executor.py::_match_error_mapping` checks the artifact's
`error_mapping` rules (banner text / URL / page text) against the live
observation whenever a checkpoint fails, so a business outcome like "no
members found" is classified *before* it would otherwise look like a
generic locator-not-found hard failure.

Determinism follows from the engine never improvising: every action is a
literal field from the artifact, every retry follows one of exactly two
named strategies, every classification comes from a static rule table, not
a fresh judgment call.

# Heterogeneity & multi-tenant

`SurfaceAdapter` (`app/browser/surface.py`) is a `Protocol`; neither
`DiscoveryEngine` nor `ReplayEngine` imports Playwright. `PlaywrightSurface`
is the only implementation built for this assessment, but the seam is real:
a future `LegacyWebSurface` or `DesktopSurface` would need to satisfy the
same eight-method protocol and nothing upstream would change.

For vendor/UI variance *within* one surface type, `CapabilityArtifact`
carries `locator_profiles`: a named override map of `step_id -> LocatorTarget`
layered on top of the default targets at replay time
(`ReplayEngine._resolve_step`). The same `capability_id`, same steps, same
checkpoints, same error mapping - only the per-step locator differs. The
demo app ships a second UI variant (`?variant=b` - no `data-testid` on the
balance figures, different labels) specifically to exercise this.

# Escalation & handoff

State machine (`app/escalation/models.py`):

```
AUTOMATION -> ESCALATION_REQUESTED -> HUMAN_CONTROL -> RESUME_REQUESTED -> AUTOMATION
```

`InterventionManager` enforces the transition table explicitly - no state
can be skipped. `SessionRegistry` enforces exclusive ownership: automation
cannot act while a session's owner is `HUMAN`
(`require_automation_owns` raises `SESSION_UNDER_HUMAN_CONTROL`), and a
session cannot be claimed by two actors at once
(`SESSION_ALREADY_CONTROLLED`). Critically, escalation never closes the
browser - `DiscoveryEngine.run()` returns without calling
`surface.close()` on an escalated result, so the exact live page state is
what a human operator sees and acts on next (`scripts/demo_escalation_handoff.py`
proves this by clicking the real "Transfer Funds" button on the same
`Page` object after escalation, then handing control back).

Detecting "stuck": two triggers, both surfaced through the same channel.
Either the LLM itself decides it cannot proceed and returns an `escalate`
action (a first-class member of the fixed action vocabulary, not a special
case), or the safety policy blocks a proposed action outright. Both paths
build the *same* `escalation_context` (`DiscoveryEngine._build_escalation_context`):
which capability/goal was running, the step it stopped on, the current
URL, and a screenshot taken at that exact moment - so an intervention
request is actionable on its own, not just a reason string a human has to
go re-derive context for. Handoff is not only "control changed hands":
`InterventionManager.record_operator_action` appends a timestamped,
evidence-linked entry for each thing the operator does while holding
control (enforced to only be callable in the `HUMAN_CONTROL` state, so the
audit trail can't misattribute an action to the wrong actor), and resume
transitions the state machine back to `AUTOMATION` before releasing
ownership.

# Safety

One policy, evaluated identically for the live agent and for replay
(`app/safety/policy.py::SafetyPolicy.evaluate`), called unconditionally
before every action reaches a surface. It is deliberately deterministic
keyword/action-type logic, not another model call - a safety gate that
itself required an LLM judgment would inherit all of the LLM's
non-determinism it exists to guard against. A domain allowlist gates
`navigate`; a restricted-keyword classifier
(`app/safety/classifier.py`) blocks any action whose target text matches
money-movement or irreversible-change patterns (transfer, delete, approve,
withdraw, ...) regardless of action type. A blocked action is never
silently skipped - it becomes an escalation with a logged reason. Redaction
(`app/safety/redaction.py`) strips API keys, tokens, cookies, and
member/account-id-shaped digits from logs and evidence, and the browser
extraction layer never captures password field *values* in the first place
(defense at the source, not just downstream). Both are explicitly
documented as best-effort, not a formal guarantee.

# Cuts

What was intentionally not built, and two things a real end-to-end test
caught that a narrower test suite would have missed:

* **Desktop/legacy-web surfaces are not implemented** - only the protocol
  and one concrete adapter. Building a second surface would prove the
  abstraction but adds no signal beyond what the protocol boundary already
  demonstrates for this assessment's scope.
* **Variant-B heterogeneity is demonstrated at the locator-resolution
  level**, not by extending `ReplayEngine.run()` to also branch navigation
  per locator profile. In this demo app, Variant B is reached via a query
  parameter on the same route; a real multi-tenant deployment would more
  naturally put it behind a different base URL per tenant, which the
  current `start_url_template` mechanism already handles per-capability.
  Extending the schema so one profile can also override the start URL was
  judged not worth the added surface area for what it would additionally
  prove here.
* **Discovery does not prune backtracking.** If the agent clicks something
  wrong and self-corrects, the recorder would currently include the
  detour, because `DiscoveryEngine` only calls `recorder.record()` after a
  successful action (failed actions are surfaced back to the model via the
  next observation instead of being recorded) - a wrong-then-corrected
  *successful* sequence isn't specially detected. Not hit in this
  assessment's runs; would need explicit dead-end detection to fix
  properly.
* **Two real bugs, found by `tests/e2e/test_full_lifecycle.py`:** an
  end-to-end test that chains discovery's own artifact into replay (rather
  than a hand-built fixture) is what surfaced these - a good argument for
  keeping at least one such test even though it's slower than the unit
  suite.
  1. The recorder's auto-generated "target still visible" checkpoint
     (Rule C) was originally applied even to steps that navigate away
     (e.g. clicking a "Sign In" button that leads to `/dashboard`) -
     asserting the button is "still visible" after the page it lived on is
     gone. Fixed by only attaching that checkpoint when the step did not
     change the URL.
  2. The recorder parameterized `value_template`/`url_template` but not a
     step's own locator fields - so a target like
     `test_id="view-member-12345"` (selecting a specific search-result row)
     was replayed verbatim and broke for any other `member_id`. Fixed by
     applying the same literal-to-`${param}` substitution to locator text
     fields (`test_id`/`name`/`label`/`text`/`css`), recursively through
     fallback chains, mirroring the inverse substitution already done at
     replay time.
* **Two more real bugs, found by the genuine Gemini discovery run itself**
  (not by any test) - the strongest argument in this whole project for
  actually running the thing end to end rather than trusting the design:
  1. The recorder's hardcoded default `MEMBER_NOT_FOUND` error-mapping rule
     matched the substring `"not found"`, but this demo app's actual banner
     text is `"No members found matching that search."` - which does not
     contain that substring. A real not-found search was misclassified as a
     generic locator-timeout hard failure instead of a clean business
     outcome. Fixed the default rule's text, and more importantly fixed the
     *structural* gap it exposed: `ReplayEngine` only re-checked
     `error_mapping` when a *checkpoint* failed, not when the *action
     itself* failed (e.g. clicking a "view member" link that never rendered
     because no member matched). Reclassification now runs uniformly for
     any non-business-outcome `AutomationError`, regardless of which of the
     two ways a step can fail.
  2. `GeminiProvider` had no request timeout and no retry: a real call
     against a momentarily congested endpoint hung indefinitely (no
     exception, just silence), and separately, back-to-back real calls
     intermittently returned transient `503`s. Fixed with a bounded
     per-request timeout and a small bounded retry (3 attempts, short
     backoff) restricted to server-side errors only - a `4xx` (bad
     request, exhausted quota) still fails immediately rather than
     retrying into a wasted attempt budget.
  Also worth naming honestly: Gemini's first real attempt at the
  member-selection step targeted the search-result row by
  `role=link name="View Jordan Alvarez"` - technically this system's
  *highest*-priority locator strategy, but wrong here because the
  accessible name is itself member-specific data. The system prompt
  (`app/agent/prompts.py`) was refined with an explicit exception for this
  case; the discovery run checked into this repository (built afterward)
  correctly targets by `test_id="view-member-${member_id}"` instead.
* **No authentication/authorization infrastructure** on the integration
  API, per the assignment's explicit guidance - this is a take-home
  artifact, not a production banking service.
