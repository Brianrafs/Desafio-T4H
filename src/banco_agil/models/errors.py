from banco_agil.models.domain import Model


class BankingError(Exception):
    code = "banking_error"
    user_message = (
        "Não consegui concluir esse pedido agora.\n\nPodemos tentar novamente em instantes?"
    )
    retryable = True


class DomainError(BankingError):
    retryable = False


class AuthorizationError(DomainError):
    code = "unauthorized"
    user_message = (
        "Ainda precisamos concluir a etapa atual para seguir com esse pedido.\n\n"
        "Posso ajudar você a continuar ou **encerrar** a conversa, se preferir."
    )


class InvalidCreditLimitError(DomainError):
    code = "invalid_limit"
    user_message = (
        "Vamos ajustar o valor? O limite precisa ser **maior que zero**, "
        "com até **duas casas decimais**.\n\nQual limite total você gostaria de solicitar?"
    )


class ScoreRangeNotFoundError(DomainError):
    code = "score_range_not_found"
    user_message = (
        "A análise de crédito está **indisponível** no momento.\n\n"
        "Seu atendimento continua aberto. Podemos tentar novamente em instantes."
    )


class InfrastructureError(BankingError):
    pass


class RepositoryError(InfrastructureError):
    code = "repository_error"
    user_message = (
        "Tive uma dificuldade para acessar os dados agora.\n\n"
        "Podemos **tentar novamente**? Vou manter a conversa nesta etapa."
    )


class ExternalServiceError(BankingError):
    pass


class ExchangeServiceUnavailableError(ExternalServiceError):
    code = "exchange_unavailable"
    user_message = (
        "A cotação está **indisponível** neste momento.\n\n"
        "Você pode tentar outra vez em instantes ou me pedir uma **consulta de limite**."
    )


class InvalidCurrencyError(DomainError):
    code = "invalid_currency"
    user_message = (
        "Por enquanto, consigo consultar estas moedas:\n\n"
        "- **Dólar** — USD\n- **Euro** — EUR\n- **Libra** — GBP\n\nQual delas você prefere?"
    )


class LLMError(BankingError):
    code = "llm_unavailable"
    user_message = (
        "Tive uma dificuldade para responder agora, mas **sua conversa continua aqui**.\n\n"
        "Pode tentar novamente em instantes? Se preferir, você também pode **encerrar**."
    )


class LLMStructuredOutputError(LLMError):
    code = "invalid_llm_output"
    user_message = (
        "Desculpe, não consegui interpretar sua mensagem desta vez.\n\n"
        "Pode me contar de outro jeito? **Seguimos de onde paramos.**"
    )


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    user_message = (
        "Preciso de uma pequena pausa antes de responder de novo.\n\n"
        "**Aguarde um minuto e tente novamente**, por favor. "
        "Sua conversa e a etapa atual estão preservadas."
    )


class ToolError(Model):
    code: str
    user_message: str
    retryable: bool

    @classmethod
    def from_exception(cls, error: BankingError):
        return cls(code=error.code, user_message=error.user_message, retryable=error.retryable)
