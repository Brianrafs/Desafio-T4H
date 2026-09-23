from datetime import date
from enum import StrEnum
from typing import ClassVar
from uuid import uuid4

from pydantic import Field

from banco_agil.models.domain import (
    CreditRequestStatus,
    EmploymentType,
    Model,
    Money,
    SupportedCurrency,
)


class AgentType(StrEnum):
    TRIAGE = "triage"
    CREDIT = "credit"
    INTERVIEW = "credit_interview"
    EXCHANGE = "exchange"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    FINISHED = "finished"


class IntentType(StrEnum):
    CREDIT_LIMIT_QUERY = "credit_limit_query"
    CREDIT_LIMIT_INCREASE = "credit_limit_increase"
    EXCHANGE_RATE = "exchange_rate"
    END_CONVERSATION = "end_conversation"
    UNKNOWN = "unknown"


class TransitionIntent(StrEnum):
    RETURN_TO_TRIAGE = "return_to_triage"
    GO_TO_CREDIT = "go_to_credit"
    GO_TO_EXCHANGE = "go_to_exchange"
    START_CREDIT_INTERVIEW = "start_credit_interview"
    RETURN_TO_CREDIT = "return_to_credit"
    END_CONVERSATION = "end_conversation"


class AuthenticationContext(Model):
    cpf: str | None = None
    birth_date: date | None = None


class CreditConversationContext(Model):
    requested_limit: Money | None = None
    awaiting_requested_limit: bool = False
    awaiting_interview_confirmation: bool = False
    last_request_status: CreditRequestStatus | None = None


class CreditInterviewContext(Model):
    FIELDS: ClassVar[tuple[str, ...]] = (
        "monthly_income",
        "employment_type",
        "fixed_expenses",
        "dependents",
        "has_active_debt",
    )

    monthly_income: Money | None = None
    employment_type: EmploymentType | None = None
    fixed_expenses: Money | None = None
    dependents: int | None = Field(default=None, ge=0, strict=True)
    has_active_debt: bool | None = Field(default=None, strict=True)
    completed: bool = False
    score_persisted: bool = False

    def next_missing_field(self) -> str | None:
        for field in self.FIELDS:
            if getattr(self, field) is None:
                return field
        return None

    def completed_fields(self) -> int:
        return sum(getattr(self, field) is not None for field in self.FIELDS)

    @classmethod
    def total_fields(cls) -> int:
        return len(cls.FIELDS)

    def is_complete(self) -> bool:
        return self.next_missing_field() is None


class SessionState(Model):
    # CrewAI usa `id` para identificar o estado tipado.
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: ConversationStatus = ConversationStatus.ACTIVE
    current_agent: AgentType = AgentType.TRIAGE
    authenticated: bool = False
    authenticated_customer_cpf: str | None = None
    authentication_attempts: int = Field(default=0, ge=0, le=3)
    authentication: AuthenticationContext = Field(default_factory=AuthenticationContext)
    pending_intent: IntentType | None = None
    pending_currency: SupportedCurrency | None = None
    credit: CreditConversationContext = Field(default_factory=CreditConversationContext)
    interview: CreditInterviewContext | None = None
    last_error_code: str | None = None

    @property
    def session_id(self) -> str:
        return self.id
