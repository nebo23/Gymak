from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

PROBLEM_CONTENT_TYPE = "application/problem+json"
ERROR_TYPE_BASE = "https://api.gymak.fitness/errors"

logger = get_logger(__name__)


class AppError(Exception):
    """Base of every error the API can raise. code/status/title are the contract in spec 7.2."""

    code: str = "INTERNAL_ERROR"
    status: int = 500
    title: str = "Something went wrong"

    def __init__(
        self,
        detail: str | None = None,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        self.detail = detail
        self.errors = errors or []
        super().__init__(self.code)


# --- one subclass per code in spec 7.3, in table order ---------------------------------


class MalformedBodyError(AppError):
    code = "MALFORMED_BODY"
    status = 400
    title = "The request body could not be parsed"


class ProviderNotSupportedError(AppError):
    code = "PROVIDER_NOT_SUPPORTED"
    status = 400
    title = "The social provider in the path is not supported"


class InvalidCredentialsError(AppError):
    code = "INVALID_CREDENTIALS"
    status = 401
    title = "Email or password is incorrect"


class TokenMissingError(AppError):
    code = "TOKEN_MISSING"
    status = 401
    title = "An access token is required"


class TokenExpiredError(AppError):
    code = "TOKEN_EXPIRED"
    status = 401
    title = "The access token has expired"


class TokenInvalidError(AppError):
    code = "TOKEN_INVALID"
    status = 401
    title = "The token is invalid"


class TokenReusedError(AppError):
    code = "TOKEN_REUSED"
    status = 401
    title = "This refresh token was already used"


class SocialTokenInvalidError(AppError):
    code = "SOCIAL_TOKEN_INVALID"
    status = 401
    title = "The social sign-in token could not be verified"


class ResetTokenInvalidError(AppError):
    code = "RESET_TOKEN_INVALID"
    status = 401
    title = "The password reset token is unknown, spent, or expired"


class AccountDisabledError(AppError):
    code = "ACCOUNT_DISABLED"
    status = 403
    title = "This account has been disabled"


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status = 404
    title = "The requested resource was not found"


class ProfileNotFoundError(AppError):
    code = "PROFILE_NOT_FOUND"
    status = 404
    title = "No profile exists for this account yet"


class EmailAlreadyRegisteredError(AppError):
    code = "EMAIL_ALREADY_REGISTERED"
    status = 409
    title = "An account with this email already exists"


class ProfileAlreadyExistsError(AppError):
    code = "PROFILE_ALREADY_EXISTS"
    status = 409
    title = "Onboarding has already been completed"


class IdentityAlreadyLinkedError(AppError):
    code = "IDENTITY_ALREADY_LINKED"
    status = 409
    title = "This social identity is linked to a different account"


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status = 422
    title = "One or more fields failed validation"


class GoalNotPermittedForMinorError(AppError):
    code = "GOAL_NOT_PERMITTED_FOR_MINOR"
    status = 422
    title = "This goal is not available for users under 18"


class ResetCodeInvalidError(AppError):
    code = "RESET_CODE_INVALID"
    status = 422
    title = "The reset code is incorrect or unknown"


class ResetCodeExpiredError(AppError):
    code = "RESET_CODE_EXPIRED"
    status = 422
    title = "The reset code has expired"


class RateLimitExceededError(AppError):
    code = "RATE_LIMIT_EXCEEDED"
    status = 429
    title = "Too many requests"


class ResetCodeAttemptsExceededError(AppError):
    code = "RESET_CODE_ATTEMPTS_EXCEEDED"
    status = 429
    title = "Too many incorrect attempts; this code is now burned"


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    status = 500
    title = "Something went wrong"


class UpstreamUnavailableError(AppError):
    code = "UPSTREAM_UNAVAILABLE"
    status = 503
    title = "A required upstream service is unavailable"


# --- the exception handler --------------------------------------------------------------


def _slug(code: str) -> str:
    return code.lower().replace("_", "-")


def _problem_response(error: AppError, trace_id: str) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_TYPE_BASE}/{_slug(error.code)}",
        "title": error.title,
        "status": error.status,
        "code": error.code,
        "trace_id": trace_id,
    }
    if error.detail:
        body["detail"] = error.detail
    if error.errors:
        body["errors"] = error.errors
    return JSONResponse(status_code=error.status, content=body, media_type=PROBLEM_CONTENT_TYPE)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None) or uuid.uuid4().hex.upper()
        return _problem_response(exc, trace_id)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None) or uuid.uuid4().hex.upper()
        logger.exception("unhandled_error", trace_id=trace_id, error_type=type(exc).__name__)
        return _problem_response(InternalError(), trace_id)
