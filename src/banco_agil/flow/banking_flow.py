from pathlib import Path

from crewai.flow.flow import Flow, start
from pydantic import PrivateAttr

from banco_agil.flow.transitions import transition
from banco_agil.models.agent_outputs import OUTPUT_TYPES, TriageTurnResult, TurnResult
from banco_agil.models.errors import BankingError, LLMStructuredOutputError
from banco_agil.models.state import (
    AgentType,
    AuthenticationContext,
    ConversationStatus,
    IntentType,
    SessionState,
    TransitionIntent,
)
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.authentication_service import AuthenticationService
from banco_agil.services.credit_service import CreditService
from banco_agil.services.exchange_service import ExchangeService
from banco_agil.services.score_service import ScoreService
from banco_agil.tools.session_tools import SessionTools


class BankingFlow(Flow[SessionState]):
    _tools: SessionTools = PrivateAttr()
    _turn_result: TurnResult | None = PrivateAttr(default=None)

    def __init__(self, data_dir: Path, exchange: ExchangeService | None = None, **kwargs):
        super().__init__(
            initial_state=SessionState(), tracing=False, suppress_flow_events=True, **kwargs
        )
        customers = CustomerRepository(data_dir)
        credit = CreditService(customers)
        self._tools = SessionTools(
            lambda: self.state,
            AuthenticationService(customers),
            credit,
            ScoreService(customers, credit),
            exchange or ExchangeService(),
        )

    async def process(self, result: TurnResult) -> str:
        if self.state.status == ConversationStatus.FINISHED:
            return "Este atendimento foi encerrado. Inicie uma nova conversa para continuar."
        if not isinstance(result, OUTPUT_TYPES[self.state.current_agent]):
            return LLMStructuredOutputError.user_message
        snapshot = self.state.model_copy(deep=True)
        self._turn_result = result
        try:
            response = await self.kickoff_async()
            self.state.last_error_code = None
            return response
        except BankingError as exc:
            for name in SessionState.model_fields:
                setattr(self.state, name, getattr(snapshot, name))
            self.state.last_error_code = exc.code
            return exc.user_message
        finally:
            self._turn_result = None

    @start()
    async def dispatch(self) -> str:
        result = self._turn_result
        if result is None:
            raise LLMStructuredOutputError()
        if (
            result.end_requested
            or getattr(result, "detected_intent", None) == IntentType.END_CONVERSATION
        ):
            transition(self.state, self._tools.end_conversation())
            return "Atendimento encerrado. Obrigado por conversar com o Banco Ágil!"
        if self.state.current_agent == AgentType.TRIAGE:
            return await self._triage(result)
        return await self._specialist(result)

    async def _triage(self, result: TriageTurnResult) -> str:
        state = self.state
        if result.detected_intent not in (None, IntentType.UNKNOWN):
            state.pending_intent = result.detected_intent
        if result.requested_limit is not None:
            state.credit.requested_limit = result.requested_limit
        if result.currency is not None:
            state.pending_currency = result.currency
        if not state.authenticated:
            if result.cpf is not None:
                state.authentication.cpf = result.cpf
            if result.birth_date is not None:
                state.authentication.birth_date = result.birth_date
            if state.authentication.cpf is None:
                return "Para começar, informe seu CPF."
            if state.authentication.birth_date is None:
                return "Qual é sua data de nascimento? Informe dia, mês e ano."
            customer = self._tools.authenticate_customer(
                state.authentication.cpf, state.authentication.birth_date
            )
            state.authentication = AuthenticationContext()
            if customer is None:
                state.authentication_attempts += 1
                if state.authentication_attempts >= 3:
                    transition(state, TransitionIntent.END_CONVERSATION)
                    return (
                        "Não foi possível confirmar seus dados após três tentativas. "
                        "Atendimento encerrado."
                    )
                return "Não consegui confirmar seus dados. Informe novamente seu CPF e nascimento."
            state.authenticated_customer_cpf = customer.cpf
            state.authenticated = True
            state.authentication_attempts = 0
        return await self._resume_intent()

    async def _resume_intent(self) -> str:
        return (
            "Identidade confirmada. Você quer consultar seu limite, "
            "pedir um aumento ou uma cotação?"
        )

    async def _specialist(self, result: TurnResult) -> str:
        raise LLMStructuredOutputError()
