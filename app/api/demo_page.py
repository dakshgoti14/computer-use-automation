"""A minimal, self-contained public demo page.

Deliberately not a SPA / build step / frontend framework - one inline HTML
file, vanilla `fetch()`, served directly by FastAPI. It exists to let a
reviewer *see* the system working, not just read a JSON blob:

* A gallery built server-side, at request time, straight from the genuine
  discovery run's own evidence (evidence/discovery/.../run.jsonl +
  screenshots) - the actual screen the LLM saw and the actual reasoning it
  gave for each action, not a description of it.
* A live, interactive replay: pick a member ID, and the actual
  ReplayEngine drives an actual headless-Chromium session against the
  actual demo bank app, with a screenshot after every step - so what
  renders is a real filmstrip of the real UI, not a pretty-printed dict.

It intentionally does not expose LLM-driven discovery - see
PUBLIC_DEMO_MODE in app/config.py and the 403 in app/api/routes.py for why.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from fastapi.responses import HTMLResponse

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 880px; margin: 0 auto; padding: 2rem 1.25rem 4rem;
    line-height: 1.55; color: #1a1a1a; background: #fafafa;
  }
  @media (prefers-color-scheme: dark) { body { color: #eaeaea; background: #121212; } }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.1rem; margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: 0.4rem; }
  @media (prefers-color-scheme: dark) { h2 { border-color: #333; } }
  .subtitle { color: #666; margin-top: 0; }
  @media (prefers-color-scheme: dark) { .subtitle { color: #999; } }
  .card {
    border: 1px solid #ddd; border-radius: 10px; padding: 1.25rem;
    margin: 1.25rem 0; background: white;
  }
  @media (prefers-color-scheme: dark) { .card { background: #1c1c1c; border-color: #333; } }
  label { font-weight: 600; display: block; margin-bottom: 0.4rem; }
  select, button {
    font-size: 1rem; padding: 0.5rem 0.75rem; border-radius: 6px;
    border: 1px solid #ccc;
  }
  button {
    background: #2563eb; color: white; border: none; cursor: pointer;
    font-weight: 600; margin-left: 0.5rem;
  }
  button:disabled { background: #93b4f0; cursor: wait; }
  pre {
    background: #0d1117; color: #c9d1d9; padding: 1rem; border-radius: 8px;
    overflow-x: auto; font-size: 0.8rem; white-space: pre-wrap; word-break: break-word;
  }
  .badge {
    display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
    font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
  }
  .badge.success { background: #dcfce7; color: #166534; }
  .badge.business_outcome { background: #fef9c3; color: #854d0e; }
  .badge.hard_failure { background: #fee2e2; color: #991b1b; }
  .badge.blocked { background: #fee2e2; color: #991b1b; }
  .badge.failed { background: #fee2e2; color: #991b1b; }
  .note { font-size: 0.85rem; color: #777; }
  a { color: #2563eb; }
  code { background: rgba(127,127,127,0.15); padding: 0.1rem 0.35rem; border-radius: 4px; }
  .filmstrip { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 1rem; }
  .frame {
    width: 220px; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;
    background: white; font-size: 0.8rem;
  }
  @media (prefers-color-scheme: dark) { .frame { background: #1c1c1c; border-color: #333; } }
  .frame img { width: 100%; display: block; border-bottom: 1px solid #ddd; }
  @media (prefers-color-scheme: dark) { .frame img { border-color: #333; } }
  .frame .body { padding: 0.6rem; }
  .frame .step-label { font-weight: 700; }
  .frame .reasoning { color: #555; margin-top: 0.3rem; }
  @media (prefers-color-scheme: dark) { .frame .reasoning { color: #aaa; } }
"""


