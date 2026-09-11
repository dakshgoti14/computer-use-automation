"""A minimal, self-contained public demo page.

Deliberately not a SPA / build step / frontend framework - one inline HTML
file, vanilla `fetch()`, served directly by FastAPI. It exists to let a
reviewer trigger a *real* deterministic replay (a real headless-Chromium
session against the also-hosted demo bank app, no mocking) from a browser
with nothing installed, and see the real typed JSON result. It intentionally
does not expose LLM-driven discovery - see PUBLIC_DEMO_MODE in
app/config.py and the 403 in app/api/routes.py for why.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

DEMO_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Computer-Use Automation - Live Replay Demo</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 760px; margin: 0 auto; padding: 2rem 1.25rem 4rem;
    line-height: 1.55; color: #1a1a1a; background: #fafafa;
  }
  @media (prefers-color-scheme: dark) { body { color: #eaeaea; background: #121212; } }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
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
    overflow-x: auto; font-size: 0.85rem; white-space: pre-wrap; word-break: break-word;
  }
  .badge {
    display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
    font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
  }
  .badge.success { background: #dcfce7; color: #166534; }
  .badge.business_outcome { background: #fef9c3; color: #854d0e; }
  .badge.hard_failure { background: #fee2e2; color: #991b1b; }
  .note { font-size: 0.85rem; color: #777; }
  a { color: #2563eb; }
  code { background: rgba(127,127,127,0.15); padding: 0.1rem 0.35rem; border-radius: 4px; }
</style>
</head>
<body>

<h1>Computer-Use Automation - Live Replay Demo</h1>
<p class="subtitle">
  A real deterministic replay engine, running against a real local demo
  banking application, driven by a real headless browser - no LLM in this
  loop. See <a href="https://github.com/dakshgoti14/computer-use-automation">
  the repository</a> for the full system, including the genuine LLM-driven
  discovery run that produced this capability.
</p>

<div class="card">
  <label for="member-id">Member ID</label>
  <select id="member-id">
    <option value="12345">12345 - Jordan Alvarez (has savings balance)</option>
    <option value="67890">67890 - a different member (proves the artifact is reusable, unmodified)</option>
    <option value="99999">99999 - no such member (business outcome, not a crash)</option>
    <option value="40404">40404 - triggers an unexpected application error</option>
    <option value="50000">50000 - triggers a session timeout the replay recovers from</option>
  </select>
  <button id="run-btn" onclick="runReplay()">Run live replay</button>
  <p class="note">
    Each click spins up a real headless-Chromium session in this demo's
    container. Rate-limited to keep the shared instance responsive - if you
    get a 429, wait a few minutes or run it yourself: <code>make replay
    --member-id &lt;id&gt;</code> after cloning the repo.
  </p>
</div>

<div id="result-card" class="card" style="display:none;">
  <div id="result-summary"></div>
  <pre id="result-json"></pre>
</div>

<script>
async function runReplay() {
  const btn = document.getElementById('run-btn');
  const memberId = document.getElementById('member-id').value;
  const card = document.getElementById('result-card');
  const summary = document.getElementById('result-summary');
  const json = document.getElementById('result-json');

  btn.disabled = true;
  btn.textContent = 'Running real replay...';
  card.style.display = 'block';
  summary.innerHTML = '<em>Launching a real browser session against the live demo bank app...</em>';
  json.textContent = '';

  try {
    const resp = await fetch('/capabilities/member_savings_lookup/replay', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { member_id: memberId } }),
    });
    const data = await resp.json();

    if (!resp.ok) {
      summary.innerHTML = `<span class="badge hard_failure">HTTP ${resp.status}</span> ${data.detail || 'request failed'}`;
      json.textContent = JSON.stringify(data, null, 2);
      return;
    }

    const status = data.status || 'unknown';
    summary.innerHTML = `<span class="badge ${status}">${status.replace('_', ' ')}</span> `
      + `${data.message || ''} <span class="note">(${data.duration_ms ? data.duration_ms.toFixed(0) : '?'} ms, `
      + `${data.steps ? data.steps.length : 0} steps, run ${data.run_id || ''})</span>`;
    json.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    summary.innerHTML = '<span class="badge hard_failure">error</span> ' + err;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run live replay';
  }
}
</script>

</body>
</html>
"""


def demo_page() -> HTMLResponse:
    return HTMLResponse(content=DEMO_PAGE_HTML)
