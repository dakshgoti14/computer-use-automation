"""Synthetic data for the demo back-office banking application.

Nothing here is real financial data. Member ids and balances exist purely
to exercise the automation lifecycle end-to-end, including its edge cases:

* ``12345`` / ``67890``  - normal members with distinct balances (the
  primary discovery/replay demo targets).
* ``99999``              - deliberately absent, to exercise the
  member-not-found business outcome.
* ``40404``              - triggers a server-side "unexpected error" page,
  to exercise hard-failure handling.
* ``50000``              - forces the current session to expire the moment
  its detail page is requested, to exercise the recoverable
  session-timeout path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class Member:
    member_id: str
    name: str
    status: str
    savings_balance: str
    checking_balance: str


MEMBERS: dict[str, Member] = {
    "12345": Member("12345", "Jordan Alvarez", "Active", "4,231.55", "1,204.10"),
    "67890": Member("67890", "Priya Natarajan", "Active", "812.00", "305.40"),
    "24680": Member("24680", "Sam Whitfield", "Dormant", "0.00", "0.00"),
    "13579": Member("13579", "Alex Rivera", "Active", "0.00", "0.00"),
    # Findable via search (so a capability can reach its detail page), but
    # viewing its detail page always forces a session-timeout condition -
    # see TIMEOUT_TRIGGER_MEMBER_ID handling in demo_app/app.py.
    "50000": Member("50000", "Terry Session", "Active", "0.00", "0.00"),
}

#: Member id that always triggers a simulated unexpected server error.
ERROR_TRIGGER_MEMBER_ID = "40404"

#: Member id that always triggers a simulated session expiry.
TIMEOUT_TRIGGER_MEMBER_ID = "50000"


def rand_suffix() -> str:
    """Non-semantic suffix applied to cosmetic wrapper elements only.

    Simulates the "unstable DOM" requirement: functional controls always
    carry a stable role/label/data-testid, but decorative wrapper divs get a
    fresh class name on every render so a naive CSS-selector-only locator
    strategy would break between runs.
    """

    return uuid.uuid4().hex[:6]


@dataclass
class SessionState:
    authenticated: bool = False
    username: str | None = None
    forced_expired: bool = False
