"""Importing this package registers every model on Base.metadata (app.database.Base)."""

from app.models.audit import AuditLog
from app.models.body_weight import BodyWeightEntry
from app.models.exercise import Exercise
from app.models.identity import UserIdentity
from app.models.profile import Profile
from app.models.program import Program, ProgramDay, ProgramExercise
from app.models.refresh_token import RefreshToken
from app.models.reset_code import PasswordResetCode
from app.models.user import User
from app.models.workout import WorkoutSession, WorkoutSet

__all__ = [
    "AuditLog",
    "BodyWeightEntry",
    "Exercise",
    "PasswordResetCode",
    "Profile",
    "Program",
    "ProgramDay",
    "ProgramExercise",
    "RefreshToken",
    "User",
    "UserIdentity",
    "WorkoutSession",
    "WorkoutSet",
]
