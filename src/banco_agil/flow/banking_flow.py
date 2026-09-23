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
from banco_agil.models.domain import CreditRequestStatus, InformationTopic
from banco_agil.models.errors import (
    BankingError,
    ExchangeServiceUnavailableError,
    InvalidCreditLimitError,
    InvalidCurrencyError,
    LLMStructuredOutputError,
)
from banco_agil.models.responses import (
    CriticalFailure,
    CriticalFailureCode,
    FlowOutcome,
    NextStep,
    OutcomeDirective,
    ResponseEvent,
)
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

    async def process(self, result: TurnResult) -> FlowOutcome | CriticalFailure:
        if self.state.status == ConversationStatus.FINISHED:
            return CriticalFailure(code=CriticalFailureCode.SESSION_FINISHED)
        if not isinstance(result, OUTPUT_TYPES[self.state.current_agent]):
            self.state.last_error_code = LLMStructuredOutputError.code
            record(
                Event.OPERATION_FAILED,
                self.state.session_id,
                error_code=LLMStructuredOutputError.code,
            )
            return CriticalFailure(code=CriticalFailureCode.INVALID_LLM_OUTPUT)
        self._checkpoint()
        self._turn_result = result
        try:
            self.state.last_error_code = None
            return await self.kickoff_async()
        except BankingError as exc:
            for name in SessionState.model_fields:
                setattr(self.state, name, getattr(self._rollback_state, name))
            self.state.last_error_code = exc.code
            record(Event.OPERATION_FAILED, self.state.session_id, error_code=exc.code)
            if isinstance(exc, ExchangeServiceUnavailableError):
                return CriticalFailure(code=CriticalFailureCode.EXTERNAL_SERVICE_UNAVAILABLE)
            if exc.critical_failure_code is not None:
                return CriticalFailure(code=exc.critical_failure_code)
            if isinstance(exc, LLMStructuredOutputError):
                return CriticalFailure(code=CriticalFailureCode.INVALID_LLM_OUTPUT)
            return CriticalFailure(code=CriticalFailureCode.INVALID_INTERNAL_STATE)
        finally:
            self._turn_result = None
            self._rollback_state = None

    def _checkpoint(self) -> None:
        self._rollback_state = self.state.model_copy(deep=True)

    @start()
    async def dispatch(self) -> FlowOutcome | CriticalFailure:
        result = self._turn_result
        if result is None:
            raise LLMStructuredOutputError()
        if (
            result.end_requested
            or getattr(result, "transition_request", None) == TransitionIntent.END_CONVERSATION
            or getattr(result, "detected_intent", None) == IntentType.END_CONVERSATION
        ):
            transition(self.state, await self._tools.execute("end_conversation"))
            return self._outcome(
                self.state.current_agent,
                ResponseEvent.CONVERSATION_CLOSED,
                next_step=NextStep.FINISHED,
            )
        if result.information_topic is not None:
            return self._service_information(result.information_topic)
        if self.state.current_agent == AgentType.TRIAGE:
            return await self._triage(result)
        return await self._specialist(result)

    async def _triage(self, result: TriageTurnResult) -> FlowOutcome | CriticalFailure:
        state = self.state
        prefix = None
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
                if state.pending_intent is None and state.authentication.birth_date is None:
                    return self._outcome(
                        AgentType.TRIAGE, ResponseEvent.WELCOME, expected_questions=1
                    )
                return self._outcome(
                    AgentType.TRIAGE,
                    ResponseEvent.REQUEST_CPF,
                    next_step=NextStep.AWAIT_CPF,
                    expected_questions=1,
                )
            if state.authentication.birth_date is None:
                return self._outcome(
                    AgentType.TRIAGE,
                    ResponseEvent.REQUEST_BIRTH_DATE,
                    next_step=NextStep.AWAIT_BIRTH_DATE,
                    expected_questions=1,
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
                    return CriticalFailure(code=CriticalFailureCode.AUTH_ATTEMPTS_EXHAUSTED)
                return FlowOutcome(
                    directives=(
                        OutcomeDirective(
                            event=ResponseEvent.AUTHENTICATION_RETRY,
                            public_context={
                                "remaining_attempts": 3 - state.authentication_attempts
                            },
                        ),
                        OutcomeDirective(event=ResponseEvent.RESUME_PENDING_STEP),
                    ),
                    specialist=AgentType.TRIAGE,
                    next_step=NextStep.AWAIT_CPF,
                    expected_questions=1,
                )
            state.authenticated_customer_cpf = customer.cpf
            state.authenticated = True
            state.authentication_attempts = 0
            prefix = self._outcome(
                AgentType.TRIAGE,
                ResponseEvent.AUTHENTICATION_SUCCEEDED,
                protected_values={"customer_first_name": customer.nome.split(maxsplit=1)[0]},
            )
            record(Event.AUTHENTICATION_SUCCEEDED, state.session_id)
            self._checkpoint()
        return await self._resume_intent(prefix)

    def _service_information(self, topic: InformationTopic) -> FlowOutcome:
        # O tópico é a única informação pública; fatos e texto ficam no catálogo.
        topic = InformationTopic(topic)
        next_step = self._pending_question()
        directives = [
            OutcomeDirective(
                event=ResponseEvent.SERVICE_INFORMATION,
                public_context={"topic": topic.value},
            )
        ]
        if next_step != NextStep.IDLE:
            context = {}
            if next_step == NextStep.AWAIT_INTERVIEW_FIELD:
                context = {"field": self.state.interview.next_missing_field()}
            directives.append(
                OutcomeDirective(event=ResponseEvent.RESUME_PENDING_STEP, public_context=context)
            )
        return FlowOutcome(
            directives=tuple(directives),
            specialist=self.state.current_agent,
            next_step=next_step,
            expected_questions=int(next_step != NextStep.IDLE),
        )

    def _pending_question(self) -> NextStep:
        state = self.state
        if not state.authenticated:
            if state.authentication.cpf is not None and state.authentication.birth_date is None:
                return NextStep.AWAIT_BIRTH_DATE
            if state.authentication.birth_date is not None or state.pending_intent is not None:
                return NextStep.AWAIT_CPF
        if state.current_agent == AgentType.CREDIT:
            if state.credit.awaiting_requested_limit:
                return NextStep.AWAIT_REQUESTED_LIMIT
            if state.credit.awaiting_interview_confirmation:
                return NextStep.AWAIT_INTERVIEW_CONFIRMATION
        if state.current_agent == AgentType.INTERVIEW and state.interview is not None:
            if state.interview.next_missing_field() is not None:
                return NextStep.AWAIT_INTERVIEW_FIELD
        if state.current_agent == AgentType.EXCHANGE:
            return NextStep.AWAIT_CURRENCY
        return NextStep.IDLE

    async def _resume_intent(
        self, prefix: FlowOutcome | None = None
    ) -> FlowOutcome | CriticalFailure:
        intent = self.state.pending_intent
        if intent in (IntentType.CREDIT_LIMIT_QUERY, IntentType.CREDIT_LIMIT_INCREASE):
            transition(self.state, TransitionIntent.GO_TO_CREDIT)
            self.state.pending_intent = None
            response = await self._credit(
                CreditTurnResult(
                    detected_intent=intent, requested_limit=self.state.credit.requested_limit
                )
            )
        elif intent == IntentType.EXCHANGE_RATE:
            transition(self.state, TransitionIntent.GO_TO_EXCHANGE)
            self.state.pending_intent = None
            currency = self.state.pending_currency
            self.state.pending_currency = None
            response = await self._exchange(ExchangeTurnResult(currency=currency))
        else:
            response = self._outcome(
                AgentType.TRIAGE, ResponseEvent.SHOW_OPTIONS, expected_questions=1
            )
        if prefix is None or isinstance(response, CriticalFailure):
            return response
        protected_values = dict(prefix.protected_values)
        for key, value in response.protected_values.items():
            if key in protected_values and protected_values[key] != value:
                self.state.last_error_code = CriticalFailureCode.INVALID_INTERNAL_STATE.value
                record(
                    Event.OPERATION_FAILED,
                    self.state.session_id,
                    error_code=self.state.last_error_code,
                )
                return CriticalFailure(code=CriticalFailureCode.INVALID_INTERNAL_STATE)
            protected_values[key] = value
        return response.model_copy(
            update={
                "directives": (*prefix.directives, *response.directives),
                "protected_values": protected_values,
            }
        )

    async def _specialist(self, result: TurnResult) -> FlowOutcome | CriticalFailure:
        if self.state.current_agent == AgentType.CREDIT:
            return await self._credit(result)
        if self.state.current_agent == AgentType.EXCHANGE:
            return await self._exchange(result)
        if self.state.current_agent == AgentType.INTERVIEW:
            return await self._interview(result)
        raise LLMStructuredOutputError()

    @staticmethod
    def _outcome(
        specialist: AgentType,
        *events: ResponseEvent,
        protected_values: dict[str, str] | None = None,
        next_step: NextStep = NextStep.IDLE,
        expected_questions: int = 0,
    ) -> FlowOutcome:
        return FlowOutcome(
            directives=tuple(OutcomeDirective(event=event) for event in events),
            specialist=specialist,
            protected_values=protected_values or {},
            next_step=next_step,
            expected_questions=expected_questions,
        )

    @staticmethod
    def _money(value) -> str:
        return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

    async def _credit(self, result: CreditTurnResult) -> FlowOutcome | CriticalFailure:
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
            question = self._interview_question_outcome()
            return question.model_copy(
                update={
                    "directives": (
                        OutcomeDirective(event=ResponseEvent.INTERVIEW_STARTED),
                        *question.directives,
                    )
                }
            )
        if result.transition_request == TransitionIntent.START_CREDIT_INTERVIEW:
            # Pedir a transição sem aceite explícito não autoriza iniciar a entrevista.
            transition(self.state, result.transition_request, accepted=False)
        if result.interview_accepted is False and credit.awaiting_interview_confirmation:
            credit.awaiting_interview_confirmation = False
            return self._complete_operation(
                self._outcome(
                    AgentType.CREDIT,
                    ResponseEvent.CREDIT_INCREASE_REJECTED_FINAL,
                )
            )
        if result.detected_intent == IntentType.CREDIT_LIMIT_QUERY:
            limit = await self._tools.execute("get_credit_limit")
            return self._complete_operation(
                self._outcome(
                    AgentType.CREDIT,
                    ResponseEvent.CREDIT_LIMIT_FOUND,
                    protected_values={"current_limit": self._money(limit)},
                )
            )
        if result.detected_intent == IntentType.CREDIT_LIMIT_INCREASE:
            credit.awaiting_requested_limit = True
            credit.requested_limit = result.requested_limit
        if result.requested_limit is not None:
            credit.requested_limit = result.requested_limit
            credit.awaiting_requested_limit = True
        if credit.awaiting_requested_limit:
            if result.requested_limit is None and credit.requested_limit is None:
                return self._outcome(
                    AgentType.CREDIT,
                    ResponseEvent.REQUEST_CREDIT_LIMIT,
                    next_step=NextStep.AWAIT_REQUESTED_LIMIT,
                    expected_questions=1,
                )
            return await self._evaluate_credit()
        if credit.awaiting_interview_confirmation:
            return self._outcome(
                AgentType.CREDIT,
                ResponseEvent.CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW,
                next_step=NextStep.AWAIT_INTERVIEW_CONFIRMATION,
                expected_questions=1,
            )
        return self._outcome(
            AgentType.TRIAGE,
            ResponseEvent.SHOW_OPTIONS,
            expected_questions=1,
        )

    def _interview_question_outcome(self) -> FlowOutcome:
        field = self.state.interview.next_missing_field()
        return FlowOutcome(
            directives=(
                OutcomeDirective(
                    event=ResponseEvent.INTERVIEW_QUESTION,
                    public_context={"field": field},
                ),
            ),
            specialist=AgentType.INTERVIEW,
            next_step=NextStep.AWAIT_INTERVIEW_FIELD,
            expected_questions=1,
        )

    def _complete_operation(self, response: FlowOutcome) -> FlowOutcome:
        self.state.pending_intent = None
        self.state.pending_currency = None
        self.state.credit.requested_limit = None
        self.state.credit.awaiting_requested_limit = False
        self.state.credit.awaiting_interview_confirmation = False
        self.state.credit.reanalysis_pending = False
        transition(self.state, TransitionIntent.RETURN_TO_TRIAGE, operation_completed=True)
        return response

    async def _interview(self, result: InterviewTurnResult) -> FlowOutcome | CriticalFailure:
        interview = self.state.interview
        if interview is None:
            raise LLMStructuredOutputError()
        field = interview.next_missing_field()
        if field is not None:
            value = getattr(result, field)
            if value is None:
                return self._interview_question_outcome()
            setattr(interview, field, value)
        if not interview.is_complete():
            return self._interview_question_outcome()
        await self._tools.execute("submit_credit_interview")
        interview.score_persisted = True
        interview.completed = True
        record(Event.CREDIT_SCORE_UPDATED, self.state.session_id)
        transition(self.state, TransitionIntent.RETURN_TO_CREDIT)
        self.state.credit.awaiting_requested_limit = True
        self.state.credit.reanalysis_pending = True
        self._checkpoint()
        return await self._evaluate_credit()

    async def _evaluate_credit(self) -> FlowOutcome | CriticalFailure:
        credit = self.state.credit
        is_reanalysis = credit.reanalysis_pending
        try:
            result = await self._tools.execute(
                "request_credit_limit_increase", requested_limit=credit.requested_limit
            )
        except InvalidCreditLimitError as exc:
            credit.requested_limit = None
            credit.awaiting_requested_limit = True
            self.state.last_error_code = exc.code
            record(Event.OPERATION_FAILED, self.state.session_id, error_code=exc.code)
            return self._outcome(
                AgentType.CREDIT,
                ResponseEvent.INVALID_INPUT,
                ResponseEvent.RESUME_PENDING_STEP,
                next_step=NextStep.AWAIT_REQUESTED_LIMIT,
                expected_questions=1,
            )
        credit.last_request_status = result.status_pedido
        record(Event.CREDIT_REQUEST_EVALUATED, self.state.session_id, status=result.status_pedido)
        credit.awaiting_requested_limit = False
        interview_completed = self.state.interview is not None and self.state.interview.completed
        credit.awaiting_interview_confirmation = (
            result.status_pedido == CreditRequestStatus.REJECTED and not interview_completed
        )
        if result.status_pedido == CreditRequestStatus.APPROVED:
            return self._complete_operation(
                self._outcome(
                    AgentType.CREDIT,
                    ResponseEvent.INTERVIEW_REANALYSIS_APPROVED
                    if is_reanalysis
                    else ResponseEvent.CREDIT_INCREASE_APPROVED,
                    protected_values={"new_limit": self._money(result.novo_limite_solicitado)},
                )
            )
        if is_reanalysis or interview_completed:
            return self._complete_operation(
                self._outcome(
                    AgentType.CREDIT,
                    ResponseEvent.INTERVIEW_REANALYSIS_REJECTED
                    if is_reanalysis
                    else ResponseEvent.CREDIT_INCREASE_REJECTED_FINAL,
                )
            )
        return self._outcome(
            AgentType.CREDIT,
            ResponseEvent.CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW,
            next_step=NextStep.AWAIT_INTERVIEW_CONFIRMATION,
            expected_questions=1,
        )

    async def _exchange(self, result: ExchangeTurnResult) -> FlowOutcome | CriticalFailure:
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
            return self._outcome(
                AgentType.EXCHANGE,
                ResponseEvent.REQUEST_CURRENCY,
                next_step=NextStep.AWAIT_CURRENCY,
                expected_questions=1,
            )
        try:
            quote = await self._tools.execute("get_exchange_rate", currency=result.currency)
        except InvalidCurrencyError as exc:
            self.state.last_error_code = exc.code
            record(Event.OPERATION_FAILED, self.state.session_id, error_code=exc.code)
            return self._outcome(
                AgentType.EXCHANGE,
                ResponseEvent.UNSUPPORTED_CURRENCY,
                next_step=NextStep.AWAIT_CURRENCY,
                expected_questions=1,
            )
        timestamp = (
            f"\n\nAtualizada em {quote.quoted_at:%d/%m/%Y às %H:%M} UTC." if quote.quoted_at else ""
        )
        interrupted_credit = self.state.credit.awaiting_requested_limit
        return self._complete_operation(
            FlowOutcome(
                directives=(
                    OutcomeDirective(
                        event=ResponseEvent.EXCHANGE_QUOTE_FOUND,
                        public_context={"credit_request_interrupted": True}
                        if interrupted_credit
                        else {},
                    ),
                ),
                specialist=AgentType.EXCHANGE,
                protected_values={
                    "exchange_rate": f"1 {quote.currency} = R$ {quote.bid:.4f}",
                    "quote_timestamp": timestamp,
                },
                next_step=NextStep.IDLE,
                expected_questions=0,
            )
        )
