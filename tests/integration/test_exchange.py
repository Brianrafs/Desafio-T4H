import httpx
import pytest

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
