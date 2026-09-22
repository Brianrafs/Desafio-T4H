import inspect
from collections.abc import Callable
from datetime import date

from crewai.tools import BaseTool
from pydantic import Field, PrivateAttr

from banco_agil.models.domain import Model, Money, SupportedCurrency
from banco_agil.models.errors import AuthorizationError, ToolError
from banco_agil.tools.session_tools import TOOL_SCOPES


class NoArguments(Model):
    pass


class AuthenticationArguments(Model):
    cpf: str
    birth_date: date


class IncreaseArguments(Model):
    requested_limit: Money


class ExchangeArguments(Model):
    currency: SupportedCurrency


ARGUMENTS = {
    "authenticate_customer": AuthenticationArguments,
    "get_credit_limit": NoArguments,
    "request_credit_limit_increase": IncreaseArguments,
    "submit_credit_interview": NoArguments,
    "get_exchange_rate": ExchangeArguments,
    "end_conversation": NoArguments,
}


class FlowAuthorizedTool(BaseTool):
    """Tool executável cujo acesso é liberado somente após validar o turno.

    O agente recebe esta mesma tool, mas chamadas durante interpretação são
    recusadas. O Flow abre a autorização exclusivamente para os argumentos validados.
    """

    operation: Callable = Field(exclude=True, repr=False)
    _authorized: bool = PrivateAttr(default=False)

    def _run(self, **kwargs):
        if not self._authorized:
            return ToolError.from_exception(AuthorizationError()).model_dump_json()
        arguments = self.args_schema.model_validate(kwargs)
        return self.operation(**arguments.model_dump())

    async def invoke_from_flow(self, **kwargs):
        self._authorized = True
        try:
            value = self._run(**kwargs)
            if inspect.isawaitable(value):
                value = await value
            return value
        finally:
            self._authorized = False


def create_tools(session_tools) -> dict[str, FlowAuthorizedTool]:
    return {
        name: FlowAuthorizedTool(
            name=name,
            description="Operação disponível após a validação do turno pelo Flow.",
            args_schema=ARGUMENTS[name],
            operation=getattr(session_tools, name),
        )
        for name in {name for scope in TOOL_SCOPES.values() for name in scope}
    }
