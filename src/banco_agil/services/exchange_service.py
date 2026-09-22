from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from banco_agil.models.domain import ExchangeRate, SupportedCurrency
from banco_agil.models.errors import ExchangeServiceUnavailableError, InvalidCurrencyError


class ExchangeService:
    def __init__(self, api_key: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.api_key, self.transport = api_key, transport

    async def get_exchange_rate(self, currency: SupportedCurrency) -> ExchangeRate:
        try:
            currency = SupportedCurrency(currency)
        except ValueError as exc:
            raise InvalidCurrencyError() from exc
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(
            base_url="https://economia.awesomeapi.com.br",
            timeout=5,
            headers=headers,
            transport=self.transport,
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.get(f"/json/last/{currency.value}-BRL")
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    if attempt == 0:
                        continue
                    raise ExchangeServiceUnavailableError() from exc
                except httpx.HTTPError as exc:
                    raise ExchangeServiceUnavailableError() from exc
                if response.status_code >= 500 and attempt == 0:
                    continue
                if response.status_code == 404:
                    raise InvalidCurrencyError()
                if response.status_code != 200:
                    raise ExchangeServiceUnavailableError()
                try:
                    quote = response.json()[f"{currency.value}BRL"]
                    timestamp = quote.get("timestamp")
                    return ExchangeRate(
                        currency=currency,
                        bid=quote["bid"],
                        quoted_at=datetime.fromtimestamp(int(timestamp), UTC)
                        if timestamp
                        else None,
                    )
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    OverflowError,
                    OSError,
                    ValidationError,
                ) as exc:
                    raise ExchangeServiceUnavailableError() from exc
        raise ExchangeServiceUnavailableError()
