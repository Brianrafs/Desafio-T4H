from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import OUTPUT_TYPES
from banco_agil.models.errors import LLMError
from banco_agil.models.state import ConversationStatus
from banco_agil.observability import Event, record
from banco_agil.presentation import (
    CLOSED,
    WELCOME,
    with_lia_voice,
    without_identity_confirmation,
)
from banco_agil.providers.groq import LLMProvider


class Conversation:
    def __init__(self, flow: BankingFlow, provider: LLMProvider):
        self.flow, self.provider = flow, provider
        self.last_reply: str | None = WELCOME

    async def send(self, message: str) -> str:
        if self.flow.state.status == ConversationStatus.FINISHED:
            return CLOSED
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
                    message, self.flow.state.model_copy(deep=True), last_reply=self.last_reply
                )
            except LLMError as exc:
                self.flow.state.last_error_code = exc.code
                record(Event.EXTERNAL_API_FAILED, self.flow.state.session_id, error_code=exc.code)
                return exc.user_message
        response = await self.flow.process(result)
        # Um erro não substitui a pergunta que o cliente estava respondendo.
        if self.flow.state.last_error_code is None:
            if (
                self.flow.state.status != ConversationStatus.FINISHED
                and result.information_topic is None
            ):
                response = with_lia_voice(response, result.message)
            self.last_reply = without_identity_confirmation(response)
        return response
