import httpx
import pytest

from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.models.agent_outputs import TriageTurnResult
from banco_agil.models.errors import ExchangeServiceUnavailableError, InvalidCurrencyError
from banco_agil.services.exchange_service import ExchangeService


@pytest.mark.parametrize(
    "statuses,calls,error",
    [
        ([200], 1, None),
        ([500, 200], 2, None),
        ([500, 500], 2, ExchangeServiceUnavailableError),
        ([404], 1, InvalidCurrencyError),
        ([429], 1, ExchangeServiceUnavailableError),
    ],
)
async def test_http_policy(statuses, calls, error):
    seen = []

    def respond(request):
        seen.append(request)
        assert request.url.path == "/json/last/USD-BRL"
        assert request.headers["x-api-key"] == "test-key"
        assert request.extensions["timeout"]["read"] == 5
        return httpx.Response(
            statuses[len(seen) - 1], json={"USDBRL": {"bid": "5.1234", "timestamp": "1750000000"}}
        )

    service = ExchangeService("test-key", httpx.MockTransport(respond))
    if error:
        with pytest.raises(error):
            await service.get_exchange_rate("USD")
    else:
        result = await service.get_exchange_rate("USD")
        assert str(result.bid) == "5.1234"
        assert result.quoted_at is not None
    assert len(seen) == calls


async def test_timeout_retries_once():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(ExchangeServiceUnavailableError):
        await ExchangeService(transport=httpx.MockTransport(timeout)).get_exchange_rate("EUR")
    assert len(calls) == 2


@pytest.mark.parametrize("body", [{}, {"GBPBRL": {"bid": "NaN"}}, {"GBPBRL": {"bid": "-1"}}])
async def test_invalid_payload(body):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(ExchangeServiceUnavailableError):
        await ExchangeService(transport=transport).get_exchange_rate("GBP")


async def test_unsupported_currency():
    with pytest.raises(InvalidCurrencyError):
        await ExchangeService().get_exchange_rate("BTC")


async def test_exchange_quote_fallback_resolves_private_values_after_composition(data_dir):
    class QuoteProvider:
        async def interpret(self, message, state, *, previous_summary=None):
            return TriageTurnResult(
                cpf="00000000001",
                birth_date="1990-01-15",
                detected_intent="exchange_rate",
                currency="USD",
            )

        async def compose(self, brief, *, previous_summary=None):
            serialized = brief.model_dump_json()
            assert "5.0000" not in serialized
            assert "15/06/2025" not in serialized
            assert "1750000000" not in serialized
            return None

    exchange = ExchangeService(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"USDBRL": {"bid": "5", "timestamp": "1750000000"}}
            )
        )
    )
    conversation = Conversation(BankingFlow(data_dir, exchange), QuoteProvider())

    reply = await conversation.send("Quanto está o dólar?")

    assert "1 USD = R$ 5.0000" in reply
    assert "15/06/2025 às 15:06 UTC" in reply
    assert conversation.last_summary.events == (
        "authentication_succeeded",
        "exchange_quote_found",
    )
