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
from banco_agil.presentation import CLOSED, OPTIONS, WELCOME
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
            return CLOSED
        if not isinstance(result, OUTPUT_TYPES[self.state.current_agent]):
            self.state.last_error_code = LLMStructuredOutputError.code
            record(
                Event.OPERATION_FAILED,
                self.state.session_id,
                error_code=LLMStructuredOutputError.code,
            )
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
            return CLOSED
        if self.state.current_agent == AgentType.TRIAGE:
            return await self._triage(result)
        return await self._specialist(result)

    async def _triage(self, result: TriageTurnResult) -> str:
        state = self.state
        if result.detected_intent not in (None, IntentType.UNKNOWN):
            state.pending_intent = result.detected_intent
        if result.requested_limit is not None:
            state.credit.requested_limit = result.requested_limit
            if result.detected_intent in (None, IntentType.UNKNOWN):
                state.pending_intent = IntentType.CREDIT_LIMIT_INCREASE
        if result.currency is not None:
            state.pending_currency = result.currency
            if result.detected_intent in (None, IntentType.UNKNOWN):
                state.pending_intent = IntentType.EXCHANGE_RATE
        if not state.authenticated:
            if result.cpf is not None:
                state.authentication.cpf = result.cpf
            if result.birth_date is not None:
                state.authentication.birth_date = result.birth_date
            if state.authentication.cpf is None:
                if state.pending_intent is None:
                    return WELCOME
                return (
                    "Para cuidar do seu pedido, preciso primeiro confirmar sua identidade.\n\n"
                    "Pode me informar seu **CPF**?"
                )
            if state.authentication.birth_date is None:
                return (
                    "Agora, me diga sua **data de nascimento**, por favor.\n\n"
                    "Pode escrever no formato **dia/mês/ano**."
                )
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
                        "Não consegui confirmar seus dados nas **três tentativas**. "
                        "Por isso, preciso encerrar este atendimento.\n\n"
                        "Confira seu CPF e nascimento antes de iniciar uma **Nova conversa**. "
                        "Estarei por aqui para ajudar.\n\n**Lia · Banco Ágil**"
                    )
                remaining = 3 - state.authentication_attempts
                return (
                    "Os dados não coincidiram com o cadastro. Vamos conferir juntos?\n\n"
                    "Envie novamente seu **CPF** e sua **data de nascimento**.\n\n"
                    f"Tentativas restantes: **{remaining}**."
                )
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
        return "Estou aqui com você. Qual destas opções você prefere?\n\n" + OPTIONS

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
        if result.transition_request not in (
            None,
            TransitionIntent.START_CREDIT_INTERVIEW,
            TransitionIntent.GO_TO_CREDIT,
        ):
            transition(self.state, result.transition_request)
        credit = self.state.credit
        if result.interview_accepted is True:
            transition(self.state, TransitionIntent.START_CREDIT_INTERVIEW, accepted=True)
            credit.awaiting_interview_confirmation = False
            self.state.interview = CreditInterviewContext()
            return (
                "Vamos olhar sua situação com mais cuidado. "
                "São **cinco perguntas rápidas**, uma de cada vez.\n\n" + self._interview_question()
            )
        if result.transition_request == TransitionIntent.START_CREDIT_INTERVIEW:
            # Pedir a transição sem aceite explícito não autoriza iniciar a entrevista.
            transition(self.state, result.transition_request, accepted=False)
        if result.interview_accepted is False and credit.awaiting_interview_confirmation:
            credit.awaiting_interview_confirmation = False
            return self._complete_operation("Tudo bem. Podemos deixar a entrevista para depois.")
        if result.detected_intent == IntentType.CREDIT_LIMIT_QUERY:
            limit = await self._tools.execute("get_credit_limit")
            return self._complete_operation(
                f"Seu limite de crédito atual é **{self._money(limit)}**.\n\n"
                "Se quiser, também posso avaliar um aumento para você."
            )
        if result.detected_intent == IntentType.CREDIT_LIMIT_INCREASE:
            credit.awaiting_requested_limit = True
            credit.requested_limit = result.requested_limit
        if result.requested_limit is not None:
            credit.requested_limit = result.requested_limit
            credit.awaiting_requested_limit = True
        if credit.awaiting_requested_limit:
            if result.requested_limit is None and credit.requested_limit is None:
                return (
                    "Qual **limite total** você gostaria de ter?\n\n"
                    "Me diga o valor final desejado, não apenas quanto quer acrescentar."
                )
            return await self._evaluate_credit()
        if credit.awaiting_interview_confirmation:
            return (
                "Quer seguir com a **entrevista financeira** para reavaliar seu pedido?\n\n"
                "Pode responder **sim** ou **não**. "
                "Se preferir, também podemos consultar uma cotação."
            )
        return "Como posso ajudar agora?\n\n" + OPTIONS

    def _interview_question(self) -> str:
        questions = {
            "monthly_income": "Para começar, qual é sua **renda mensal**?",
            "employment_type": (
                "E como está sua **situação de trabalho** hoje?\n\n"
                "- Emprego formal, como CLT\n- Trabalho autônomo\n- Sem emprego no momento"
            ),
            "fixed_expenses": (
                "Quanto somam suas **despesas fixas por mês**, como aluguel, contas e alimentação?"
            ),
            "dependents": (
                "Quantas pessoas **dependem financeiramente de você**? Se nenhuma, diga **0**."
            ),
            "has_active_debt": (
                "Falta só uma pergunta: você tem alguma **dívida ativa**?\n\n"
                "Pode responder **sim** ou **não**."
            ),
        }
        return questions[self.state.interview.next_missing_field()]

    def _complete_operation(self, response: str) -> str:
        self.state.pending_intent = None
        self.state.pending_currency = None
        self.state.credit.requested_limit = None
        self.state.credit.awaiting_requested_limit = False
        self.state.credit.awaiting_interview_confirmation = False
        transition(self.state, TransitionIntent.RETURN_TO_TRIAGE, operation_completed=True)
        return response

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
        return await self._evaluate_credit()

    async def _evaluate_credit(self) -> str:
        credit = self.state.credit
        result = await self._tools.execute(
            "request_credit_limit_increase", requested_limit=credit.requested_limit
        )
        credit.last_request_status = result.status_pedido
        record(Event.CREDIT_REQUEST_EVALUATED, self.state.session_id, status=result.status_pedido)
        credit.awaiting_requested_limit = False
        interview_completed = self.state.interview is not None and self.state.interview.completed
        credit.awaiting_interview_confirmation = (
            result.status_pedido == CreditRequestStatus.REJECTED and not interview_completed
        )
        if result.status_pedido == CreditRequestStatus.APPROVED:
            if interview_completed:
                return self._complete_operation(
                    "Obrigada por responder às perguntas. Com as informações atualizadas, "
                    "seu pedido foi **aprovado**.\n\n"
                    f"Seu novo limite é **{self._money(result.novo_limite_solicitado)}** "
                    "e já está disponível."
                )
            return self._complete_operation(
                "Boa notícia: seu pedido foi **aprovado**.\n\n"
                f"Seu novo limite é **{self._money(result.novo_limite_solicitado)}** "
                "e já está disponível."
            )
        if interview_completed:
            return self._complete_operation(
                "Obrigada por responder às perguntas. Mesmo com as informações atualizadas, "
                "não consegui aprovar esse valor agora. Seu limite atual continua o mesmo.\n\n"
                "Se quiser, posso consultar seu limite ou ajudar com uma cotação."
            )
        return (
            "Não consegui aprovar esse valor agora, então seu limite continua o mesmo.\n\n"
            "Podemos fazer uma **entrevista financeira rápida** e analisar novamente com "
            "informações atualizadas. **Quer continuar?** Pode responder sim ou não."
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
        if result.transition_request not in (None, TransitionIntent.GO_TO_EXCHANGE):
            transition(self.state, result.transition_request)
        if result.currency is None:
            return (
                "Qual moeda você gostaria de consultar?\n\n"
                "- **Dólar** — USD\n- **Euro** — EUR\n- **Libra** — GBP\n\n"
                "Vou mostrar a cotação de compra em reais."
            )
        quote = await self._tools.execute("get_exchange_rate", currency=result.currency)
        timestamp = (
            f"\n\nAtualizada em {quote.quoted_at:%d/%m/%Y às %H:%M} UTC." if quote.quoted_at else ""
        )
        interrupted_credit = self.state.credit.awaiting_requested_limit
        body = (
            f"**Cotação de {quote.currency}**\n\n"
            f"**1 {quote.currency} = R$ {quote.bid:.4f}**\n\n"
            f"Valor de compra em reais.{timestamp}"
        )
        if interrupted_credit:
            body += (
                "\n\nSeu pedido de aumento ficou interrompido. "
                "Podemos consultar seu limite para conferir a situação antes de retomar o pedido."
            )
        else:
            body += "\n\nQuer consultar outra moeda ou falar sobre seu limite?"
        return self._complete_operation(body)
