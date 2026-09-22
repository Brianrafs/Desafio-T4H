import inspect
from datetime import date
from decimal import Decimal

import pytest

from banco_agil.models.errors import AuthorizationError
from banco_agil.models.state import AgentType, SessionState
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.authentication_service import AuthenticationService
from banco_agil.services.credit_service import CreditService
from banco_agil.services.exchange_service import ExchangeService
from banco_agil.services.score_service import ScoreService
from banco_agil.tools.session_tools import TOOL_SCOPES, SessionTools


@pytest.fixture
def session_tools(data_dir):
    state = SessionState()
    customers = CustomerRepository(data_dir)
    credit = CreditService(customers)
    tools = SessionTools(
        lambda: state,
        AuthenticationService(customers),
        credit,
        ScoreService(customers, credit),
        ExchangeService(),
    )
    return state, tools


def test_protected_tools_require_authentication(session_tools):
    state, tools = session_tools
    state.current_agent = AgentType.CREDIT
    with pytest.raises(AuthorizationError):
        tools.get_credit_limit()


def test_no_cpf_in_protected_signatures(session_tools):
    state, tools = session_tools
    for method in (
        tools.get_credit_limit,
        tools.request_credit_limit_increase,
        tools.submit_credit_interview,
        tools.get_exchange_rate,
    ):
        assert "cpf" not in inspect.signature(method).parameters
    state.authenticated = True
    state.authenticated_customer_cpf = "00000000001"
    state.current_agent = AgentType.CREDIT
    assert tools.get_credit_limit() == 1000
    state.current_agent = AgentType.EXCHANGE
    with pytest.raises(AuthorizationError):
        tools.get_credit_limit()


def test_authentication_and_scope(session_tools):
    state, tools = session_tools
    assert tools.authenticate_customer("00000000001", date(1990, 1, 15)) is not None
    assert not state.authenticated  # O Flow controla o estado.
    assert "request_credit_limit_increase" not in TOOL_SCOPES[AgentType.TRIAGE]


def test_credit_requires_validated_amount(session_tools):
    state, tools = session_tools
    state.authenticated = True
    state.authenticated_customer_cpf = "00000000001"
    state.current_agent = AgentType.CREDIT
    with pytest.raises(AuthorizationError):
        tools.request_credit_limit_increase(Decimal(2000))
    state.credit.awaiting_requested_limit = True
    state.credit.requested_limit = Decimal(2000)
    assert tools.request_credit_limit_increase(Decimal(2000)).status_pedido == "aprovado"
