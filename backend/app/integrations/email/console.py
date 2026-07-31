"""P1-ADR-05's development/test backend: prints the message instead of sending it, so
the suite never sends real mail and a developer can read a reset code straight off the
terminal. §6.4/A.1's EMAIL_BACKEND default.
"""

from __future__ import annotations

from typing import ClassVar

from app.core.logging import get_logger
from app.integrations.email.base import EmailMessage

logger = get_logger(__name__)


class ConsoleEmailSender:
    """No network call. `logger.info` rather than `print` alone: the message is already
    structured (to/subject), and going through structlog keeps it in the same stream as
    every other log line during a dev run instead of interleaving unpredictably with it.

    `sent` is a class-level list, not instance state: `get_email_sender()` builds a new
    instance per call, and an integration test needs to read back the code a background
    task just "sent" without scraping stdout or reaching past the HTTP boundary into the
    database pepper. Tests call `ConsoleEmailSender.reset()` between cases the same way
    they already reset the rate limiter singleton.
    """

    sent: ClassVar[list[EmailMessage]] = []

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "email_dispatched",
            backend="console",
            to=message.to,
            subject=message.subject,
        )
        print(f"\n----- EMAIL to {message.to} -----")
        print(f"Subject: {message.subject}")
        print(message.html_body)
        print("----- END EMAIL -----\n")
        ConsoleEmailSender.sent.append(message)

    @classmethod
    def reset(cls) -> None:
        """Clear the record. For tests, and for nothing else."""
        cls.sent.clear()
