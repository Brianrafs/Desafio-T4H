from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import OUTPUT_TYPES
from banco_agil.models.errors import LLMError, LLMStructuredOutputError
from banco_agil.models.responses import (
    CriticalFailure,
    CriticalFailureCode,
    FallbackReason,
    FlowOutcome,
    NextStep,
    OutcomeDirective,
    ResponseEvent,
    SafeConversationSummary,
    UserTone,
)
from banco_agil.models.state import ConversationStatus
from banco_agil.observability import Event, record
from banco_agil.providers.groq import LLMProvider
from banco_agil.responses.briefs import build_response_brief, safe_summary
from banco_agil.responses.catalog import CRITICAL_MESSAGES
from banco_agil.responses.renderer import render_response


class Conversation:
    def __init__(self, flow: BankingFlow, provider: LLMProvider):
        self.flow, self.provider = flow, provider
        self.last_summary: SafeConversationSummary | None = None

    async def start(self) -> str:
        outcome = FlowOutcome(
            directives=(OutcomeDirective(event=ResponseEvent.WELCOME),),
            specialist="triage",
            next_step=NextStep.IDLE,
            expected_questions=1,
        )
        return await self._render_outcome(outcome, UserTone.NEUTRAL)

    async def _render_outcome(self, outcome: FlowOutcome, user_tone: UserTone) -> str:
        brief = build_response_brief(outcome, user_tone)
        session_id = self.flow.state.session_id
        record(Event.RESPONSE_COMPOSITION_STARTED, session_id, agent=outcome.specialist)
        try:
            generated = await self.provider.compose(brief, previous_summary=self.last_summary)
            rendered = render_response(outcome, brief, generated)
        except LLMError as exc:
            rendered = render_response(
                outcome,
                brief,
                generated=None,
                fallback_reason=(
                    FallbackReason.INVALID_SCHEMA
                    if isinstance(exc, LLMStructuredOutputError)
                    else FallbackReason.PROVIDER_UNAVAILABLE
                ),
            )
        if rendered.used_fallback:
            if rendered.fallback_reason in {
                FallbackReason.UNKNOWN_PLACEHOLDER,
                FallbackReason.MISSING_PLACEHOLDER,
                FallbackReason.POLICY_REJECTED,
            }:
                record(
                    Event.RESPONSE_POLICY_REJECTED,
                    session_id,
                    agent=outcome.specialist,
                    reason=rendered.fallback_reason,
                )
            record(
                Event.RESPONSE_COMPOSITION_FALLBACK,
                session_id,
                agent=outcome.specialist,
                reason=rendered.fallback_reason,
            )
        else:
            record(Event.RESPONSE_COMPOSITION_SUCCEEDED, session_id, agent=outcome.specialist)
        self.last_summary = safe_summary(outcome, brief)
        return rendered.text

    async def send(self, message: str) -> str:
        if self.flow.state.status == ConversationStatus.FINISHED:
            return CRITICAL_MESSAGES[CriticalFailureCode.SESSION_FINISHED]
        # Comandos inequívocos continuam disponíveis mesmo com a Groq indisponível.
        if message.strip().casefold().rstrip(".!?") in {
            "sair",
            "encerrar",
            "encerrar atendimento",
            "finalizar",
            "fim",
            "tchau",
        }:
            result = OUTPUT_TYPES[self.flow.state.current_agent](end_requested=True)
        else:
            try:
                result = await self.provider.interpret(
                    message,
                    self.flow.state.model_copy(deep=True),
                    previous_summary=self.last_summary,
                )
            except LLMError as exc:
                self.flow.state.last_error_code = exc.code
                record(Event.EXTERNAL_API_FAILED, self.flow.state.session_id, error_code=exc.code)
                code = (
                    CriticalFailureCode.INVALID_LLM_OUTPUT
                    if isinstance(exc, LLMStructuredOutputError)
                    else CriticalFailureCode.LLM_UNAVAILABLE
                )
                return CRITICAL_MESSAGES[code]
        response = await self.flow.process(result)
        if isinstance(response, CriticalFailure):
            return CRITICAL_MESSAGES[response.code]
        return await self._render_outcome(response, result.user_tone)