def _discovery_gallery_html(evidence_dir: Path) -> str:
    """Read the genuine discovery run's own evidence and render it as a
    filmstrip: the real screenshot + the real reasoning Gemini gave for
    each action, straight from evidence/discovery/*/run.jsonl.

    Rebuilt from disk on every page load rather than cached or hardcoded,
    so it can never drift from whatever discovery evidence actually exists
    in this deployment.
    """

    discovery_root = evidence_dir / "discovery"
    if not discovery_root.is_dir():
        return "<p class=\"note\">No discovery evidence found in this deployment.</p>"

    run_dirs = sorted(
        (d for d in discovery_root.iterdir() if d.is_dir() and (d / "run.jsonl").exists()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not run_dirs:
        return "<p class=\"note\">No discovery evidence found in this deployment.</p>"

    run_dir = run_dirs[0]
    events = [
        json.loads(line)
        for line in (run_dir / "run.jsonl").read_text().splitlines()
        if line.strip()
    ]

    goal = ""
    steps: dict[str, dict[str, str]] = {}
    for event in events:
        step_id = event.get("step_id")
        if event["event_type"] == "run_started":
            goal = event.get("details", {}).get("goal", "")
        elif event["event_type"] == "observation" and step_id:
            steps.setdefault(step_id, {})
            steps[step_id]["url"] = event["details"].get("url", "")
            steps[step_id]["title"] = event["details"].get("title", "")
        elif event["event_type"] == "agent_decision" and step_id:
            steps.setdefault(step_id, {})
            steps[step_id]["action"] = event.get("action", "")
            steps[step_id]["reasoning"] = event.get("details", {}).get("reasoning", "")

    frames = []
    for step_id in sorted(steps):
        info = steps[step_id]
        screenshot = run_dir / "screenshots" / f"{step_id}-before.png"
        if not screenshot.exists():
            continue
        frames.append(f"""
        <div class="frame">
          <img src="/evidence-file?path={html.escape(str(screenshot.resolve()))}" alt="{html.escape(step_id)} screenshot">
          <div class="body">
            <div class="step-label">{html.escape(step_id)} - {html.escape(info.get('action', ''))}</div>
            <div class="note">{html.escape(info.get('title', ''))}</div>
            <div class="reasoning">&ldquo;{html.escape(info.get('reasoning', ''))}&rdquo;</div>
          </div>
        </div>""")

    if not frames:
        return "<p class=\"note\">Discovery evidence exists but has no screenshots to show.</p>"

    return f"""
    <p class="note">Real reasoning from a real Gemini-driven run, goal:
      <em>&ldquo;{html.escape(goal)}&rdquo;</em> - {len(frames)} steps shown below,
      straight from <code>evidence/discovery/{html.escape(run_dir.name)}/</code>.</p>
    <div class="filmstrip">{''.join(frames)}</div>
    """


def demo_page(evidence_dir: Path) -> HTMLResponse:
    discovery_gallery = _discovery_gallery_html(evidence_dir)

    return HTMLResponse(content=f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Computer-Use Automation - Live Demo</title>
<style>{_PAGE_STYLE}</style>
</head>
<body>

<h1>Computer-Use Automation - Live Demo</h1>
<p class="subtitle">
  A real deterministic replay engine driving a real headless browser
  against a real local demo banking application - no LLM in this loop.
  See <a href="https://github.com/dakshgoti14/computer-use-automation">
  the repository</a> for the full system and source.
</p>

<h2>How this capability was discovered</h2>
{discovery_gallery}

<h2>Run it live: deterministic replay</h2>
<div class="card">
  <label for="member-id">Member ID</label>
  <select id="member-id">
    <option value="12345">12345 - Jordan Alvarez (has a savings balance)</option>
    <option value="67890">67890 - a different member (proves the artifact is reusable, unmodified)</option>
    <option value="99999">99999 - no such member (a business outcome, not a crash)</option>
    <option value="40404">40404 - triggers an unexpected application error</option>
    <option value="50000">50000 - triggers a session timeout the replay recovers from</option>
  </select>
  <button id="run-btn" onclick="runReplay()">Run live replay</button>
  <p class="note">
    Each click spins up a real headless-Chromium session in this demo's
    container and screenshots every step. Rate-limited to keep the shared
    instance responsive - a 429 means wait a few minutes, or clone the repo
    and run <code>make replay</code> locally.
  </p>
</div>

<div id="result-card" style="display:none;">
  <div class="card">
    <div id="result-summary"></div>
  </div>
  <div id="result-filmstrip" class="filmstrip"></div>
  <details style="margin-top: 1rem;">
    <summary class="note">Raw JSON result</summary>
    <pre id="result-json"></pre>
  </details>
</div>

<script>
async function runReplay() {{
  const btn = document.getElementById('run-btn');
  const memberId = document.getElementById('member-id').value;
  const card = document.getElementById('result-card');
  const summary = document.getElementById('result-summary');
  const filmstrip = document.getElementById('result-filmstrip');
  const json = document.getElementById('result-json');

  btn.disabled = true;
  btn.textContent = 'Running real replay...';
  card.style.display = 'block';
  summary.innerHTML = '<em>Launching a real browser session against the live demo bank app...</em>';
  filmstrip.innerHTML = '';
  json.textContent = '';

  try {{
    const resp = await fetch('/capabilities/member_savings_lookup/replay', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ params: {{ member_id: memberId }} }}),
    }});
    const data = await resp.json();

    if (!resp.ok) {{
      summary.innerHTML = `<span class="badge hard_failure">HTTP ${{resp.status}}</span> ${{data.detail || 'request failed'}}`;
      json.textContent = JSON.stringify(data, null, 2);
      return;
    }}

    const status = data.status || 'unknown';
    summary.innerHTML = `<span class="badge ${{status}}">${{status.replace('_', ' ')}}</span> `
      + `${{data.message || ''}} <span class="note">(${{data.duration_ms ? data.duration_ms.toFixed(0) : '?'}} ms, `
      + `${{data.steps ? data.steps.length : 0}} steps, run ${{data.run_id || ''}})</span>`;

    for (const step of (data.steps || [])) {{
      if (!step.screenshot_ref) continue;
      const frame = document.createElement('div');
      frame.className = 'frame';
      const badgeClass = step.status === 'success' ? 'success' : (step.status === 'business_outcome' ? 'business_outcome' : 'failed');
      frame.innerHTML = `
        <img src="/evidence-file?path=${{encodeURIComponent(step.screenshot_ref)}}" alt="${{step.step_id}} screenshot">
        <div class="body">
          <div class="step-label">${{step.step_id}} - ${{step.action}} <span class="badge ${{badgeClass}}">${{step.status}}</span></div>
          <div class="note">${{step.duration_ms.toFixed(0)}} ms, attempt ${{step.attempts}}</div>
          ${{step.error_message ? `<div class="reasoning">${{step.error_message}}</div>` : ''}}
        </div>`;
      filmstrip.appendChild(frame);
    }}

    json.textContent = JSON.stringify(data, null, 2);
  }} catch (err) {{
    summary.innerHTML = '<span class="badge hard_failure">error</span> ' + err;
  }} finally {{
    btn.disabled = false;
    btn.textContent = 'Run live replay';
  }}
}}
</script>

</body>
</html>
""")
