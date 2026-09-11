"""A deliberately "hostile legacy-like" local banking back-office application.

This is the TARGET SURFACE the agent/replay engine operate on - it is not
part of the reusable integration layer itself. It exists to provide enough
realistic behaviour (search, details, balances, validation errors,
not-found outcomes, session timeout, an unexpected error state, a risky
transfer action, and a second UI variant) to make the rest of the system
meaningful to demonstrate.

Run directly with:  python -m demo_app.app
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from demo_app.data import (
    ERROR_TRIGGER_MEMBER_ID,
    MEMBERS,
    TIMEOUT_TRIGGER_MEMBER_ID,
    rand_suffix,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Riverbend Community Credit Union - Demo Back Office")
# A fixed, non-secret demo key is fine here: this is a synthetic local test
# surface with no real user data, never deployed, and explicitly out of
# scope for the "no secrets" rule (there is nothing secret to protect).
app.add_middleware(SessionMiddleware, secret_key="demo-app-non-secret-session-key")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SEARCH_DELAY_SECONDS = 1.2


def _flash(request: Request, text: str, kind: str = "error") -> None:
    flashes = request.session.setdefault("flash", [])
    flashes.append({"text": text, "kind": kind})


def _pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])


def _render(request: Request, template: str, status_code: int = 200, **context: object) -> HTMLResponse:
    context.setdefault("authenticated", bool(request.session.get("authenticated")))
    context.setdefault("flash_messages", _pop_flashes(request))
    context.setdefault("rand", rand_suffix())
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def _require_auth(request: Request) -> bool:
    return bool(request.session.get("authenticated")) and not request.session.get("forced_expired")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> RedirectResponse:
    return RedirectResponse("/dashboard" if _require_auth(request) else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if request.query_params.get("expired"):
        _flash(request, "Your session has expired. Please sign in again.", kind="error")
    return _render(request, "login.html", authenticated=False)


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    # Synthetic auth: any non-empty credentials succeed. This app has no
    # real users - the point is to exercise a login step, not to gate access.
    request.session["authenticated"] = True
    request.session["forced_expired"] = False
    request.session["username"] = username or "operator"
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)
    return _render(request, "dashboard.html", username=request.session.get("username"))


@app.get("/members/search", response_class=HTMLResponse)
async def search_form(request: Request) -> Response:
    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)
    return _render(request, "search.html", searched=False, results=None, query=None)


@app.post("/members/search", response_class=HTMLResponse)
async def search_submit(request: Request, member_id: str = Form(...)) -> Response:
    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)

    # Simulated network/render delay - exercises "delayed UI state" handling.
    await asyncio.sleep(SEARCH_DELAY_SECONDS)

    member_id = member_id.strip()
    if not member_id:
        _flash(request, "Please enter a member ID to search.", kind="error")
        return _render(request, "search.html", searched=False, results=None, query=member_id)

    if member_id == ERROR_TRIGGER_MEMBER_ID:
        return _render(request, "error.html", status_code=500)

    match = MEMBERS.get(member_id)
    results = [match] if match else []
    return _render(request, "search.html", searched=True, results=results, query=member_id)


@app.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail(request: Request, member_id: str, variant: str = "a") -> Response:
    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)

    if member_id == ERROR_TRIGGER_MEMBER_ID:
        return _render(request, "error.html", status_code=500)

    if member_id == TIMEOUT_TRIGGER_MEMBER_ID and not request.session.get("timeout_already_forced"):
        # Force the session to appear expired the FIRST time this member is
        # viewed per browser session, so the redirect to /login (below)
        # deterministically reproduces a session-timeout condition for
        # testing/evidence purposes. Only once, so a client that correctly
        # re-authenticates and retries then succeeds - demonstrating actual
        # recovery, not just repeated failure.
        request.session["forced_expired"] = True
        request.session["timeout_already_forced"] = True
        return RedirectResponse("/login?expired=1", status_code=303)

    member = MEMBERS.get(member_id)
    if member is None:
        _flash(request, f"Member {member_id} was not found.", kind="error")
        return RedirectResponse("/members/search", status_code=303)

    return _render(request, "member_detail.html", member=member, variant=variant.lower())


@app.get("/members/{member_id}/actions", response_class=HTMLResponse)
async def member_actions(request: Request, member_id: str) -> Response:
    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)
    member = MEMBERS.get(member_id)
    if member is None:
        _flash(request, f"Member {member_id} was not found.", kind="error")
        return RedirectResponse("/members/search", status_code=303)
    return _render(request, "member_actions.html", member=member)


@app.post("/members/{member_id}/transfer")
async def transfer_funds(request: Request, member_id: str, amount: str = Form(...)) -> RedirectResponse:
    """A real, risky, irreversible action. Automation must never reach this
    endpoint - the safety policy blocks the "Transfer Funds" click before a
    request is ever made. Implemented for real (not a stub) so a human
    operator using the escalation handoff could deliberately complete it."""

    if not _require_auth(request):
        return RedirectResponse("/login?expired=1", status_code=303)
    member = MEMBERS.get(member_id)
    if member is None:
        return RedirectResponse("/members/search", status_code=303)
    try:
        delta = float(amount)
    except ValueError:
        _flash(request, "Invalid transfer amount.", kind="error")
        return RedirectResponse(f"/members/{member_id}/actions", status_code=303)

    savings = float(member.savings_balance.replace(",", ""))
    checking = float(member.checking_balance.replace(",", ""))
    savings -= delta
    checking += delta
    member.savings_balance = f"{savings:,.2f}"
    member.checking_balance = f"{checking:,.2f}"
    _flash(request, f"Transferred {amount} from savings to checking.", kind="info")
    return RedirectResponse(f"/members/{member_id}", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("demo_app.app:app", host="127.0.0.1", port=8001, reload=False)
