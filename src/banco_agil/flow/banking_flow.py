from pathlib import Path

from crewai.flow.flow import Flow, start
from pydantic import PrivateAttr

from banco_agil.flow.transitions import transition
from banco_agil.models.agent_outputs import (
    OUTPUT_TYPES,
    CreditTurnResult,
    ExchangeTurnResult,
    InterviewTurnResult,
    TriageTurnResult,
    TurnResult,
)
from banco_agil.models.domain import CreditRequestStatus
from banco_agil.models.errors import BankingError, LLMStructuredOutputError
from banco_agil.models.state import (
    AgentType,
    AuthenticationContext,
    ConversationStatus,
    CreditInterviewContext,
    IntentType,
    SessionState,
    TransitionIntent,
)
from banco_agil.observability import Event, configure_logging, record
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.authentication_service import AuthenticationService
from banco_agil.services.credit_service import CreditService
from banco_agil.services.exchange_service import ExchangeService
from banco_agil.services.score_service import ScoreService
from banco_agil.tools.session_tools import SessionTools


class BankingFlow(Flow[SessionState]):
    _tools: SessionTools = PrivateAttr()
    _turn_result: TurnResult | None = PrivateAttr(default=None)
    _rollback_state: SessionState | None = PrivateAttr(default=None)

    def __init__(self, data_dir: Path, exchange: ExchangeService | None = None, **kwargs):
        configure_logging()
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
        record(Event.SESSION_STARTED, self.state.session_id)

    @property
    def tools(self) -> SessionTools:
        return self._tools

    async def process(self, result: TurnResult) -> str:
        if self.state.status == ConversationStatus.FINISHED:
            return "Este atendimento foi encerrado. Inicie uma nova conversa para continuar."
        if not isinstance(result, OUTPUT_TYPES[self.state.current_agent]):
            return LLMStructuredOutputError.user_message
        self._checkpoint()
        self._turn_result = result
        try:
            response = await self.kickoff_async()
            self.state.last_error_code = None
            return response
        except BankingError as exc:
            for name in SessionState.model_fields:
                setattr(self.state, name, getattr(self._rollback_state, name))
            self.state.last_error_code = exc.code
            record(Event.OPERATION_FAILED, self.state.session_id, error_code=exc.code)
            return exc.user_message
        finally:
            self._turn_result = None
            self._rollback_state = None

    def _checkpoint(self) -> None:
        self._rollback_state = self.state.model_copy(deep=True)

    @start()
    async def dispatch(self) -> str:
        result = self._turn_result
        if result is None:
            raise LLMStructuredOutputError()
        if (
            result.end_requested
            or getattr(result, "transition_request", None) == TransitionIntent.END_CONVERSATION
            or getattr(result, "detected_intent", None) == IntentType.END_CONVERSATION
        ):
            transition(self.state, await self._tools.execute("end_conversation"))
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
            customer = await self._tools.execute(
                "authenticate_customer",
                cpf=state.authentication.cpf,
                birth_date=state.authentication.birth_date,
            )
            state.authentication = AuthenticationContext()
            if customer is None:
                record(Event.AUTHENTICATION_FAILED, state.session_id)
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
            record(Event.AUTHENTICATION_SUCCEEDED, state.session_id)
            self._checkpoint()
        return await self._resume_intent()

    async def _resume_intent(self) -> str:
        intent = self.state.pending_intent
        if intent in (IntentType.CREDIT_LIMIT_QUERY, IntentType.CREDIT_LIMIT_INCREASE):
            transition(self.state, TransitionIntent.GO_TO_CREDIT)
            self.state.pending_intent = None
            return await self._credit(
                CreditTurnResult(
                    detected_intent=intent, requested_limit=self.state.credit.requested_limit
                )
            )
        if intent == IntentType.EXCHANGE_RATE:
            transition(self.state, TransitionIntent.GO_TO_EXCHANGE)
            self.state.pending_intent = None
            currency = self.state.pending_currency
            self.state.pending_currency = None
            return await self._exchange(ExchangeTurnResult(currency=currency))
        return (
            "Identidade confirmada. Você quer consultar seu limite, "
            "pedir um aumento ou uma cotação?"
        )

    async def _specialist(self, result: TurnResult) -> str:
        if self.state.current_agent == AgentType.CREDIT:
            return await self._credit(result)
        if self.state.current_agent == AgentType.EXCHANGE:
            return await self._exchange(result)
        if self.state.current_agent == AgentType.INTERVIEW:
            return await self._interview(result)
        raise LLMStructuredOutputError()

    @staticmethod
    def _money(value) -> str:
        return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

    async def _credit(self, result: CreditTurnResult) -> str:
        if (
            result.transition_request == TransitionIntent.GO_TO_EXCHANGE
            or result.detected_intent == IntentType.EXCHANGE_RATE
        ):
            transition(self.state, TransitionIntent.GO_TO_EXCHANGE)
            return await self._exchange(ExchangeTurnResult(currency=result.currency))
        if result.transition_request not in (None, TransitionIntent.START_CREDIT_INTERVIEW):
            transition(self.state, result.transition_request)
        credit = self.state.credit
        if result.interview_accepted is True:
            transition(self.state, TransitionIntent.START_CREDIT_INTERVIEW, accepted=True)
            credit.awaiting_interview_confirmation = False
            self.state.interview = CreditInterviewContext()
            return self._interview_question()
        if result.transition_request == TransitionIntent.START_CREDIT_INTERVIEW:
            # Pedir a transição sem aceite explícito não autoriza iniciar a entrevista.
            transition(self.state, result.transition_request, accepted=False)
        if result.interview_accepted is False and credit.awaiting_interview_confirmation:
            credit.awaiting_interview_confirmation = False
            return "Tudo bem. Posso ajudar com uma consulta de limite ou de cotação."
        if result.detected_intent == IntentType.CREDIT_LIMIT_QUERY:
            limit = await self._tools.execute("get_credit_limit")
            return f"Seu limite atual é {self._money(limit)}."
        if result.detected_intent == IntentType.CREDIT_LIMIT_INCREASE:
            credit.awaiting_requested_limit = True
            credit.requested_limit = result.requested_limit
        if result.requested_limit is not None:
            credit.requested_limit = result.requested_limit
            credit.awaiting_requested_limit = True
        if credit.awaiting_requested_limit:
            if result.requested_limit is None and credit.requested_limit is None:
                return "Qual novo limite total você deseja solicitar?"
            return await self._evaluate_credit()
        return "Você quer consultar seu limite ou solicitar um aumento?"

    def _interview_question(self) -> str:
        questions = {
            "monthly_income": "Qual é sua renda mensal?",
            "employment_type": "Você tem emprego formal, é autônomo ou está desempregado?",
            "fixed_expenses": "Qual é o total das suas despesas fixas mensais?",
            "dependents": "Quantos dependentes você tem?",
            "has_active_debt": "Você tem alguma dívida ativa? Responda sim ou não.",
        }
        return questions[self.state.interview.next_missing_field()]

    async def _interview(self, result: InterviewTurnResult) -> str:
        interview = self.state.interview
        if interview is None:
            raise LLMStructuredOutputError()
        field = interview.next_missing_field()
        if field is not None:
            value = getattr(result, field)
            if value is None:
                return self._interview_question()
            setattr(interview, field, value)
        if not interview.is_complete():
            return self._interview_question()
        await self._tools.execute("submit_credit_interview")
        interview.score_persisted = True
        interview.completed = True
        record(Event.CREDIT_SCORE_UPDATED, self.state.session_id)
        transition(self.state, TransitionIntent.RETURN_TO_CREDIT)
        self.state.credit.awaiting_requested_limit = True
        self._checkpoint()
        return "Entrevista concluída. " + await self._evaluate_credit()

    async def _evaluate_credit(self) -> str:
        credit = self.state.credit
        result = await self._tools.execute(
            "request_credit_limit_increase", requested_limit=credit.requested_limit
        )
        credit.last_request_status = result.status_pedido
        record(Event.CREDIT_REQUEST_EVALUATED, self.state.session_id, status=result.status_pedido)
        credit.awaiting_requested_limit = False
        credit.awaiting_interview_confirmation = (
            result.status_pedido == CreditRequestStatus.REJECTED
        )
        if result.status_pedido == CreditRequestStatus.APPROVED:
            return (
                f"Pedido aprovado! Seu novo limite é {self._money(result.novo_limite_solicitado)}."
            )
        return (
            "Seu pedido não foi aprovado nesta análise. "
            "Quer responder a uma breve entrevista financeira para reavaliarmos o pedido?"
        )

    async def _exchange(self, result: ExchangeTurnResult) -> str:
        if result.transition_request == TransitionIntent.GO_TO_CREDIT or result.detected_intent in (
            IntentType.CREDIT_LIMIT_QUERY,
            IntentType.CREDIT_LIMIT_INCREASE,
        ):
            transition(self.state, TransitionIntent.GO_TO_CREDIT)
            return await self._credit(
                CreditTurnResult(
                    detected_intent=result.detected_intent, requested_limit=result.requested_limit
                )
            )
        if result.transition_request is not None:
            transition(self.state, result.transition_request)
        if result.currency is None:
            return "Qual moeda deseja consultar: dólar (USD), euro (EUR) ou libra (GBP)?"
        quote = await self._tools.execute("get_exchange_rate", currency=result.currency)
        timestamp = (
            f" Cotação de {quote.quoted_at:%d/%m/%Y às %H:%M} UTC." if quote.quoted_at else ""
        )
        return (
            f"1 {quote.currency} = R$ {quote.bid:.4f} (compra).{timestamp} "
            "Posso ajudar com mais alguma coisa?"
        )
