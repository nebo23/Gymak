"""P1-ADR-05: email delivery sits behind an interface, with a console backend for
development and an HTTP backend for the production provider. No application code
imports a provider SDK directly (§13.1 item 4 picks Resend or Brevo, unset in Phase 1);
swapping the provider is a one-file change behind `get_email_sender()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    html_body: str


def render_template(name: str, language: str, **params: str) -> str:
    """Loads `templates/{name}.{language}.html` and substitutes `{{KEY}}` placeholders.
    Appendix A.2 does not permit Jinja2 (or any template engine) in this codebase, and
    the handful of values these templates ever need (a code, a TTL) do not warrant one
    -- plain `str.replace` is the whole templating layer.
    """
    html = (_TEMPLATES_DIR / f"{name}.{language}.html").read_text(encoding="utf-8")
    for key, value in params.items():
        html = html.replace(f"{{{{{key}}}}}", value)
    return html


class EmailSender(Protocol):
    """One method, per §12 T-07 / ADR-05. Implementations raise on failure; callers
    (password_reset_service, dispatched on a FastAPI background task) decide whether a
    failure is worth logging or swallowing -- this interface makes no such judgment.
    """

    async def send(self, message: EmailMessage) -> None: ...


def get_email_sender() -> EmailSender:
    """Selects the implementation by `EMAIL_BACKEND` (§6.4/A.1). The only place that
    reads this setting to make that decision -- callers ask for "the sender", never for
    a concrete class, so EMAIL_BACKEND=console (Phase 1's setting) versus =http is a
    config change, not a code change at any call site.
    """
    from app.config import settings

    if settings.EMAIL_BACKEND == "http":
        from app.integrations.email.http_provider import HttpEmailSender

        return HttpEmailSender()

    from app.integrations.email.console import ConsoleEmailSender

    return ConsoleEmailSender()
