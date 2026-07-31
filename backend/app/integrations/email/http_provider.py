"""P1-ADR-05's production backend, selected by `EMAIL_BACKEND=http` (§12 T-07 /
§13.1 item 4). Structurally complete but not exercised in Phase 1: no provider account
exists yet, EMAIL_BACKEND stays "console", and no test calls this over the network --
only `httpx` is used, never a provider SDK, so Appendix A.2 is respected and swapping
Resend for Brevo later is a change to this one file's request shape, not to any caller.

Modelled on Resend's REST API (§13.1 item 4's recommendation) since it needs no
provider-specific SDK, only a bearer-authenticated JSON POST -- the same shape Brevo's
transactional endpoint uses closely enough that switching stays a one-file change.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.integrations.email.base import EmailMessage

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_REQUEST_TIMEOUT_SECONDS = 10.0


class HttpEmailSender:
    """One HTTP call per `send`. `settings.EMAIL_API_KEY` is validated as required
    whenever `EMAIL_BACKEND=http` by `config.py`'s cross-field check, so it is never
    None on this path -- see that check's docstring for why the failure belongs there,
    at startup, rather than as a per-request None check here.
    """

    async def send(self, message: EmailMessage) -> None:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.EMAIL_API_KEY}"},
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [message.to],
                    "subject": message.subject,
                    "html": message.html_body,
                },
            )
            response.raise_for_status()
