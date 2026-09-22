from banco_agil.models.domain import Model


class BankingError(Exception):
    code = "banking_error"
    user_message = "Não foi possível concluir agora. Tente novamente."
    retryable = True


class DomainError(BankingError):
    retryable = False


class AuthorizationError(DomainError):
    code = "unauthorized"
    user_message = "Esta operação não está disponível nesta etapa do atendimento."


class InvalidCreditLimitError(DomainError):
    code = "invalid_limit"
    user_message = "Informe um limite positivo, com no máximo duas casas decimais."


class ScoreRangeNotFoundError(DomainError):
    code = "score_range_not_found"
    user_message = "A análise de crédito está indisponível no momento."


class InfrastructureError(BankingError):
    pass


class RepositoryError(InfrastructureError):
    code = "repository_error"
    user_message = "Os dados estão temporariamente indisponíveis. Tente novamente."


class ExternalServiceError(BankingError):
    pass


class ExchangeServiceUnavailableError(ExternalServiceError):
    code = "exchange_unavailable"
    user_message = "A cotação está indisponível no momento. Tente novamente em instantes."


class InvalidCurrencyError(DomainError):
    code = "invalid_currency"
    user_message = "Informe uma moeda suportada: USD, EUR ou GBP."


class LLMError(BankingError):
    code = "llm_unavailable"
    user_message = "O atendimento está temporariamente indisponível. Tente novamente em instantes."


class LLMStructuredOutputError(LLMError):
    code = "invalid_llm_output"
    user_message = "Não consegui entender. Pode reformular sua mensagem?"


class ToolError(Model):
    code: str
    user_message: str
    retryable: bool

    @classmethod
    def from_exception(cls, error: BankingError):
        return cls(code=error.code, user_message=error.user_message, retryable=error.retryable)
