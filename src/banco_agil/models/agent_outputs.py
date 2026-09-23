from datetime import date

from pydantic import Field

from banco_agil.models.domain import (
    EmploymentType,
    InformationTopic,
    Model,
    Money,
    SupportedCurrency,
)
from banco_agil.models.responses import UserTone
from banco_agil.models.state import IntentType, TransitionIntent


class TurnResult(Model):
    user_tone: UserTone = UserTone.NEUTRAL
    end_requested: bool = False
    information_topic: InformationTopic | None = None


class TriageTurnResult(TurnResult):
    detected_intent: IntentType | None = None
    transition_request: TransitionIntent | None = None
    cpf: str | None = None
    birth_date: date | None = None
    requested_limit: Money | None = None
    currency: SupportedCurrency | None = None


class CreditTurnResult(TurnResult):
    detected_intent: IntentType | None = None
    requested_limit: Money | None = None
    transition_request: TransitionIntent | None = None
    interview_accepted: bool | None = None
    currency: SupportedCurrency | None = None


class InterviewTurnResult(TurnResult):
    monthly_income: Money | None = None
    employment_type: EmploymentType | None = None
    fixed_expenses: Money | None = None
    dependents: int | None = Field(default=None, ge=0, strict=True)
    has_active_debt: bool | None = Field(default=None, strict=True)


class ExchangeTurnResult(TurnResult):
    detected_intent: IntentType | None = None
    currency: SupportedCurrency | None = None
    transition_request: TransitionIntent | None = None
    requested_limit: Money | None = None


OUTPUT_TYPES = {
    "triage": TriageTurnResult,
    "credit": CreditTurnResult,
    "credit_interview": InterviewTurnResult,
    "exchange": ExchangeTurnResult,
}
