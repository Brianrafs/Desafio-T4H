from collections.abc import Callable
from datetime import date
from decimal import Decimal

from banco_agil.models.domain import FinancialProfile, SupportedCurrency
from banco_agil.models.errors import AuthorizationError
from banco_agil.models.state import AgentType, ConversationStatus, SessionState, TransitionIntent
from banco_agil.observability import Event, record
from banco_agil.services.authentication_service import AuthenticationService
from banco_agil.services.credit_service import CreditService
from banco_agil.services.exchange_service import ExchangeService
from banco_agil.services.score_service import ScoreService

TOOL_SCOPES = {
    AgentType.TRIAGE: ("authenticate_customer", "end_conversation"),
    AgentType.CREDIT: ("get_credit_limit", "request_credit_limit_increase", "end_conversation"),
    AgentType.INTERVIEW: ("submit_credit_interview", "end_conversation"),
    AgentType.EXCHANGE: ("get_exchange_rate", "end_conversation"),
}


class SessionTools:
    def __init__(
        self,
        state: Callable[[], SessionState],
        authentication: AuthenticationService,
        credit: CreditService,
        score: ScoreService,
        exchange: ExchangeService,
    ):
        self._state = state
        self.authentication, self.credit = authentication, credit
        self.score, self.exchange = score, exchange

    def _authorize(self, name: str, protected: bool = True) -> SessionState:
        state = self._state()
        if (
            state.status != ConversationStatus.ACTIVE
            or name not in TOOL_SCOPES[state.current_agent]
        ):
            raise AuthorizationError()
        if protected and (not state.authenticated or not state.authenticated_customer_cpf):
            raise AuthorizationError()
        return state

    def authenticate_customer(self, cpf: str, birth_date: date):
        state = self._authorize("authenticate_customer", protected=False)
        if state.authenticated or state.authentication_attempts >= 3:
            raise AuthorizationError()
        record(Event.AUTHENTICATION_ATTEMPT, state.session_id)
        return self.authentication.authenticate(cpf, birth_date)

    def get_credit_limit(self):
        state = self._authorize("get_credit_limit")
        return self.credit.get_limit(state.authenticated_customer_cpf)

    def request_credit_limit_increase(self, requested_limit: Decimal):
        state = self._authorize("request_credit_limit_increase")
        if (
            not state.credit.awaiting_requested_limit
            or state.credit.requested_limit != requested_limit
        ):
            raise AuthorizationError()
        record(Event.CREDIT_LIMIT_REQUESTED, state.session_id)
        return self.credit.request_increase(state.authenticated_customer_cpf, requested_limit)

    def submit_credit_interview(self):
        state = self._authorize("submit_credit_interview")
        interview = state.interview
        if interview is None or not interview.is_complete() or interview.score_persisted:
            raise AuthorizationError()
        profile = FinancialProfile.model_validate(
            interview.model_dump(exclude={"completed", "score_persisted"})
        )
        return self.score.submit(state.authenticated_customer_cpf, profile)

    async def get_exchange_rate(self, currency: SupportedCurrency):
        state = self._authorize("get_exchange_rate")
        record(Event.EXCHANGE_RATE_REQUESTED, state.session_id)
        return await self.exchange.get_exchange_rate(currency)

    def end_conversation(self):
        self._authorize("end_conversation", protected=False)
        # Somente o Flow executa a transição solicitada.
        return TransitionIntent.END_CONVERSATION
