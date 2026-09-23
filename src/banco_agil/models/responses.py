from enum import StrEnum

from pydantic import Field

from banco_agil.models.domain import Model
from banco_agil.models.state import AgentType


class UserTone(StrEnum):
    NEUTRAL = "neutral"
    UNCERTAIN = "uncertain"
    CONCERNED = "concerned"
    FRUSTRATED = "frustrated"
    POSITIVE = "positive"


class ResponseEvent(StrEnum):
    WELCOME = "welcome"
    SHOW_OPTIONS = "show_options"
    REQUEST_CPF = "request_cpf"
    REQUEST_BIRTH_DATE = "request_birth_date"
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_RETRY = "authentication_retry"
    CREDIT_LIMIT_FOUND = "credit_limit_found"
    REQUEST_CREDIT_LIMIT = "request_credit_limit"
    CREDIT_INCREASE_APPROVED = "credit_increase_approved"
    CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW = "credit_increase_rejected_offer_interview"
    CREDIT_INCREASE_REJECTED_FINAL = "credit_increase_rejected_final"
    INTERVIEW_STARTED = "interview_started"
    INTERVIEW_QUESTION = "interview_question"
    INTERVIEW_REANALYSIS_APPROVED = "interview_reanalysis_approved"
    INTERVIEW_REANALYSIS_REJECTED = "interview_reanalysis_rejected"
    REQUEST_CURRENCY = "request_currency"
    EXCHANGE_QUOTE_FOUND = "exchange_quote_found"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    SERVICE_INFORMATION = "service_information"
    RESUME_PENDING_STEP = "resume_pending_step"
    INVALID_INPUT = "invalid_input"
    CONVERSATION_CLOSED = "conversation_closed"


class ResponseAction(StrEnum):
    CONSULT_CREDIT_LIMIT = "consult_credit_limit"
    REQUEST_CREDIT_INCREASE = "request_credit_increase"
    START_CREDIT_INTERVIEW = "start_credit_interview"
    CONSULT_EXCHANGE_RATE = "consult_exchange_rate"
    END_CONVERSATION = "end_conversation"


class NextStep(StrEnum):
    AWAIT_CPF = "await_cpf"
    AWAIT_BIRTH_DATE = "await_birth_date"
    AWAIT_REQUESTED_LIMIT = "await_requested_limit"
    AWAIT_INTERVIEW_CONFIRMATION = "await_interview_confirmation"
    AWAIT_INTERVIEW_FIELD = "await_interview_field"
    AWAIT_CURRENCY = "await_currency"
    IDLE = "idle"
    FINISHED = "finished"


class CriticalFailureCode(StrEnum):
    LLM_UNAVAILABLE = "llm_unavailable"
    INVALID_LLM_OUTPUT = "invalid_llm_output"
    EXTERNAL_SERVICE_UNAVAILABLE = "external_service_unavailable"
    PERSISTENCE_FAILURE = "persistence_failure"
    AUTH_ATTEMPTS_EXHAUSTED = "auth_attempts_exhausted"
    SESSION_FINISHED = "session_finished"
    INVALID_INTERNAL_STATE = "invalid_internal_state"


class FallbackReason(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_SCHEMA = "invalid_schema"
    UNKNOWN_PLACEHOLDER = "unknown_placeholder"
    MISSING_PLACEHOLDER = "missing_placeholder"
    POLICY_REJECTED = "policy_rejected"


class OutcomeDirective(Model):
    event: ResponseEvent
    public_context: dict[str, str | int | bool] = Field(default_factory=dict)


class FlowOutcome(Model):
    directives: tuple[OutcomeDirective, ...] = Field(min_length=1)
    specialist: AgentType
    protected_values: dict[str, str] = Field(default_factory=dict)
    next_step: NextStep
    expected_questions: int = Field(default=0, ge=0, le=1)


class CriticalFailure(Model):
    code: CriticalFailureCode


class ResponseDirective(Model):
    event: ResponseEvent
    communication_goal: str = Field(min_length=1)
    public_context: dict[str, str | int | bool] = Field(default_factory=dict)


class ResponseBrief(Model):
    directives: tuple[ResponseDirective, ...] = Field(min_length=1)
    specialist: AgentType
    required_placeholders: frozenset[str] = frozenset()
    allowed_placeholders: frozenset[str] = frozenset()
    allowed_actions: tuple[ResponseAction, ...] = ()
    next_step: NextStep
    expected_questions: int = Field(ge=0, le=1)
    user_tone: UserTone
    constraints: tuple[str, ...] = ()


class ResponsePolicy(Model):
    required_placeholders: frozenset[str] = frozenset()
    allowed_placeholders: frozenset[str] = frozenset()
    expected_questions: int = Field(ge=0, le=1)
    max_length: int = Field(default=700, gt=0)
    forbidden_patterns: tuple[str, ...] = ()
    required_patterns: tuple[str, ...] = ()


class GeneratedMessage(Model):
    text: str = Field(min_length=1, max_length=700)


class RenderedResponse(Model):
    text: str = Field(min_length=1)
    used_fallback: bool
    fallback_reason: FallbackReason | None = None


class SafeConversationSummary(Model):
    events: tuple[ResponseEvent, ...] = Field(min_length=1)
    specialist: AgentType
    actions_offered: tuple[ResponseAction, ...] = ()
    next_step: NextStep
