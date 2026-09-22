from decimal import Decimal

import pytest

from banco_agil.models.errors import InvalidCreditLimitError, RepositoryError
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.credit_service import CreditService


def test_get_limit(data_dir):
    assert CreditService(CustomerRepository(data_dir)).get_limit("00000000001") == 1000


def test_unknown_customer(data_dir):
    with pytest.raises(RepositoryError):
        CreditService(CustomerRepository(data_dir)).get_limit("00000000099")


@pytest.mark.parametrize(
    "amount,status,limit",
    [
        (2000, "aprovado", 2000),
        (2001, "rejeitado", 1000),
        (1000, "rejeitado", 1000),
        (500, "rejeitado", 1000),
    ],
)
def test_increase(data_dir, amount, status, limit):
    service = CreditService(CustomerRepository(data_dir))
    result = service.request_increase("00000000001", Decimal(amount))
    assert result.status_pedido == status
    assert service.get_limit("00000000001") == limit
    assert service.requests.read() == [result]


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "1.001"])
def test_invalid_increase_is_not_persisted(data_dir, amount):
    service = CreditService(CustomerRepository(data_dir))
    with pytest.raises(InvalidCreditLimitError):
        service.request_increase("00000000001", Decimal(amount))
    assert service.requests.read() == []


def test_recovers_interrupted_approval_without_duplicate(data_dir, monkeypatch):
    service = CreditService(CustomerRepository(data_dir))
    save = CreditRequestRepository.save

    def fail_save(self, request):
        raise RepositoryError()

    monkeypatch.setattr(CreditRequestRepository, "save", fail_save)
    with pytest.raises(RepositoryError):
        service.request_increase("00000000001", Decimal(2000))
    assert service.requests.read()[0].status_pedido == "pendente"
    monkeypatch.setattr(CreditRequestRepository, "save", save)
    assert service.request_increase("00000000001", Decimal(2000)).status_pedido == "aprovado"
    assert len(service.requests.read()) == 1
    assert service.get_limit("00000000001") == 2000
